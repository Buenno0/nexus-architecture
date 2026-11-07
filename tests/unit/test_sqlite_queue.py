"""Testes da fila SQLite — ADR-004.

Isolados: cada teste recebe um arquivo proprio em diretorio temporario. Sem Docker,
sem rede, sem estado compartilhado.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from nexus.queue.client import FailOutcome, QueueMessage
from nexus.queue.sqlite import SqliteQueue
from nexus.shared.config import Settings


@pytest.fixture
def queue_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="local",
        queue_path=str(tmp_path / "fila.db"),
        queue_visibility_timeout_seconds=30.0,
        queue_max_receive=3,
        queue_retry_backoff_base_seconds=0.01,
    )


@pytest.fixture
def queue(queue_settings: Settings) -> Iterator[SqliteQueue]:
    fila = SqliteQueue(settings=queue_settings)
    try:
        yield fila
    finally:
        fila.close()


def msg(n: int = 1) -> QueueMessage:
    return QueueMessage(event_id=f"evt-{n}", record_id=f"rec-{n}", correlation_id=f"corr-{n}")


class TestPublicacao:
    def test_publica_e_fica_pendente(self, queue: SqliteQueue) -> None:
        assert queue.publish(msg()) is True
        assert queue.stats().pending == 1

    def test_evento_repetido_e_ignorado(self, queue: SqliteQueue) -> None:
        """O dispatcher pode republicar apos crash — ADR-003. Nao pode duplicar."""
        assert queue.publish(msg()) is True
        assert queue.publish(msg()) is False
        assert queue.stats().pending == 1

    def test_eventos_distintos_coexistem(self, queue: SqliteQueue) -> None:
        for i in range(5):
            queue.publish(msg(i))
        assert queue.stats().pending == 5

    def test_sobrevive_a_nova_conexao(self, queue_settings: Settings) -> None:
        """Uma fila que perde mensagens ao reiniciar nao e uma fila."""
        primeira = SqliteQueue(settings=queue_settings)
        primeira.publish(msg())
        primeira.close()

        segunda = SqliteQueue(settings=queue_settings)
        try:
            assert segunda.stats().pending == 1
        finally:
            segunda.close()


class TestRecebimento:
    def test_entrega_e_torna_invisivel(self, queue: SqliteQueue) -> None:
        queue.publish(msg())
        recebidas = queue.receive(max_messages=10)

        assert len(recebidas) == 1
        assert recebidas[0].event_id == "evt-1"
        assert recebidas[0].receive_count == 1

        stats = queue.stats()
        assert stats.pending == 0
        assert stats.in_flight == 1

    def test_segunda_leitura_nao_ve_a_mensagem(self, queue: SqliteQueue) -> None:
        queue.publish(msg())
        queue.receive(max_messages=10)
        assert queue.receive(max_messages=10) == []

    def test_respeita_o_tamanho_do_lote(self, queue: SqliteQueue) -> None:
        for i in range(10):
            queue.publish(msg(i))
        assert len(queue.receive(max_messages=3)) == 3

    def test_fila_vazia_devolve_lista_vazia(self, queue: SqliteQueue) -> None:
        assert queue.receive(max_messages=10) == []

    def test_lote_invalido_devolve_vazio(self, queue: SqliteQueue) -> None:
        queue.publish(msg())
        assert queue.receive(max_messages=0) == []

    def test_mensagem_reaparece_apos_o_prazo(self, queue: SqliteQueue) -> None:
        """A garantia contra trabalho preso num processo que morreu."""
        queue.publish(msg())
        queue.receive(max_messages=10, visibility_timeout_seconds=0.05)
        assert queue.receive(max_messages=10) == []

        time.sleep(0.1)
        reentregue = queue.receive(max_messages=10)
        assert len(reentregue) == 1
        assert reentregue[0].receive_count == 2

    def test_ordem_por_visibilidade(self, queue: SqliteQueue) -> None:
        for i in range(3):
            queue.publish(msg(i))
        recebidas = queue.receive(max_messages=3)
        assert [m.event_id for m in recebidas] == ["evt-0", "evt-1", "evt-2"]


class TestRecibo:
    def test_apaga_com_recibo_valido(self, queue: SqliteQueue) -> None:
        queue.publish(msg())
        recebida = queue.receive(max_messages=1)[0]
        assert queue.delete(recebida.receipt) is True
        assert queue.stats().total == 0

    def test_recibo_desconhecido_nao_apaga(self, queue: SqliteQueue) -> None:
        queue.publish(msg())
        queue.receive(max_messages=1)
        assert queue.delete("recibo-inventado") is False
        assert queue.stats().in_flight == 1

    def test_recibo_vencido_nao_apaga_trabalho_alheio(self, queue: SqliteQueue) -> None:
        """Worker lento nao pode apagar o que outro ja reivindicou."""
        queue.publish(msg())
        antiga = queue.receive(max_messages=1, visibility_timeout_seconds=0.05)[0]
        time.sleep(0.1)
        nova = queue.receive(max_messages=1)[0]

        assert queue.delete(antiga.receipt) is False
        assert queue.stats().in_flight == 1
        assert queue.delete(nova.receipt) is True


class TestFalhaEDlq:
    def test_primeira_falha_reagenda(self, queue: SqliteQueue) -> None:
        queue.publish(msg())
        recebida = queue.receive(max_messages=1)[0]
        assert queue.fail(recebida.receipt, error="falha") is FailOutcome.RETRY
        assert queue.stats().dead == 0

    def test_backoff_adia_a_reentrega(self, queue: SqliteQueue) -> None:
        queue.publish(msg())
        recebida = queue.receive(max_messages=1)[0]
        queue.fail(recebida.receipt, error="falha")
        # Ainda dentro do backoff configurado.
        assert queue.receive(max_messages=1) == []
        time.sleep(0.05)
        assert len(queue.receive(max_messages=1)) == 1

    def test_vai_para_dlq_ao_esgotar_tentativas(self, queue: SqliteQueue) -> None:
        """Mensagem envenenada nao pode bloquear a fila indefinidamente."""
        queue.publish(msg())
        resultado = None
        for _ in range(3):
            recebida = queue.receive(max_messages=1)[0]
            resultado = queue.fail(recebida.receipt, error="sempre falha")
            time.sleep(0.05)

        assert resultado is FailOutcome.DEAD_LETTERED
        stats = queue.stats()
        assert stats.dead == 1
        assert stats.pending == 0
        assert stats.in_flight == 0

    def test_recibo_desconhecido(self, queue: SqliteQueue) -> None:
        assert queue.fail("nao-existe", error="x") is FailOutcome.UNKNOWN_RECEIPT

    def test_erro_longo_e_truncado(self, queue: SqliteQueue) -> None:
        queue.publish(msg())
        for _ in range(3):
            recebida = queue.receive(max_messages=1)[0]
            queue.fail(recebida.receipt, error="x" * 5_000)
            time.sleep(0.05)

        conn = queue._connection
        erro = conn.execute("SELECT last_error FROM dead_letters").fetchone()[0]
        assert len(erro) <= 512

    def test_mensagem_envenenada_nao_trava_as_demais(self, queue: SqliteQueue) -> None:
        queue.publish(msg(1))
        queue.publish(msg(2))

        for _ in range(3):
            for recebida in queue.receive(max_messages=10):
                if recebida.event_id == "evt-1":
                    queue.fail(recebida.receipt, error="envenenada")
                else:
                    queue.delete(recebida.receipt)
            time.sleep(0.05)

        stats = queue.stats()
        assert stats.dead == 1
        assert stats.pending == 0


class TestRedrive:
    def _envenenar(self, queue: SqliteQueue) -> None:
        queue.publish(msg())
        for _ in range(3):
            recebida = queue.receive(max_messages=1)[0]
            queue.fail(recebida.receipt, error="falha")
            time.sleep(0.05)

    def test_devolve_da_dlq(self, queue: SqliteQueue) -> None:
        self._envenenar(queue)
        assert queue.redrive(limit=10) == 1
        stats = queue.stats()
        assert stats.dead == 0
        assert stats.pending == 1

    def test_zera_a_contagem_de_tentativas(self, queue: SqliteQueue) -> None:
        """Redrive acontece depois de corrigir a causa: a mensagem merece orcamento novo."""
        self._envenenar(queue)
        queue.redrive(limit=10)
        assert queue.receive(max_messages=1)[0].receive_count == 1

    def test_dlq_vazia(self, queue: SqliteQueue) -> None:
        assert queue.redrive(limit=10) == 0

    def test_limite_invalido(self, queue: SqliteQueue) -> None:
        self._envenenar(queue)
        assert queue.redrive(limit=0) == 0
        assert queue.stats().dead == 1


class TestConcorrencia:
    def test_dois_consumidores_nao_recebem_a_mesma_mensagem(self, queue_settings: Settings) -> None:
        """A razao de existir do BEGIN IMMEDIATE.

        Com BEGIN diferido, dois workers leem as mesmas linhas, ambos as julgam
        disponiveis e ambos as reivindicam — entrega dupla silenciosa.
        """
        escritor = SqliteQueue(settings=queue_settings)
        for i in range(200):
            escritor.publish(msg(i))
        escritor.close()

        def consumir(_: int) -> list[str]:
            fila = SqliteQueue(settings=queue_settings)
            try:
                coletadas: list[str] = []
                while True:
                    lote = fila.receive(max_messages=7)
                    if not lote:
                        return coletadas
                    coletadas.extend(m.event_id for m in lote)
            finally:
                fila.close()

        with ThreadPoolExecutor(max_workers=4) as pool:
            resultados = list(pool.map(consumir, range(4)))

        todas = [event_id for parcial in resultados for event_id in parcial]
        assert len(todas) == 200, "nenhuma mensagem pode ser perdida"
        assert len(set(todas)) == 200, "nenhuma mensagem pode ser entregue duas vezes"

    def test_publicacao_concorrente_do_mesmo_evento(self, queue_settings: Settings) -> None:
        def publicar(_: int) -> bool:
            fila = SqliteQueue(settings=queue_settings)
            try:
                return fila.publish(msg(99))
            finally:
                fila.close()

        with ThreadPoolExecutor(max_workers=8) as pool:
            sucessos = sum(pool.map(publicar, range(20)))

        assert sucessos == 1, "exatamente uma publicacao pode vencer"
        fila = SqliteQueue(settings=queue_settings)
        try:
            assert fila.stats().pending == 1
        finally:
            fila.close()


class TestPurge:
    def test_esvazia_tudo(self, queue: SqliteQueue) -> None:
        queue.publish(msg(1))
        queue.publish(msg(2))
        queue.receive(max_messages=1)
        queue.purge()
        assert queue.stats().total == 0


class TestRecibosPorMensagem:
    """O recibo identifica uma entrega de uma mensagem, nunca o lote inteiro."""

    def test_cada_mensagem_recebe_recibo_proprio(self, queue: SqliteQueue) -> None:
        for i in range(5):
            queue.publish(msg(i))
        recebidas = queue.receive(max_messages=5)
        assert len({m.receipt for m in recebidas}) == 5

    def test_apagar_uma_nao_apaga_o_lote(self, queue: SqliteQueue) -> None:
        """Com recibo de lote, confirmar a primeira apagaria todas as demais.

        O worker cairia no meio do lote e as restantes sumiriam sem processamento —
        perda silenciosa, a classe de defeito que este projeto existe para evitar.
        """
        for i in range(5):
            queue.publish(msg(i))
        recebidas = queue.receive(max_messages=5)

        assert queue.delete(recebidas[0].receipt) is True
        assert queue.stats().in_flight == 4

    def test_falhar_uma_nao_afeta_as_demais(self, queue: SqliteQueue) -> None:
        for i in range(5):
            queue.publish(msg(i))
        recebidas = queue.receive(max_messages=5)

        queue.fail(recebidas[0].receipt, error="falha isolada")
        time.sleep(0.05)  # passa o backoff da que falhou

        # Apenas a que falhou volta; as outras seguem reivindicadas.
        devolvidas = queue.receive(max_messages=10)
        assert [m.event_id for m in devolvidas] == [recebidas[0].event_id]

        for recebida in recebidas[1:]:
            assert queue.delete(recebida.receipt) is True

    def test_dlq_de_uma_nao_leva_o_lote(self, queue: SqliteQueue) -> None:
        for i in range(3):
            queue.publish(msg(i))
        recebidas = queue.receive(max_messages=3)

        assert queue.dead_letter(recebidas[0].receipt, error="envenenada") is True

        stats = queue.stats()
        assert stats.dead == 1
        assert stats.in_flight == 2


class TestCicloDeVidaDaConexao:
    def test_close_fecha_conexoes_de_todas_as_threads(self, queue_settings: Settings) -> None:
        """Fechar so a conexao da thread chamadora vazaria descritores em silencio.

        Regressao de dois defeitos encadeados: ``close`` fechava apenas a conexao da
        thread chamadora, e quando passou a fechar todas, o sqlite3 recusava o
        fechamento entre threads — recusa que um ``suppress`` generico escondia.
        """
        fila = SqliteQueue(settings=queue_settings)
        fila.publish(msg(1))

        def usar(_: int) -> None:
            fila.stats()

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(usar, range(4)))

        abertas = list(fila._connections)
        assert len(abertas) >= 4

        fila.close()

        assert fila._connections == []
        for conexao in abertas:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                conexao.execute("SELECT 1")

    def test_close_e_idempotente(self, queue_settings: Settings) -> None:
        fila = SqliteQueue(settings=queue_settings)
        fila.close()
        fila.close()
