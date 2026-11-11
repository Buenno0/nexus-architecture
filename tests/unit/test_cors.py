"""Testes de CORS.

O Control Center roda em outra origem, entao o navegador exige CORS. As rotas de
`/v1/ops` disparam trabalho — uma configuracao permissiva aqui deixaria qualquer pagina
aciona-las pelo navegador de quem a visitasse.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from nexus.ingestion.api import app
from nexus.persistence import get_repository
from nexus.queue import get_queue_client
from nexus.shared.config import Settings, get_settings
from tests.fakes import FakeRepository, RecordingQueueClient

ORIGEM = "http://localhost:5173"
ORIGEM_ESTRANHA = "https://site-malicioso.example"


@pytest.fixture
def client() -> Iterator[TestClient]:
    # Fabricas, nao classes. O FastAPI inspeciona a assinatura do que recebe e trata
    # cada parametro como dependencia: passar `Settings` faz ele injetar os campos do
    # modelo como parametros de consulta, e os que usam `default_factory` chegam como
    # o sentinela interno do Pydantic. O erro ficou dormente ate a Fase 7, porque
    # nenhuma rota exercitada aqui dependia de `get_settings` — e /health passou a
    # depender.
    app.dependency_overrides[get_repository] = lambda: FakeRepository()
    app.dependency_overrides[get_queue_client] = lambda: RecordingQueueClient()
    app.dependency_overrides[get_settings] = lambda: Settings()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


class TestConfiguracao:
    def test_padrao_e_o_dev_server(self) -> None:
        assert Settings().cors_allowed_origins == ("http://localhost:5173",)

    def test_aceita_lista_separada_por_virgula(self) -> None:
        """Variavel de ambiente entrega string, nao lista."""
        s = Settings(cors_allowed_origins="https://a.dev, https://b.dev")
        assert s.cors_allowed_origins == ("https://a.dev", "https://b.dev")

    def test_recusa_curinga(self) -> None:
        """Com "*", qualquer pagina da internet chama /v1/ops pelo navegador alheio."""
        with pytest.raises(ValidationError, match="nao aceita"):
            Settings(cors_allowed_origins=["*"])

    def test_recusa_curinga_entre_outras_origens(self) -> None:
        with pytest.raises(ValidationError, match="nao aceita"):
            Settings(cors_allowed_origins="https://a.dev,*")


class TestPreflight:
    def test_origem_permitida(self, client: TestClient) -> None:
        resposta = client.options(
            "/v1/records/person",
            headers={
                "Origin": ORIGEM,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,idempotency-key",
            },
        )
        assert resposta.status_code == 200
        assert resposta.headers["access-control-allow-origin"] == ORIGEM

    def test_origem_desconhecida_nao_recebe_permissao(self, client: TestClient) -> None:
        resposta = client.options(
            "/v1/records/person",
            headers={
                "Origin": ORIGEM_ESTRANHA,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in resposta.headers

    def test_header_de_idempotencia_e_permitido(self, client: TestClient) -> None:
        """Sem ele a ingestao pelo navegador seria impossivel: o header e obrigatorio."""
        resposta = client.options(
            "/v1/records/person",
            headers={
                "Origin": ORIGEM,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "idempotency-key",
            },
        )
        permitidos = resposta.headers.get("access-control-allow-headers", "").lower()
        assert "idempotency-key" in permitidos


class TestRespostaSimples:
    def test_expoe_correlation_id(self, client: TestClient) -> None:
        """Sem expor, o JavaScript nao enxerga o header mesmo ele chegando."""
        resposta = client.get("/health", headers={"Origin": ORIGEM})
        expostos = resposta.headers.get("access-control-expose-headers", "").lower()
        assert "x-correlation-id" in expostos

    def test_expoe_idempotency_replayed(self, client: TestClient) -> None:
        resposta = client.get("/health", headers={"Origin": ORIGEM})
        expostos = resposta.headers.get("access-control-expose-headers", "").lower()
        assert "idempotency-replayed" in expostos

    def test_sem_credenciais(self, client: TestClient) -> None:
        """A autenticacao e por token no header, nao por cookie."""
        resposta = client.get("/health", headers={"Origin": ORIGEM})
        assert "access-control-allow-credentials" not in resposta.headers

    def test_requisicao_sem_origem_continua_funcionando(self, client: TestClient) -> None:
        """curl e os testes nao mandam Origin; nada pode quebrar por isso."""
        assert client.get("/health").status_code in (200, 503)
