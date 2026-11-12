"""Rota de semeadura da demonstracao publica.

O que esta sendo testado nao e "o gerador gera": e que os tetos **do servidor** valem.
A credencial de convidado da demonstracao vai embutida no JavaScript publico, entao
qualquer pessoa chama esta rota diretamente, sem passar pela interface. Um limite que
so existe no botao nao limita nada.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from nexus.ingestion.api import app
from nexus.persistence import get_repository
from nexus.queue import get_queue_client
from nexus.shared.config import Settings, get_settings
from tests.fakes import FakeRepository, RecordingQueueClient

PESSOA = {"source": "x", "full_name": "Nome Sintetico"}
CHAVE = {"Idempotency-Key": "k-demo"}


def montar(repositorio: FakeRepository, **ajustes: object) -> TestClient:
    configuracao = Settings(queue_backend="none", **ajustes)  # type: ignore[arg-type]
    app.dependency_overrides[get_repository] = lambda: repositorio
    app.dependency_overrides[get_queue_client] = lambda: RecordingQueueClient()
    app.dependency_overrides[get_settings] = lambda: configuracao
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def repositorio() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def demo(repositorio: FakeRepository) -> Iterator[TestClient]:
    try:
        yield montar(repositorio, demo_mode=True, demo_max_per_call=20, demo_max_total=50)
    finally:
        app.dependency_overrides.clear()


class TestModoDesligado:
    def test_rota_nao_existe_fora_do_modo_demo(self, repositorio: FakeRepository) -> None:
        """404, nao 403: dizer "existe mas voce nao pode" entrega informacao a toa."""
        try:
            cliente = montar(repositorio, demo_mode=False)
            resposta = cliente.post("/v1/demo/seed", json={"count": 5})
        finally:
            app.dependency_overrides.clear()

        assert resposta.status_code == 404
        assert resposta.json()["code"] == "not_found"

    def test_nada_e_gravado(self, repositorio: FakeRepository) -> None:
        try:
            cliente = montar(repositorio, demo_mode=False)
            cliente.post("/v1/demo/seed", json={"count": 5})
        finally:
            app.dependency_overrides.clear()

        assert repositorio.demo_seeded == 0


class TestSemeadura:
    def test_gera_e_persiste(self, demo: TestClient, repositorio: FakeRepository) -> None:
        corpo = demo.post("/v1/demo/seed", json={"count": 10}).json()

        assert corpo["requested"] == 10
        assert corpo["accepted"] + corpo["duplicate"] == 10
        assert corpo["failed"] == 0
        assert corpo["quota_used"] == 10
        assert corpo["quota_total"] == 50

    def test_produz_duplicatas_para_a_resolucao_ter_o_que_mostrar(self, demo: TestClient) -> None:
        """Acervo so de registros distintos nao produz par, fusao nem revisao."""
        corpo = demo.post("/v1/demo/seed", json={"count": 20}).json()
        assert corpo["duplicate"] > 0

    def test_organizacao_tambem(self, demo: TestClient) -> None:
        corpo = demo.post("/v1/demo/seed", json={"count": 5, "record_type": "organization"}).json()
        assert corpo["accepted"] + corpo["duplicate"] == 5

    def test_funciona_sem_corpo(self, demo: TestClient) -> None:
        """O padrao de 100 esta acima do teto deste teste — deve recusar, nao estourar."""
        assert demo.post("/v1/demo/seed").status_code == 429


class TestTetos:
    def test_teto_por_chamada(self, demo: TestClient, repositorio: FakeRepository) -> None:
        resposta = demo.post("/v1/demo/seed", json={"count": 21})

        assert resposta.status_code == 429
        assert resposta.json()["code"] == "demo_quota_exceeded"
        # Recusado antes de reservar: o teto por chamada nao consome cota.
        assert repositorio.demo_seeded == 0

    def test_teto_acumulado(self, demo: TestClient) -> None:
        """O teto por chamada nao limita nada sozinho: basta chamar de novo.

        Teto de 50 com lotes de 20: duas chamadas cabem, a terceira levaria a 60 e e
        recusada **inteira**. O teto nao e aparado para encaixar um lote parcial — uma
        reserva parcial faria o cliente receber menos do que pediu sem dizer por que.
        """
        assert demo.post("/v1/demo/seed", json={"count": 20}).status_code == 200
        assert demo.post("/v1/demo/seed", json={"count": 20}).status_code == 200

        resposta = demo.post("/v1/demo/seed", json={"count": 20})

        assert resposta.status_code == 429
        assert resposta.json()["code"] == "demo_quota_exceeded"

    def test_o_que_cabe_ainda_passa(self, demo: TestClient) -> None:
        """Recusar 20 nao bloqueia a demonstracao: 10 ainda cabem nos 50."""
        demo.post("/v1/demo/seed", json={"count": 20})
        demo.post("/v1/demo/seed", json={"count": 20})

        assert demo.post("/v1/demo/seed", json={"count": 10}).status_code == 200

    def test_cota_e_reservada_antes_de_gerar(
        self, demo: TestClient, repositorio: FakeRepository
    ) -> None:
        """Reservar depois deixaria a escrita acontecer para so entao recusar."""
        demo.post("/v1/demo/seed", json={"count": 20})
        demo.post("/v1/demo/seed", json={"count": 20})
        antes = len(repositorio.records)

        demo.post("/v1/demo/seed", json={"count": 20})

        assert repositorio.demo_seeded == 40
        assert len(repositorio.records) == antes

    def test_teto_do_contrato_independe_da_configuracao(self, demo: TestClient) -> None:
        """1.000 e o teto do schema; acima disso o Pydantic recusa antes da rota."""
        assert demo.post("/v1/demo/seed", json={"count": 100_000}).status_code == 422

    def test_campo_desconhecido_e_recusado(self, demo: TestClient) -> None:
        assert demo.post("/v1/demo/seed", json={"count": 5, "seed": 1}).status_code == 422


class TestConcorrencia:
    def test_chamadas_simultaneas_nao_furam_o_teto(
        self, demo: TestClient, repositorio: FakeRepository
    ) -> None:
        """Numa URL publica, chamadas simultaneas sao o caso normal.

        Ler o total e depois gravar deixaria uma janela em que duas chamadas leem o
        mesmo valor e ambas passam.
        """
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=8) as pool:
            respostas = list(
                pool.map(lambda _: demo.post("/v1/demo/seed", json={"count": 20}), range(8))
            )

        aceitas = sum(1 for r in respostas if r.status_code == 200)
        assert aceitas <= 3
        assert repositorio.demo_seeded <= 50


class TestIngestaoLivreFechada:
    """Em modo demonstracao, a ingestao livre nao existe nem na aplicacao.

    Retirar a rota do API Gateway e a protecao que funciona no dia a dia. Esta aqui e
    a que sobrevive a um erro de configuracao do gateway ou a uma invocacao direta da
    Lambda — uma garantia que depende de uma linha de Terraform estar certa nao e uma
    garantia da aplicacao.
    """

    def test_pessoa_responde_404(self, demo: TestClient) -> None:
        resposta = demo.post("/v1/records/person", json=PESSOA, headers=CHAVE)

        assert resposta.status_code == 404
        assert resposta.json()["code"] == "not_found"

    def test_organizacao_responde_404(self, demo: TestClient) -> None:
        corpo = {"source": "x", "legal_name": "Empresa Sintetica Ltda"}
        assert demo.post("/v1/records/organization", json=corpo, headers=CHAVE).status_code == 404

    def test_nada_e_persistido(self, demo: TestClient, repositorio: FakeRepository) -> None:
        demo.post("/v1/records/person", json=PESSOA, headers=CHAVE)

        assert repositorio.records == {}

    def test_fora_do_modo_demo_continua_aceitando(self, repositorio: FakeRepository) -> None:
        """A rota so some em modo demonstracao: o desenvolvimento normal nao muda."""
        try:
            cliente = montar(repositorio, demo_mode=False)
            resposta = cliente.post("/v1/records/person", json=PESSOA, headers=CHAVE)
        finally:
            app.dependency_overrides.clear()

        assert resposta.status_code == 202
