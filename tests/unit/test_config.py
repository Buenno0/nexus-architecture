"""Testes de configuracao."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nexus.shared.config import Settings


class TestSettings:
    def test_padroes_locais(self) -> None:
        s = Settings(env="local")
        assert s.is_aws is False
        assert s.dynamo_table

    def test_ambiente_aws(self) -> None:
        assert Settings(env="aws").is_aws is True

    def test_nivel_de_log_normalizado(self) -> None:
        assert Settings(log_level="debug").log_level == "DEBUG"

    def test_nivel_de_log_invalido(self) -> None:
        with pytest.raises(ValidationError, match="log_level invalido"):
            Settings(log_level="VERBOSO")

    def test_ambiente_invalido(self) -> None:
        with pytest.raises(ValidationError):
            Settings(env="producao")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("campo", "valor"),
        [
            ("outbox_shards", 0),
            ("outbox_shards", 999),
            ("outbox_max_attempts", 0),
            ("outbox_backoff_base_seconds", 0),
            ("max_batch_records", 0),
            ("max_page_size", 0),
            ("idempotency_ttl_seconds", 1),
        ],
    )
    def test_limites_sao_validados(self, campo: str, valor: object) -> None:
        """Limites de seguranca e custo nao podem ser desativados por configuracao."""
        with pytest.raises(ValidationError):
            Settings(**{campo: valor})

    def test_imutavel(self) -> None:
        s = Settings()
        with pytest.raises(ValidationError):
            s.env = "aws"  # type: ignore[misc]
