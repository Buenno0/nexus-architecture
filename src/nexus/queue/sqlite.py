"""Fila local sobre SQLite — ADR-004.

Implementa as mesmas primitivas do SQS: visibility timeout, contagem de entregas,
backoff e Dead Letter Queue. O objetivo nao e substituir o SQS, e **tornar o mecanismo
visivel**: cada garantia aqui e uma linha de SQL que da para ler, em vez de um
comportamento importado de uma biblioteca.

A troca por SQS na Fase 3 e uma mudanca de configuracao, porque a ingestao e o worker
dependem de ``QueueClient``, nunca desta classe.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from nexus.queue.client import (
    FailOutcome,
    QueueClient,
    QueueMessage,
    QueueStats,
    ReceivedMessage,
)
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings, get_settings
from nexus.shared.errors import QueuePublishError
from nexus.shared.identity import new_ulid
from nexus.shared.logging import get_logger

logger = get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    message_id     TEXT PRIMARY KEY,
    event_id       TEXT NOT NULL UNIQUE,
    record_id      TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    enqueued_at    TEXT NOT NULL,
    visible_at     TEXT NOT NULL,
    receive_count  INTEGER NOT NULL DEFAULT 0,
    receipt        TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_visible ON messages(visible_at);
CREATE INDEX IF NOT EXISTS idx_messages_receipt ON messages(receipt);

CREATE TABLE IF NOT EXISTS dead_letters (
    message_id     TEXT PRIMARY KEY,
    event_id       TEXT NOT NULL,
    record_id      TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    enqueued_at    TEXT NOT NULL,
    failed_at      TEXT NOT NULL,
    receive_count  INTEGER NOT NULL,
    last_error     TEXT
);
"""

MAX_ERROR_LENGTH = 512


class SqliteQueue(QueueClient):
    """Fila persistente em arquivo SQLite."""

    def __init__(self, path: str | Path | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._path = Path(path or self._settings.queue_path)
        if self._path.parent != Path():
            self._path.parent.mkdir(parents=True, exist_ok=True)
        # Conexoes sao por thread: objetos sqlite3 nao podem ser compartilhados entre
        # threads, e a API serve requisicoes num threadpool.
        self._local = threading.local()
        # Registro de todas as conexoes abertas. Sem ele, ``close`` fecharia apenas a
        # conexao da thread que chamou, e as criadas por outras threads ficariam
        # abertas ate a coleta de lixo — descritores de arquivo vazando em silencio.
        self._connections: list[sqlite3.Connection] = []
        self._connections_lock = threading.Lock()
        self._ensure_schema()

    # ------------------------------------------------------------------ conexao

    @property
    def _connection(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self._path,
                # Controlamos as transacoes explicitamente: sem BEGIN IMMEDIATE a
                # reivindicacao de mensagens tem corrida entre leitura e escrita.
                isolation_level=None,
                timeout=self._settings.queue_busy_timeout_seconds,
                # Cada thread USA apenas a sua propria conexao (thread-local acima).
                # A permissao existe para que ``close`` possa fecha-las todas a partir
                # de uma unica thread; sem ela o sqlite3 recusa e os descritores vazam.
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            # busy_timeout PRIMEIRO: sem ele, os PRAGMAs seguintes falham de imediato
            # em vez de esperar, quando varias conexoes abrem ao mesmo tempo.
            conn.execute(
                f"PRAGMA busy_timeout={int(self._settings.queue_busy_timeout_seconds * 1000)}"
            )
            try:
                # WAL permite leitor e escritor simultaneos — API publicando enquanto o
                # worker consome.
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                # Outra conexao esta trocando o modo neste instante. WAL e persistente
                # no arquivo, entao basta que uma conexao tenha conseguido definir.
                logger.debug("queue_wal_already_set")
            # FULL: a mensagem precisa sobreviver a queda do processo. Uma fila que
            # perde mensagens num crash nao e uma fila.
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
            with self._connections_lock:
                self._connections.append(conn)
        return conn

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Transacao de escrita com bloqueio adquirido na abertura.

        ``BEGIN IMMEDIATE`` e o ponto critico da fila: ele adquire o bloqueio de escrita
        antes de ler. Com o ``BEGIN`` padrao (diferido), dois workers leem as mesmas
        linhas, ambos as consideram disponiveis e ambos as reivindicam — entrega dupla
        silenciosa.
        """
        conn = self._connection
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    def _ensure_schema(self) -> None:
        # executescript gerencia a propria transacao; envolve-lo em BEGIN/COMMIT
        # explicito resulta em "cannot commit - no transaction is active".
        self._connection.executescript(SCHEMA)

    def close(self) -> None:
        """Fecha todas as conexoes abertas por esta instancia, de qualquer thread."""
        with self._connections_lock:
            pendentes, self._connections = self._connections, []
        for conn in pendentes:
            try:
                conn.close()
            except sqlite3.Error as exc:
                # Nao silenciar: uma falha aqui significa descritor vazando, e foi
                # exatamente um ``suppress`` generico que escondeu esse defeito antes.
                logger.warning("queue_connection_close_failed", extra={"reason": str(exc)})
        self._local.conn = None

    # ------------------------------------------------------------------ contrato

    @property
    def is_enabled(self) -> bool:
        return True

    def publish(self, message: QueueMessage) -> bool:
        """Publica a mensagem. ``False`` se o evento ja estava na fila.

        ``INSERT OR IGNORE`` sobre ``event_id`` absorve a republicacao que o ADR-003
        admite: o dispatcher pode republicar um evento se cair antes de marcar o
        despacho.

        Essa protecao vale apenas enquanto a mensagem esta na fila. Depois de consumida
        e apagada, uma republicacao entra de novo — a garantia de efeito unico e a
        escrita condicional do marcador de processamento (ADR-005), nao esta linha.
        """
        now = utcnow()
        try:
            with self._write_transaction() as conn:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO messages
                        (message_id, event_id, record_id, correlation_id,
                         enqueued_at, visible_at, receive_count, receipt)
                    VALUES (?, ?, ?, ?, ?, ?, 0, NULL)
                    """,
                    (
                        new_ulid(),
                        message.event_id,
                        message.record_id,
                        message.correlation_id,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
        except sqlite3.Error as exc:
            logger.error("queue_publish_failed", extra={"reason": str(exc)})
            raise QueuePublishError("Falha ao publicar na fila") from exc

        if cursor.rowcount == 0:
            logger.info("queue_publish_duplicate", extra={"event_id": message.event_id})
            return False
        return True

    def receive(
        self, *, max_messages: int, visibility_timeout_seconds: float | None = None
    ) -> list[ReceivedMessage]:
        """Reivindica um lote de mensagens visiveis, atomicamente."""
        if max_messages < 1:
            return []

        timeout = (
            visibility_timeout_seconds
            if visibility_timeout_seconds is not None
            else self._settings.queue_visibility_timeout_seconds
        )
        now = utcnow()
        invisible_until = now + timedelta(seconds=timeout)
        # O recibo identifica UMA ENTREGA DE UMA MENSAGEM, nunca o lote.
        #
        # Com recibo unico por lote, "DELETE WHERE receipt = ?" apagaria todas as
        # mensagens do lote ao confirmar a primeira: se o worker caisse no meio, as
        # restantes sumiriam sem terem sido processadas — perda silenciosa. E uma
        # unica falha mandaria o lote inteiro para a DLQ.
        #
        # Concatenar o token do lote com o message_id da proria linha da a cada
        # mensagem um recibo distinto numa unica instrucao.
        batch_token = new_ulid()

        with self._write_transaction() as conn:
            rows = conn.execute(
                """
                UPDATE messages
                   SET visible_at    = ?,
                       receive_count = receive_count + 1,
                       receipt       = ? || ':' || message_id
                 WHERE message_id IN (
                       SELECT message_id FROM messages
                        WHERE visible_at <= ?
                        ORDER BY visible_at
                        LIMIT ?
                 )
             RETURNING message_id, event_id, record_id, correlation_id,
                       enqueued_at, receive_count, receipt
                """,
                (invisible_until.isoformat(), batch_token, now.isoformat(), max_messages),
            ).fetchall()

        return [
            ReceivedMessage(
                message_id=row["message_id"],
                event_id=row["event_id"],
                record_id=row["record_id"],
                correlation_id=row["correlation_id"],
                receipt=row["receipt"],
                receive_count=row["receive_count"],
                enqueued_at=datetime.fromisoformat(row["enqueued_at"]),
            )
            for row in rows
        ]

    def delete(self, receipt: str) -> bool:
        """Remove a mensagem desta entrega.

        O recibo entra na condicao: se o prazo expirou e a mensagem foi reentregue a
        outro consumidor, o recibo antigo nao casa e nada e apagado. Sem isso, um worker
        lento apagaria trabalho que outro ja reivindicou e ainda esta executando.
        """
        with self._write_transaction() as conn:
            cursor = conn.execute("DELETE FROM messages WHERE receipt = ?", (receipt,))
        return cursor.rowcount > 0

    def fail(self, receipt: str, *, error: str) -> FailOutcome:
        """Registra falha: retentativa com backoff, ou DLQ ao esgotar o limite."""
        now = utcnow()
        truncated = error[:MAX_ERROR_LENGTH]

        with self._write_transaction() as conn:
            row = conn.execute(
                "SELECT message_id, receive_count FROM messages WHERE receipt = ?",
                (receipt,),
            ).fetchone()

            if row is None:
                logger.warning("queue_fail_unknown_receipt")
                return FailOutcome.UNKNOWN_RECEIPT

            if row["receive_count"] >= self._settings.queue_max_receive:
                # Mensagem envenenada: sai do caminho quente para nao bloquear a fila.
                conn.execute(
                    """
                    INSERT OR REPLACE INTO dead_letters
                        (message_id, event_id, record_id, correlation_id,
                         enqueued_at, failed_at, receive_count, last_error)
                    SELECT message_id, event_id, record_id, correlation_id,
                           enqueued_at, ?, receive_count, ?
                      FROM messages WHERE message_id = ?
                    """,
                    (now.isoformat(), truncated, row["message_id"]),
                )
                conn.execute("DELETE FROM messages WHERE message_id = ?", (row["message_id"],))
                outcome = FailOutcome.DEAD_LETTERED
            else:
                backoff = self._settings.queue_retry_backoff_base_seconds * (
                    2 ** (row["receive_count"] - 1)
                )
                conn.execute(
                    "UPDATE messages SET visible_at = ?, receipt = NULL WHERE message_id = ?",
                    ((now + timedelta(seconds=backoff)).isoformat(), row["message_id"]),
                )
                outcome = FailOutcome.RETRY

        logger.warning(
            "queue_message_failed",
            extra={
                "message_id": row["message_id"],
                "receive_count": row["receive_count"],
                "outcome": outcome.value,
                "reason": truncated[:256],
            },
        )
        return outcome

    def dead_letter(self, receipt: str, *, error: str) -> bool:
        """Move direto para a DLQ, ignorando o orcamento de tentativas."""
        now = utcnow()
        truncated = error[:MAX_ERROR_LENGTH]

        with self._write_transaction() as conn:
            row = conn.execute(
                "SELECT message_id FROM messages WHERE receipt = ?", (receipt,)
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                """
                INSERT OR REPLACE INTO dead_letters
                    (message_id, event_id, record_id, correlation_id,
                     enqueued_at, failed_at, receive_count, last_error)
                SELECT message_id, event_id, record_id, correlation_id,
                       enqueued_at, ?, receive_count, ?
                  FROM messages WHERE message_id = ?
                """,
                (now.isoformat(), truncated, row["message_id"]),
            )
            conn.execute("DELETE FROM messages WHERE message_id = ?", (row["message_id"],))

        logger.warning(
            "queue_message_dead_lettered",
            extra={"message_id": row["message_id"], "reason": truncated[:256]},
        )
        return True

    def stats(self) -> QueueStats:
        now = utcnow().isoformat()
        conn = self._connection
        pending = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE visible_at <= ?", (now,)
        ).fetchone()[0]
        in_flight = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE visible_at > ?", (now,)
        ).fetchone()[0]
        dead = conn.execute("SELECT COUNT(*) FROM dead_letters").fetchone()[0]
        return QueueStats(pending=pending, in_flight=in_flight, dead=dead)

    def redrive(self, *, limit: int) -> int:
        """Devolve mensagens da DLQ para a fila, com contagem zerada.

        A contagem volta a zero de proposito: o redrive e feito **depois** de corrigir
        a causa da falha, entao a mensagem merece o mesmo orcamento de tentativas que
        uma mensagem nova. Mantê-la no limite faria a primeira falha transitoria
        devolve-la direto para a DLQ.
        """
        if limit < 1:
            return 0
        now = utcnow().isoformat()
        with self._write_transaction() as conn:
            rows = conn.execute(
                "SELECT message_id FROM dead_letters ORDER BY failed_at LIMIT ?", (limit,)
            ).fetchall()
            if not rows:
                return 0
            ids = [row["message_id"] for row in rows]
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"""
                INSERT OR IGNORE INTO messages
                    (message_id, event_id, record_id, correlation_id,
                     enqueued_at, visible_at, receive_count, receipt)
                SELECT message_id, event_id, record_id, correlation_id,
                       enqueued_at, ?, 0, NULL
                  FROM dead_letters WHERE message_id IN ({placeholders})
                """,
                (now, *ids),
            )
            conn.execute(
                f"DELETE FROM dead_letters WHERE message_id IN ({placeholders})",
                ids,
            )

        logger.info("queue_redrive", extra={"count": len(ids)})
        return len(ids)

    # -------------------------------------------------------------------- testes

    def purge(self) -> None:
        """Esvazia a fila e a DLQ. Destrutivo — uso em teste e em reset explicito."""
        with self._write_transaction() as conn:
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM dead_letters")
