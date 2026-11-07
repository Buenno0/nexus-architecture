"""Cenarios de carga — Fase 7.

Execucao::

    locust -f tests/load/locustfile.py --host http://localhost:8080 \
           --headless -u 50 -r 10 -t 60s

Os tres cenarios tem pesos distintos de proposito: um teste que so envia registros
novos mede apenas o caminho mais barato e esconde o custo de replay e deduplicacao.

Resultados ficam em ``docs/performance/``. Numeros obtidos contra DynamoDB Local
**nao** sao previsao de desempenho na AWS — ver COSTS.md.
"""

from __future__ import annotations

import uuid
from typing import Any

from locust import HttpUser, between, task


def pessoa(sufixo: str) -> dict[str, Any]:
    return {
        "source": "locust",
        "full_name": f"Carga Teste {sufixo}",
        "email": f"carga.{sufixo}@example.com",
        "document": f"{abs(hash(sufixo)) % 10**11:011d}",
        "phone": "11999998888",
    }


class IngestionUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        self.conhecido = pessoa(uuid.uuid4().hex[:8])
        self.chave_fixa = str(uuid.uuid4())
        self.client.post(
            "/v1/records/person",
            json=self.conhecido,
            headers={"Idempotency-Key": self.chave_fixa},
            name="POST /v1/records/person [preparo]",
        )

    @task(6)
    def registro_novo(self) -> None:
        self.client.post(
            "/v1/records/person",
            json=pessoa(uuid.uuid4().hex[:12]),
            headers={"Idempotency-Key": str(uuid.uuid4())},
            name="POST /v1/records/person [novo]",
        )

    @task(2)
    def conteudo_duplicado(self) -> None:
        """Chave nova, conteudo ja observado: exercita a consulta por fingerprint."""
        self.client.post(
            "/v1/records/person",
            json=self.conhecido,
            headers={"Idempotency-Key": str(uuid.uuid4())},
            name="POST /v1/records/person [duplicata]",
        )

    @task(2)
    def replay(self) -> None:
        """Mesma chave: deve sair cedo, sem normalizar nem consultar o indice."""
        self.client.post(
            "/v1/records/person",
            json=self.conhecido,
            headers={"Idempotency-Key": self.chave_fixa},
            name="POST /v1/records/person [replay]",
        )

    @task(1)
    def listagem(self) -> None:
        self.client.get("/v1/records?limit=25", name="GET /v1/records")
