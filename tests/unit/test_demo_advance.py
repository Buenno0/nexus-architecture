"""Passo de processamento da demonstracao publica — ``POST /v1/demo/advance``.

A rota existe porque **nada no Nexus processa sozinho** (ADR-003). Na demonstracao
publica as rotas de ``/v1/ops/*`` estao fechadas, e sem um gatilho o registro do
visitante parava em ``accepted`` ate a rede de seguranca do EventBridge rodar, 15
minutos depois.

O que esta sendo testado aqui nao e "o worker funciona" — disso cuidam os testes do
worker, com a fila real. E que **os tetos sao do servidor** e que o passo nao abre
nenhuma porta nova: ele move o que ja existe, nao cria nada e nao gasta a cota de
semeadura.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexus.ingestion.api import (
    DEMO_ADVANCE_MAX_BATCHES,
    DEMO_ADVANCE_MAX_MESSAGES,
    app,
)
from nexus.persistence import get_repository
from nexus.queue import get_queue_client
from nexus.queue.sqlite import SqliteQueue
from nexus.shared.config import Settings, get_settings
from tests.fakes import FakeRepository


def montar(
    repositorio: FakeRepository, fila: SqliteQueue, configuracao: Settings
) -> TestClient:
    app.dependency_overrides[get_repository] = lambda: repositorio
    app.dependency_overrides[get_queue_client] = lambda: fila
    app.dependency_overrides[get_settings] = lambda: configuracao
    return TestClient(app, raise_server_exceptions=False)


def configurar(tmp_path: Path, *, demo: bool) -> Settings:
    return Settings(
        env="local",
        queue_path=str(tmp_path / "fila.db"),
        demo_mode=demo,
        # Folgados de proposito: um dos testes semeia acima do teto de um passo para
        # provar que o que nao coube continua na fila.
        demo_max_per_call=500,
        demo_max_total=2000,
    )


@pytest.fixture
def repositorio() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def fila(tmp_path: Path) -> Iterator[SqliteQueue]:
    motor = SqliteQueue(settings=configurar(tmp_path, demo=True))
    try:
        yield motor
    finally:
        motor.close()


@pytest.fixture
def demo(
    repositorio: FakeRepository, fila: SqliteQueue, tmp_path: Path
) -> Iterator[TestClient]:
    try:
        yield montar(repositorio, fila, configurar(tmp_path, demo=True))
    finally:
        app.dependency_overrides.clear()


class TestModoDesligado:
    def test_rota_nao_existe_fora_do_modo_demo(
        self, repositorio: FakeRepository, fila: SqliteQueue, tmp_path: Path
    ) -> None:
        """404, nao 403 — mesma regra de ``/v1/demo/seed``.

        Fora da demonstracao o operador tem ``/v1/ops/dispatch`` e ``/v1/ops/process``,
        que fazem o mesmo com limites que ele escolhe. Esta rota nao deve existir la.
        """
        try:
            cliente = montar(repositorio, fila, configurar(tmp_path, demo=False))
            resposta = cliente.post("/v1/demo/advance")
        finally:
            app.dependency_overrides.clear()

        assert resposta.status_code == 404
        assert resposta.json()["code"] == "not_found"


class TestPasso:
    def test_faz_o_trabalho_andar(
        self, demo: TestClient, repositorio: FakeRepository
    ) -> None:
        """Semear deixa o evento pendente; o passo e quem publica e consome."""
        semeado = demo.post("/v1/demo/seed", json={"count": 5}).json()
        assert semeado["accepted"] > 0

        # Antes do passo ha trabalho parado em algum lugar: ou no outbox, porque a
        # publicacao best-effort falhou, ou na fila, esperando consumo.
        pendente_antes = repositorio.count_pending_outbox()
        assert pendente_antes > 0 or len(semeado["record_ids"]) > 0

        corpo = demo.post("/v1/demo/advance").json()

        assert corpo["processed"] > 0, "o passo precisa consumir o que foi semeado"
        assert corpo["outbox_pending"] == 0
        assert corpo["duration_ms"] >= 0

    def test_consome_no_maximo_o_teto_do_servidor(self, demo: TestClient) -> None:
        """O visitante escolhe QUANDO, nunca QUANTO.

        A rota nao tem corpo de pedido, entao nao ha como negociar o teto. O passo
        consome em rodadas, mas o produto rodadas x mensagens continua sendo do
        servidor: semeando mais do que cabe num passo, sobra para o proximo.
        """
        teto = DEMO_ADVANCE_MAX_BATCHES * DEMO_ADVANCE_MAX_MESSAGES
        # Bem acima do teto: parte do lote vira duplicata exata, que nao enfileira, e
        # uma margem pequena deixaria o teste depender do sorteio do gerador.
        demo.post("/v1/demo/seed", json={"count": teto * 2})

        corpo = demo.post("/v1/demo/advance").json()

        assert corpo["received"] <= teto
        assert corpo["batches"] <= DEMO_ADVANCE_MAX_BATCHES
        assert corpo["queue_pending"] > 0, "o que nao coube precisa continuar na fila"

    def test_corpo_enviado_pelo_cliente_e_ignorado(self, demo: TestClient) -> None:
        """Mandar um teto maior no corpo nao aumenta teto nenhum."""
        demo.post(
            "/v1/demo/seed",
            json={"count": DEMO_ADVANCE_MAX_BATCHES * DEMO_ADVANCE_MAX_MESSAGES + 20},
        )

        resposta = demo.post("/v1/demo/advance", json={"max_messages": 500})

        assert resposta.status_code == 200
        teto = DEMO_ADVANCE_MAX_BATCHES * DEMO_ADVANCE_MAX_MESSAGES
        assert resposta.json()["received"] <= teto

    def test_nao_gasta_a_cota_de_semeadura(self, demo: TestClient) -> None:
        """O passo move o que existe; nao cria registro, entao nao reserva cota.

        Se gastasse, pedir o processamento duas vezes esgotaria a demonstracao sem
        nenhum registro novo ter sido criado.
        """
        antes = demo.post("/v1/demo/seed", json={"count": 3}).json()["quota_used"]

        demo.post("/v1/demo/advance")
        demo.post("/v1/demo/advance")

        depois = demo.post("/v1/demo/seed", json={"count": 3}).json()["quota_used"]
        assert depois == antes + 3

    def test_fila_vazia_nao_quebra(self, demo: TestClient) -> None:
        """Apertar sem nada para fazer responde zero, nao erro."""
        resposta = demo.post("/v1/demo/advance")

        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["received"] == 0
        assert corpo["processed"] == 0
        assert corpo["dispatched"] == 0
        # Fila vazia encerra na primeira rodada: nao fica girando para receber zero.
        assert corpo["batches"] == 1
