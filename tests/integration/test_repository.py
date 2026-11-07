"""Testes do repositorio contra DynamoDB Local.

Exercitam o que o repositorio falso nao consegue reproduzir: transacoes reais,
condicoes de escrita do motor e o comportamento do indice esparso.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from nexus.persistence.dynamo import DynamoRecordRepository
from nexus.persistence.models import (
    IdempotencyRecord,
    OutboxEvent,
    OutboxStatus,
    RecordType,
    StoredRecord,
)
from nexus.persistence.repository import CommitConflictError
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings
from nexus.shared.errors import InvalidPaginationCursorError
from nexus.shared.identity import natural_key, new_ulid, record_fingerprint

pytestmark = pytest.mark.integration


def build_trio(
    *, source: str = "it", phone: str = "111", key: str = "k1"
) -> tuple[StoredRecord, OutboxEvent, IdempotencyRecord]:
    now = utcnow()
    normalized = {"document": "12345678909", "phone": phone}
    record_id, event_id = new_ulid(), new_ulid()
    record = StoredRecord(
        record_id=record_id,
        record_type=RecordType.PERSON,
        source=source,
        natural_key=natural_key("person", normalized),
        record_fingerprint=record_fingerprint("person", normalized),
        payload=normalized,
        normalized=normalized,
        correlation_id="corr",
        created_at=now,
    )
    event = OutboxEvent(
        event_id=event_id,
        record_id=record_id,
        correlation_id="corr",
        created_at=now,
        next_attempt_at=now,
        pending_shard="PENDING#0",
    )
    idempotency = IdempotencyRecord(
        source=source,
        idempotency_key=key,
        request_hash="hash",
        record_id=record_id,
        status_code=202,
        response_body={"record_id": record_id, "seen_count": 1},
        created_at=now,
        expires_at=int((now + timedelta(hours=1)).timestamp()),
    )
    return record, event, idempotency


class TestTransacao:
    def test_grava_as_tres_entidades_atomicamente(self, repository: DynamoRecordRepository) -> None:
        record, event, idem = build_trio()
        repository.commit_ingestion(record, event, idem)

        assert repository.get_record(record.record_id) is not None
        assert repository.get_outbox_event(event.event_id) is not None
        assert repository.find_idempotency("it", "k1") is not None

    def test_chave_de_idempotencia_repetida_e_conflito(
        self, repository: DynamoRecordRepository
    ) -> None:
        record, event, idem = build_trio()
        repository.commit_ingestion(record, event, idem)

        outro_record, outro_event, _ = build_trio(phone="222")
        with pytest.raises(CommitConflictError):
            repository.commit_ingestion(outro_record, outro_event, idem)

    def test_conflito_nao_deixa_escrita_parcial(self, repository: DynamoRecordRepository) -> None:
        """A garantia da transacao: ou as tres escritas acontecem, ou nenhuma."""
        record, event, idem = build_trio()
        repository.commit_ingestion(record, event, idem)

        outro_record, outro_event, _ = build_trio(phone="222")
        with pytest.raises(CommitConflictError):
            repository.commit_ingestion(outro_record, outro_event, idem)

        assert repository.get_record(outro_record.record_id) is None
        assert repository.get_outbox_event(outro_event.event_id) is None


class TestConsultas:
    def test_busca_por_fingerprint(self, repository: DynamoRecordRepository) -> None:
        record, event, idem = build_trio()
        repository.commit_ingestion(record, event, idem)

        achado = repository.find_by_fingerprint(record.natural_key, record.record_fingerprint)
        assert achado is not None
        assert achado.record_id == record.record_id

    def test_fingerprint_diferente_nao_colide(self, repository: DynamoRecordRepository) -> None:
        """Mesma chave natural, conteudo diferente: sao observacoes distintas."""
        a, ea, ia = build_trio(phone="111", key="ka")
        b, eb, ib = build_trio(phone="222", key="kb")
        repository.commit_ingestion(a, ea, ia)
        repository.commit_ingestion(b, eb, ib)

        assert a.natural_key == b.natural_key
        assert (
            repository.find_by_fingerprint(a.natural_key, a.record_fingerprint).record_id
            == a.record_id
        )
        assert (
            repository.find_by_fingerprint(b.natural_key, b.record_fingerprint).record_id
            == b.record_id
        )

    def test_inexistente_devolve_none(self, repository: DynamoRecordRepository) -> None:
        assert repository.get_record("NAO-EXISTE") is None
        assert repository.find_idempotency("x", "y") is None
        assert repository.find_by_fingerprint("nk", "fp") is None

    def test_listagem_mais_recentes_primeiro(self, repository: DynamoRecordRepository) -> None:
        ids = []
        for i in range(5):
            record, event, idem = build_trio(phone=f"{i}", key=f"k{i}")
            repository.commit_ingestion(record, event, idem)
            ids.append(record.record_id)

        pagina = repository.list_records(RecordType.PERSON, limit=10)
        assert [r.record_id for r in pagina.items] == sorted(ids, reverse=True)

    def test_paginacao_percorre_tudo_sem_repetir(self, repository: DynamoRecordRepository) -> None:
        for i in range(7):
            record, event, idem = build_trio(phone=f"{i}", key=f"k{i}")
            repository.commit_ingestion(record, event, idem)

        vistos: list[str] = []
        cursor = None
        for _ in range(10):
            pagina = repository.list_records(RecordType.PERSON, limit=3, cursor=cursor)
            vistos.extend(r.record_id for r in pagina.items)
            cursor = pagina.next_cursor
            if cursor is None:
                break

        assert len(vistos) == 7
        assert len(set(vistos)) == 7

    def test_cursor_invalido_e_recusado(self, repository: DynamoRecordRepository) -> None:
        with pytest.raises(InvalidPaginationCursorError):
            repository.list_records(RecordType.PERSON, limit=5, cursor="nao-e-base64-valido!!")


class TestDuplicata:
    def test_incrementa_seen_count(self, repository: DynamoRecordRepository) -> None:
        record, event, idem = build_trio()
        repository.commit_ingestion(record, event, idem)

        _, _, segunda = build_trio(key="k2")
        repository.register_duplicate(record.record_id, segunda)

        assert repository.get_record(record.record_id).seen_count == 2

    def test_chave_repetida_na_duplicata_e_conflito(
        self, repository: DynamoRecordRepository
    ) -> None:
        record, event, idem = build_trio()
        repository.commit_ingestion(record, event, idem)
        with pytest.raises(CommitConflictError):
            repository.register_duplicate(record.record_id, idem)


class TestOutboxIndiceEsparso:
    def test_evento_pendente_aparece_no_indice(self, repository: DynamoRecordRepository) -> None:
        record, event, idem = build_trio()
        repository.commit_ingestion(record, event, idem)

        pendentes = repository.list_pending_outbox(
            "PENDING#0", limit=10, now=utcnow() + timedelta(seconds=1)
        )
        assert event.event_id in pendentes

    def test_despacho_remove_do_indice(self, repository: DynamoRecordRepository) -> None:
        """A propriedade central do ADR-003: REMOVE tira o item do indice esparso."""
        record, event, idem = build_trio()
        repository.commit_ingestion(record, event, idem)
        assert repository.count_pending_outbox() == 1

        repository.mark_outbox_dispatched(event.event_id)

        assert repository.count_pending_outbox() == 0
        assert (
            repository.list_pending_outbox(
                "PENDING#0", limit=10, now=utcnow() + timedelta(seconds=1)
            )
            == []
        )
        # O item continua na tabela base — apenas saiu do indice.
        persistido = repository.get_outbox_event(event.event_id)
        assert persistido is not None
        assert persistido.status == OutboxStatus.DISPATCHED

    def test_nao_entrega_evento_agendado_para_o_futuro(
        self, repository: DynamoRecordRepository
    ) -> None:
        record, event, idem = build_trio()
        futuro = utcnow() + timedelta(hours=1)
        from dataclasses import replace

        repository.commit_ingestion(record, replace(event, next_attempt_at=futuro), idem)
        assert repository.list_pending_outbox("PENDING#0", limit=10, now=utcnow()) == []

    def test_backoff_exponencial(
        self, repository: DynamoRecordRepository, settings: Settings
    ) -> None:
        record, event, idem = build_trio()
        repository.commit_ingestion(record, event, idem)

        now = utcnow()
        primeira = repository.reschedule_outbox(event.event_id, error="falha 1", now=now)
        assert primeira.attempts == 1
        assert primeira.next_attempt_at > now
        assert primeira.pending_shard == "PENDING#0"

        intervalo_1 = primeira.next_attempt_at - now
        segunda = repository.reschedule_outbox(event.event_id, error="falha 2", now=now)
        intervalo_2 = segunda.next_attempt_at - now
        assert intervalo_2 > intervalo_1, "o intervalo deve crescer a cada tentativa"

    def test_esgotadas_as_tentativas_sai_do_indice(
        self, repository: DynamoRecordRepository, settings: Settings
    ) -> None:
        """Evento esgotado nao pode bloquear os demais — ADR-003."""
        record, event, idem = build_trio()
        repository.commit_ingestion(record, event, idem)

        final = None
        for i in range(settings.outbox_max_attempts):
            final = repository.reschedule_outbox(event.event_id, error=f"falha {i}", now=utcnow())

        assert final is not None
        assert final.status == OutboxStatus.FAILED
        assert repository.count_pending_outbox() == 0
        assert repository.get_outbox_event(event.event_id).status == OutboxStatus.FAILED

    def test_erro_longo_e_truncado(self, repository: DynamoRecordRepository) -> None:
        record, event, idem = build_trio()
        repository.commit_ingestion(record, event, idem)
        repository.reschedule_outbox(event.event_id, error="x" * 5_000, now=utcnow())
        assert len(repository.get_outbox_event(event.event_id).last_error) <= 512


class TestSaude:
    def test_ping_ok(self, repository: DynamoRecordRepository) -> None:
        assert repository.ping() is True
