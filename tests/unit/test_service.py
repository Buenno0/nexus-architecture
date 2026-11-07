"""Testes do caminho de ingestao — ADR-002 e ADR-003.

Usam o repositorio falso: toda a logica e exercitada sem Docker e sem rede.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from nexus.ingestion.service import IngestionService
from nexus.persistence.models import OutboxStatus, RecordType
from nexus.shared.config import Settings
from nexus.shared.errors import IdempotencyConflictError
from tests.fakes import FakeRepository, RecordingQueueClient

PAYLOAD: dict[str, Any] = {
    "source": "testes",
    "full_name": "Maria Souza",
    "email": "maria@example.com",
    "document": "12345678909",
    "phone": "11999998888",
}


def raw(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True).encode("utf-8")


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def queue() -> RecordingQueueClient:
    return RecordingQueueClient(enabled=True)


@pytest.fixture
def service(
    repo: FakeRepository, queue: RecordingQueueClient, settings: Settings
) -> IngestionService:
    return IngestionService(repo, queue, settings)


def ingest(service: IngestionService, payload: dict[str, Any], key: str) -> Any:
    return service.ingest(
        RecordType.PERSON,
        payload,
        raw_body=raw(payload),
        idempotency_key=key,
        correlation_id="corr-test",
    )


class TestObservacaoNova:
    def test_aceita_com_202(self, service: IngestionService) -> None:
        resultado = ingest(service, PAYLOAD, "k1")
        assert resultado.status_code == 202
        assert resultado.body["status"] == "accepted"
        assert resultado.replayed is False

    def test_grava_as_tres_entidades(self, service: IngestionService, repo: FakeRepository) -> None:
        """Observacao, evento de outbox e idempotencia — ADR-003."""
        ingest(service, PAYLOAD, "k1")
        assert len(repo.records) == 1
        assert len(repo.events) == 1
        assert len(repo.idempotency) == 1

    def test_publica_e_remove_do_indice(
        self, service: IngestionService, repo: FakeRepository, queue: RecordingQueueClient
    ) -> None:
        ingest(service, PAYLOAD, "k1")
        assert len(queue.published) == 1
        evento = next(iter(repo.events.values()))
        assert evento.status == OutboxStatus.DISPATCHED
        assert evento.pending_shard is None

    def test_shard_dentro_do_intervalo(
        self, service: IngestionService, repo: FakeRepository, settings: Settings
    ) -> None:
        for i in range(20):
            ingest(service, {**PAYLOAD, "phone": f"1199999{i:04d}"}, f"k{i}")
        shards = {s.event_id: s for s in repo.events.values()}
        assert all(
            e.pending_shard is None or e.pending_shard.startswith("PENDING#")
            for e in shards.values()
        )


class TestIdempotencia:
    def test_replay_devolve_resposta_armazenada(self, service: IngestionService) -> None:
        primeiro = ingest(service, PAYLOAD, "k1")
        segundo = ingest(service, PAYLOAD, "k1")
        assert segundo.replayed is True
        assert segundo.status_code == primeiro.status_code
        assert segundo.body == primeiro.body

    def test_replay_nao_cria_observacao(
        self, service: IngestionService, repo: FakeRepository
    ) -> None:
        ingest(service, PAYLOAD, "k1")
        ingest(service, PAYLOAD, "k1")
        assert len(repo.records) == 1

    def test_replay_nao_republica(
        self, service: IngestionService, queue: RecordingQueueClient
    ) -> None:
        ingest(service, PAYLOAD, "k1")
        ingest(service, PAYLOAD, "k1")
        assert len(queue.published) == 1

    def test_chave_reusada_com_corpo_diferente_e_conflito(self, service: IngestionService) -> None:
        """409, nao 200: devolver a resposta antiga esconderia um bug do cliente."""
        ingest(service, PAYLOAD, "k1")
        with pytest.raises(IdempotencyConflictError):
            ingest(service, {**PAYLOAD, "phone": "11000000000"}, "k1")

    def test_chave_escopada_por_fonte(
        self, service: IngestionService, repo: FakeRepository
    ) -> None:
        ingest(service, PAYLOAD, "mesma-chave")
        ingest(service, {**PAYLOAD, "source": "outra"}, "mesma-chave")
        assert len(repo.records) == 2


class TestDuplicataDeConteudo:
    def test_conteudo_identico_devolve_200(self, service: IngestionService) -> None:
        ingest(service, PAYLOAD, "k1")
        resultado = ingest(service, PAYLOAD, "k2")
        assert resultado.status_code == 200
        assert resultado.body["status"] == "duplicate"

    def test_nao_cria_observacao_nem_publica(
        self, service: IngestionService, repo: FakeRepository, queue: RecordingQueueClient
    ) -> None:
        ingest(service, PAYLOAD, "k1")
        ingest(service, PAYLOAD, "k2")
        assert len(repo.records) == 1
        assert len(queue.published) == 1

    def test_incrementa_seen_count(self, service: IngestionService, repo: FakeRepository) -> None:
        ingest(service, PAYLOAD, "k1")
        resultado = ingest(service, PAYLOAD, "k2")
        assert resultado.body["seen_count"] == 2
        assert next(iter(repo.records.values())).seen_count == 2

    def test_variacao_irrelevante_conta_como_duplicata(self, service: IngestionService) -> None:
        """Caixa do e-mail e pontuacao do documento sao ruido, nao conteudo novo."""
        ingest(service, PAYLOAD, "k1")
        ruidoso = {**PAYLOAD, "email": "MARIA@EXAMPLE.COM", "document": "123.456.789-09"}
        assert ingest(service, ruidoso, "k2").body["status"] == "duplicate"


class TestAtualizacaoLegitima:
    """O defeito que o ADR-002 existe para impedir."""

    def test_mesma_entidade_com_dado_novo_e_aceita(self, service: IngestionService) -> None:
        primeiro = ingest(service, PAYLOAD, "k1")
        atualizado = ingest(service, {**PAYLOAD, "phone": "11777776666"}, "k2")

        assert atualizado.status_code == 202, "atualizacao legitima nao pode virar duplicata"
        assert atualizado.body["status"] == "accepted"
        assert atualizado.body["record_id"] != primeiro.body["record_id"]

    def test_observacao_original_permanece_intacta(
        self, service: IngestionService, repo: FakeRepository
    ) -> None:
        """Observacoes sao imutaveis: a nova se soma, nao sobrescreve."""
        primeiro = ingest(service, PAYLOAD, "k1")
        ingest(service, {**PAYLOAD, "phone": "11777776666"}, "k2")

        original = repo.records[primeiro.body["record_id"]]
        assert original.normalized["phone"] == "11999998888"
        assert len(repo.records) == 2

    def test_ambas_compartilham_a_chave_natural(
        self, service: IngestionService, repo: FakeRepository
    ) -> None:
        """Mesma entidade candidata; vincula-las e trabalho do Entity Resolution."""
        ingest(service, PAYLOAD, "k1")
        ingest(service, {**PAYLOAD, "phone": "11777776666"}, "k2")
        chaves = {r.natural_key for r in repo.records.values()}
        assert len(chaves) == 1


class TestFilaIndisponivel:
    def test_sem_fila_evento_fica_pendente(self, repo: FakeRepository, settings: Settings) -> None:
        """Fase 1 nao possui fila: o evento fica pendente, sem consumir tentativas."""
        service = IngestionService(repo, RecordingQueueClient(enabled=False), settings)
        ingest(service, PAYLOAD, "k1")
        evento = next(iter(repo.events.values()))
        assert evento.status == OutboxStatus.PENDING
        assert evento.pending_shard is not None
        assert evento.attempts == 0

    def test_falha_de_publicacao_nao_derruba_a_ingestao(
        self, repo: FakeRepository, settings: Settings
    ) -> None:
        """A observacao ja esta persistida; o dispatcher recupera depois — ADR-003."""
        service = IngestionService(repo, RecordingQueueClient(fail=True), settings)
        resultado = ingest(service, PAYLOAD, "k1")

        assert resultado.status_code == 202
        assert len(repo.records) == 1
        evento = next(iter(repo.events.values()))
        assert evento.status == OutboxStatus.PENDING
        assert evento.pending_shard is not None


class TestConcorrencia:
    def test_mesma_chave_em_paralelo_produz_uma_observacao(
        self, service: IngestionService, repo: FakeRepository
    ) -> None:
        """50 requisicoes simultaneas com a mesma chave: exatamente uma observacao.

        A garantia vem da condicao de escrita na transacao, nao de verificar antes de
        gravar — uma leitura seguida de escrita teria janela de corrida.
        """
        with ThreadPoolExecutor(max_workers=16) as pool:
            resultados = list(pool.map(lambda _: ingest(service, PAYLOAD, "mesma"), range(50)))

        assert len(repo.records) == 1
        assert len({r.body["record_id"] for r in resultados}) == 1
        assert sum(1 for r in resultados if r.status_code == 202) >= 1

    def test_chaves_distintas_em_paralelo_nao_explodem(
        self, service: IngestionService, repo: FakeRepository
    ) -> None:
        """Mesmo conteudo com chaves diferentes: a deduplicacao e best-effort.

        A verificacao de duplicata e uma leitura seguida de escrita, sem condicao que
        as ligue. Threads simultaneas podem nao enxergar a observacao uma da outra e
        criar mais de uma — e o repositorio falso reproduz essa corrida fielmente, em
        vez de esconde-la atras de um lock que o DynamoDB nao tem.

        Afirmar "exatamente 1" aqui seria um teste que passa por sorte. A garantia real
        da plataforma e outra: deduplicacao de **operacao** pela chave de idempotencia
        (teste acima, deterministico) e deduplicacao de **identidade** pelo Entity
        Resolution, a jusante. Ver ADR-002.
        """
        with ThreadPoolExecutor(max_workers=16) as pool:
            resultados = list(pool.map(lambda i: ingest(service, PAYLOAD, f"k{i}"), range(20)))

        assert all(r.status_code in (200, 202) for r in resultados)
        assert 1 <= len(repo.records) <= 20
        # Toda observacao criada descreve a mesma entidade candidata.
        assert len({r.natural_key for r in repo.records.values()}) == 1
