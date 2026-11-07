"""Configuracao da plataforma.

Toda configuracao vem de variaveis de ambiente com prefixo ``NEXUS_``. Nenhum valor
operacional e embutido no codigo: trocar de ambiente nao deve exigir alteracao de fonte.

``NEXUS_ENV`` e o unico ponto onde o ambiente e decidido. As fabricas de repositorio e
de fila consultam esse valor; nenhum outro modulo deve ramificar por ambiente.
"""

from __future__ import annotations

import socket
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "aws"]
QueueBackend = Literal["none", "sqlite", "sqs"]


class Settings(BaseSettings):
    """Configuracao carregada do ambiente."""

    model_config = SettingsConfigDict(
        env_prefix="NEXUS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    env: Environment = "local"
    service_name: str = "nexus-ingestion"
    log_level: str = "INFO"

    # Persistencia
    dynamo_table: str = "nexus-records"
    dynamo_endpoint: str | None = Field(
        default="http://localhost:8000",
        description="Endpoint do DynamoDB Local. Deve ser None no ambiente AWS.",
    )
    aws_region: str = "us-east-1"

    # Idempotencia — ADR-002
    idempotency_ttl_seconds: int = Field(default=172_800, ge=60)

    # Outbox — ADR-003
    outbox_shards: int = Field(default=4, ge=1, le=64)
    outbox_max_attempts: int = Field(default=5, ge=1, le=20)
    outbox_backoff_base_seconds: float = Field(default=2.0, gt=0)
    outbox_dispatch_batch_size: int = Field(default=25, ge=1, le=100)

    # Fila — ADR-004
    queue_backend: QueueBackend = "sqlite"
    queue_path: str = "./data/nexus-queue.db"
    queue_visibility_timeout_seconds: float = Field(default=30.0, gt=0)
    queue_max_receive: int = Field(default=3, ge=1, le=20)
    queue_retry_backoff_base_seconds: float = Field(default=2.0, gt=0)
    queue_busy_timeout_seconds: float = Field(default=5.0, gt=0)
    #: URLs das filas SQS. Obrigatorias quando queue_backend == "sqs".
    sqs_queue_url: str | None = None
    sqs_dlq_url: str | None = None

    # Worker
    worker_batch_size: int = Field(default=10, ge=1, le=100)
    worker_id: str = Field(default_factory=lambda: f"worker-{socket.gethostname()}")
    failure_injection_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Fracao de processamentos que falham deliberadamente. Existe para exercitar "
            "retentativa e DLQ sem adulterar os dados de entrada."
        ),
    )

    # Entity Resolution — Fase 5
    resolution_match_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    resolution_possible_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    resolution_min_compared_fields: int = Field(default=2, ge=1, le=10)
    resolution_max_candidates: int = Field(default=200, ge=1, le=5_000)
    resolution_max_cluster_size: int = Field(default=50, ge=2, le=10_000)
    resolution_review_shards: int = Field(default=2, ge=1, le=64)
    #: Campos cuja correspondencia exata dispensa a guarda de campos minimos.
    resolution_strong_fields: tuple[str, ...] = ("document",)
    resolution_weights: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "person": {
                "document": 0.45,
                "email": 0.25,
                "full_name": 0.20,
                "phone": 0.10,
            },
            "organization": {
                "document": 0.45,
                "legal_name": 0.25,
                "email": 0.20,
                "phone": 0.10,
            },
        }
    )

    # Limites de seguranca e custo
    max_batch_records: int = Field(default=10_000, ge=1, le=100_000)
    max_field_length: int = Field(default=512, ge=1)
    max_page_size: int = Field(default=100, ge=1, le=1_000)

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"log_level invalido: {value!r}. Esperado um de {sorted(allowed)}")
        return upper

    @property
    def is_aws(self) -> bool:
        return self.env == "aws"

    @property
    def queue_enabled(self) -> bool:
        return self.queue_backend != "none"

    @model_validator(mode="after")
    def _sqs_requires_urls(self) -> Settings:
        """Falha ao subir, nao na primeira mensagem.

        Sem a URL, o adaptador SQS so quebraria quando alguem tentasse publicar — bem
        depois do deploy, provavelmente em producao.
        """
        if self.queue_backend == "sqs" and not self.sqs_queue_url:
            raise ValueError("queue_backend='sqs' exige NEXUS_SQS_QUEUE_URL")
        return self

    @model_validator(mode="after")
    def _coherent_thresholds(self) -> Settings:
        """O limiar de correspondencia precisa ser maior que o de possivel.

        Invertidos, toda correspondencia provavel viraria certa — a faixa intermediaria
        que impede fusao automatica em duvida deixaria de existir (ADR-002).
        """
        if self.resolution_possible_threshold > self.resolution_match_threshold:
            raise ValueError(
                "resolution_possible_threshold nao pode ser maior que resolution_match_threshold"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Devolve a configuracao do processo.

    Em cache: a configuracao e imutavel durante a vida do processo. Testes que precisem
    de outra configuracao devem chamar ``get_settings.cache_clear()``.
    """
    return Settings()
