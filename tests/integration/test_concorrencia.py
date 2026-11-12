"""Concorrencia contra a persistencia real — Fase 7.

`tests/unit/test_service.py` ja cobre estas corridas contra o repositorio falso, que
as reproduz fielmente. O que falta, e o que este arquivo faz, e exercita-las contra o
**DynamoDB de verdade**: o falso implementa a condicao de escrita em Python, e um
acordo entre duas implementacoes minhas nao prova nada sobre o banco.

A diferenca nao e teorica. `TransactWriteItems` devolve `TransactionCanceledException`
com motivos por item, e o codigo que traduz isso para `CommitConflictError` so e
exercitado aqui. Um erro nessa traducao transformaria conflito em erro 500 — e o teste
unitario continuaria verde.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexus.ingestion.api import app
from nexus.persistence import get_repository
from nexus.persistence.dynamo import DynamoRecordRepository
from nexus.persistence.models import RecordType
from nexus.queue import get_queue_client
from nexus.queue.sqlite import SqliteQueue
from nexus.queue.worker import Worker
from nexus.shared.config import Settings, get_settings

pytestmark = pytest.mark.integration

PESSOA: dict[str, Any] = {
    "source": "concorrencia",
    "full_name": "Joana Ribeiro Lima",
    "email": "joana.lima@example.com",
    "document": "529.982.247-25",
    "phone": "(11) 97777-6666",
}


@pytest.fixture
def queue(settings: Settings) -> Iterator[SqliteQueue]:
    fila = SqliteQueue(settings=settings)
    try:
        yield fila
    finally:
        fila.close()


@pytest.fixture
def client(
    repository: DynamoRecordRepository, queue: SqliteQueue, settings: Settings
) -> Iterator[TestClient]:
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_queue_client] = lambda: queue
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


def postar(client: TestClient, payload: dict[str, Any], chave: str) -> Any:
    return client.post("/v1/records/person", json=payload, headers={"Idempotency-Key": chave})


class TestIdempotenciaSobConcorrencia:
    def test_mesma_chave_em_paralelo_produz_uma_observacao(
        self, client: TestClient, repository: DynamoRecordRepository
    ) -> None:
        """Trinta requisicoes simultaneas, uma observacao — no banco de verdade.

        A garantia e `attribute_not_exists` dentro da transacao. Quem perde a corrida
        recebe `TransactionCanceledException`, releem o resultado ja estabelecido e
        devolve a mesma resposta. Nenhuma delas pode falhar.
        """
        chave = str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=15) as pool:
            respostas = list(pool.map(lambda _: postar(client, PESSOA, chave), range(30)))

        assert [r.status_code for r in respostas].count(202) >= 1
        assert all(r.status_code in (200, 202) for r in respostas)

        identificadores = {r.json()["record_id"] for r in respostas}
        assert len(identificadores) == 1

        pagina = repository.list_records(RecordType.PERSON, limit=100, cursor=None)
        assert len(pagina.items) == 1

    def test_nenhuma_requisicao_perde_a_corrida_com_erro(self, client: TestClient) -> None:
        """Conflito de escrita nao pode vazar como 500.

        A traducao de `TransactionCanceledException` para conflito resolvido so e
        exercitada contra o banco real. Se ela quebrar, todas as perdedoras viram erro
        interno — e nenhum teste unitario notaria.
        """
        chave = str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=15) as pool:
            respostas = list(pool.map(lambda _: postar(client, PESSOA, chave), range(30)))

        assert [r.status_code for r in respostas if r.status_code >= 500] == []

    def test_chave_reusada_com_corpo_diferente_responde_409(self, client: TestClient) -> None:
        """Mesmo sob concorrencia, reusar a chave com outro corpo e bug do cliente."""
        chave = str(uuid.uuid4())
        assert postar(client, PESSOA, chave).status_code == 202

        outro = {**PESSOA, "full_name": "Outra Pessoa Completamente"}
        with ThreadPoolExecutor(max_workers=8) as pool:
            respostas = list(pool.map(lambda _: postar(client, outro, chave), range(16)))

        assert {r.status_code for r in respostas} == {409}


class TestConsumoSobConcorrencia:
    def test_workers_simultaneos_processam_uma_vez_so(
        self,
        client: TestClient,
        repository: DynamoRecordRepository,
        queue: SqliteQueue,
        settings: Settings,
    ) -> None:
        """Quatro workers na mesma fila: cada registro processado exatamente uma vez.

        Sao duas garantias empilhadas, e so o banco real exercita as duas juntas: a
        fila entrega cada mensagem a um consumidor por vez (visibility timeout,
        ADR-004) e a escrita condicional do resultado resolve a reentrega
        (ADR-005). Um registro processado duas vezes aqui significaria que a segunda
        falhou em silencio.
        """
        for _ in range(12):
            postar(
                client,
                {**PESSOA, "document": f"{uuid.uuid4().int % 10**11:011d}"},
                str(uuid.uuid4()),
            )

        workers = [Worker(repository, queue, settings=settings) for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            relatorios = list(pool.map(lambda w: w.process_once(max_messages=12), workers))

        processados = sum(r.processed for r in relatorios)
        repetidos = sum(r.skipped_duplicate for r in relatorios)
        mortos = sum(r.dead_lettered for r in relatorios)

        assert mortos == 0
        assert processados == 12, f"processados={processados} repetidos={repetidos}"
        assert queue.stats().total == 0
