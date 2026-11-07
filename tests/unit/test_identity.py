"""Testes das primitivas de identidade — ADR-002."""

from __future__ import annotations

import pytest

from nexus.shared.identity import (
    canonical_json,
    idempotency_scope,
    natural_key,
    new_ulid,
    record_fingerprint,
    request_hash,
)


class TestUlid:
    def test_tamanho_fixo(self) -> None:
        assert len(new_ulid()) == 26

    def test_ordena_por_tempo(self) -> None:
        """Propriedade que justifica o ULID: ordem lexicografica == ordem cronologica."""
        anteriores = [new_ulid(t) for t in (1, 1_000, 1_000_000, 1_700_000_000_000)]
        assert anteriores == sorted(anteriores)

    def test_unico_no_mesmo_milissegundo(self) -> None:
        gerados = {new_ulid(1_700_000_000_000) for _ in range(1_000)}
        assert len(gerados) == 1_000

    def test_prefixo_igual_no_mesmo_milissegundo(self) -> None:
        a, b = new_ulid(1_700_000_000_000), new_ulid(1_700_000_000_000)
        assert a[:10] == b[:10]

    def test_recusa_timestamp_fora_da_faixa(self) -> None:
        with pytest.raises(ValueError, match="fora da faixa"):
            new_ulid(1 << 48)
        with pytest.raises(ValueError, match="fora da faixa"):
            new_ulid(-1)


class TestCanonicalJson:
    def test_ordem_das_chaves_nao_importa(self) -> None:
        assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})

    def test_preserva_nao_ascii(self) -> None:
        assert "José" in canonical_json({"n": "José"})


class TestRecordFingerprint:
    def test_deterministico(self) -> None:
        dados = {"email": "a@b.com", "document": "123"}
        assert record_fingerprint("person", dados) == record_fingerprint("person", dados)

    def test_independe_da_ordem(self) -> None:
        a = record_fingerprint("person", {"email": "a@b.com", "document": "123"})
        b = record_fingerprint("person", {"document": "123", "email": "a@b.com"})
        assert a == b

    def test_tipo_entra_no_hash(self) -> None:
        """Pessoa e organizacao com os mesmos campos nunca devem colidir."""
        dados = {"email": "a@b.com"}
        assert record_fingerprint("person", dados) != record_fingerprint("organization", dados)

    def test_muda_com_o_conteudo(self) -> None:
        a = record_fingerprint("person", {"phone": "111"})
        b = record_fingerprint("person", {"phone": "222"})
        assert a != b


class TestRequestHash:
    def test_sensivel_a_bytes(self) -> None:
        assert request_hash(b'{"a":1}') != request_hash(b'{"a": 1}')

    def test_deterministico(self) -> None:
        assert request_hash(b"abc") == request_hash(b"abc")


class TestNaturalKey:
    def test_prefere_documento(self) -> None:
        chave = natural_key("person", {"document": "123", "email": "a@b.com"})
        assert "document" in chave

    def test_recai_para_email(self) -> None:
        assert "email" in natural_key("person", {"email": "a@b.com"})

    def test_estavel_quando_campo_nao_identificador_muda(self) -> None:
        """A propriedade central do ADR-002.

        Telefone diferente mantem a mesma chave natural (mesma entidade) mas muda o
        fingerprint (conteudo novo). Por isso a atualizacao e aceita como nova
        observacao em vez de descartada como duplicata.
        """
        base = {"document": "123", "phone": "111"}
        atualizado = {"document": "123", "phone": "222"}
        assert natural_key("person", base) == natural_key("person", atualizado)
        assert record_fingerprint("person", base) != record_fingerprint("person", atualizado)

    def test_sem_campo_identificador_usa_fingerprint(self) -> None:
        assert "fingerprint" in natural_key("person", {"nota": "x"})

    def test_tipo_desconhecido_nao_quebra(self) -> None:
        assert natural_key("desconhecido", {"a": "b"}).startswith("desconhecido|")


class TestIdempotencyScope:
    def test_escopado_por_fonte(self) -> None:
        """Duas fontes podem escolher a mesma chave sem interferir uma na outra."""
        assert idempotency_scope("a", "k") != idempotency_scope("b", "k")
