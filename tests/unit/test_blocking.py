"""Testes de blocking.

O erro aqui e assimetrico: agrupar demais custa tempo, perder um par e definitivo.
Os testes cobrem principalmente a segunda classe.
"""

from __future__ import annotations

from typing import Any

import pytest

from nexus.resolution.blocking import blocking_keys

PESSOA: dict[str, Any] = {
    "document": "123.456.789-09",
    "email": "Maria.Souza@Example.com",
    "full_name": "Maria Aparecida Souza",
    "phone": "+55 (11) 98765-4321",
}


def chaves(record_type: str, dados: dict[str, Any]) -> set[str]:
    return set(blocking_keys(record_type, dados))


class TestPessoa:
    def test_gera_uma_chave_por_criterio(self) -> None:
        assert chaves("person", PESSOA) == {
            "doc:12345678909",
            "email:maria.souza@example.com",
            "name:m|souza",
            "phone:87654321",
        }

    def test_sem_duplicatas_e_ordem_estavel(self) -> None:
        assert blocking_keys("person", PESSOA) == blocking_keys("person", PESSOA)
        assert len(blocking_keys("person", PESSOA)) == len(set(blocking_keys("person", PESSOA)))

    def test_registro_vazio_nao_gera_chave(self) -> None:
        assert blocking_keys("person", {}) == []

    def test_campos_parciais(self) -> None:
        assert chaves("person", {"document": "123"}) == {"doc:123"}

    def test_tipo_desconhecido(self) -> None:
        assert blocking_keys("desconhecido", PESSOA) == []


class TestColisoesDesejadas:
    """Cada caso aqui e um par verdadeiro que o blocking PRECISA aproximar."""

    def test_acento_nao_separa(self) -> None:
        a = chaves("person", {"full_name": "José da Silva"})
        b = chaves("person", {"full_name": "Jose da Silva"})
        assert a & b

    def test_nome_do_meio_ausente_nao_separa(self) -> None:
        a = chaves("person", {"full_name": "Maria Aparecida Souza"})
        b = chaves("person", {"full_name": "Maria Souza"})
        assert "name:m|souza" in a & b

    def test_abreviacao_nao_separa(self) -> None:
        a = chaves("person", {"full_name": "Maria Aparecida Souza"})
        b = chaves("person", {"full_name": "M. A. Souza"})
        assert a & b

    def test_formatacao_de_documento_nao_separa(self) -> None:
        a = chaves("person", {"document": "123.456.789-09"})
        b = chaves("person", {"document": "12345678909"})
        assert a == b

    def test_ddi_no_telefone_nao_separa(self) -> None:
        a = chaves("person", {"phone": "+55 11 98765-4321"})
        b = chaves("person", {"phone": "(11) 98765-4321"})
        assert a == b

    def test_caixa_do_email_nao_separa(self) -> None:
        a = chaves("person", {"email": "MARIA@EXAMPLE.COM"})
        b = chaves("person", {"email": "maria@example.com"})
        assert a == b

    def test_registro_sem_documento_ainda_encontra_pelo_nome(self) -> None:
        """O caso que justifica chaves independentes em vez de uma chave composta."""
        com_doc = chaves("person", {"document": "12345678909", "full_name": "Maria Souza"})
        sem_doc = chaves("person", {"full_name": "Maria Souza"})
        assert com_doc & sem_doc


class TestSeparacoesDesejadas:
    def test_sobrenomes_diferentes_nao_colidem_por_nome(self) -> None:
        a = chaves("person", {"full_name": "Maria Souza"})
        b = chaves("person", {"full_name": "Maria Pereira"})
        assert not (a & b)

    def test_telefones_diferentes_nao_colidem(self) -> None:
        a = chaves("person", {"phone": "11987654321"})
        b = chaves("person", {"phone": "11911112222"})
        assert not (a & b)

    def test_telefone_curto_nao_gera_chave(self) -> None:
        """Sufixo curto agruparia registros sem relacao."""
        assert blocking_keys("person", {"phone": "1234"}) == []

    def test_nome_curto_demais_nao_gera_chave(self) -> None:
        assert blocking_keys("person", {"full_name": "Al"}) == []


class TestOrganizacao:
    def test_usa_tokens_significativos(self) -> None:
        resultado = chaves("organization", {"legal_name": "Acme Servicos Digitais Ltda"})
        assert "name:acme-digitais" in resultado

    def test_sufixo_societario_nao_separa(self) -> None:
        """Ltda, S.A. e ME sao ruido: a mesma empresa aparece com e sem eles."""
        a = chaves("organization", {"legal_name": "Acme Digitais Ltda"})
        b = chaves("organization", {"legal_name": "ACME Digitais S.A."})
        assert a & b

    def test_nome_so_com_stopwords_nao_gera_chave(self) -> None:
        assert blocking_keys("organization", {"legal_name": "Comercio e Servicos Ltda"}) == []

    def test_pessoa_e_organizacao_usam_construtores_diferentes(self) -> None:
        dados = {"full_name": "Maria Souza", "legal_name": "Acme Digitais"}
        assert "name:m|souza" in chaves("person", dados)
        assert "name:acme-digitais" in chaves("organization", dados)


class TestRobustez:
    @pytest.mark.parametrize(
        "valor", ["", "   ", None, "🏪", "'; DROP TABLE records;--", "a" * 5_000]
    )
    def test_entrada_hostil_nao_quebra(self, valor: Any) -> None:
        resultado = blocking_keys("person", {"full_name": valor, "document": valor})
        assert all(isinstance(chave, str) for chave in resultado)
