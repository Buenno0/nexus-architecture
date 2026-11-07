"""Testes de normalizacao — funcoes puras, sem I/O."""

from __future__ import annotations

import pytest

from nexus.ingestion.normalization import (
    normalize_document,
    normalize_email,
    normalize_name,
    normalize_payload,
    normalize_phone,
    normalize_text,
)


class TestNormalizeText:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("  Maria  ", "Maria"),
            ("Maria   Aparecida    Souza", "Maria Aparecida Souza"),
            ("Maria\tAparecida\nSouza", "Maria Aparecida Souza"),
            ("", None),
            ("   ", None),
            (None, None),
        ],
    )
    def test_colapsa_espacos(self, entrada: str | None, esperado: str | None) -> None:
        assert normalize_text(entrada) == esperado

    def test_unifica_forma_unicode(self) -> None:
        """Composto e decomposto sao ruido de codificacao, nao conteudo diferente."""
        composto = "José"  # e com acento, caractere unico
        decomposto = "José"  # e + acento combinante
        assert composto != decomposto
        assert normalize_text(composto) == normalize_text(decomposto)

    def test_preserva_emoji(self) -> None:
        assert normalize_text("Loja 🏪 Central") == "Loja 🏪 Central"


class TestNormalizeEmail:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("MARIA@EXAMPLE.COM", "maria@example.com"),
            ("  Maria.Souza@Example.Com  ", "maria.souza@example.com"),
            ("", None),
            (None, None),
        ],
    )
    def test_minusculas(self, entrada: str | None, esperado: str | None) -> None:
        assert normalize_email(entrada) == esperado


class TestNormalizeDocument:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("123.456.789-09", "12345678909"),
            ("12.345.678/0001-95", "12345678000195"),
            ("  ab-12/cd  ", "AB12CD"),
            ("...---...", None),
            (None, None),
        ],
    )
    def test_remove_pontuacao(self, entrada: str | None, esperado: str | None) -> None:
        assert normalize_document(entrada) == esperado


class TestNormalizePhone:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("(11) 98765-4321", "11987654321"),
            ("+55 11 98765-4321", "5511987654321"),
            ("abc", None),
            (None, None),
        ],
    )
    def test_somente_digitos(self, entrada: str | None, esperado: str | None) -> None:
        assert normalize_phone(entrada) == esperado


class TestNormalizeName:
    def test_preserva_acento_e_caixa(self) -> None:
        """Decisao de ADR-002: acento e caixa sao sinal, nao ruido.

        Removê-los aqui faria "Jose" e "José" compartilharem fingerprint, e a segunda
        observacao seria descartada como duplicata — uma decisao de identidade tomada
        pela camada com menos informacao para toma-la.
        """
        assert normalize_name("  José   da Silva ") == "José da Silva"
        assert normalize_name("José") != normalize_name("Jose")


class TestNormalizePayload:
    def test_aplica_normalizador_por_campo(self) -> None:
        resultado = normalize_payload(
            {
                "source": " fonte ",
                "full_name": "  Maria   Souza ",
                "email": "MARIA@EXAMPLE.COM",
                "document": "123.456.789-09",
                "phone": "(11) 98765-4321",
            }
        )
        assert resultado == {
            "source": "fonte",
            "full_name": "Maria Souza",
            "email": "maria@example.com",
            "document": "12345678909",
            "phone": "11987654321",
        }

    def test_remove_campos_vazios(self) -> None:
        """Campo ausente e campo vazio devem produzir o mesmo conteudo normalizado.

        Sem isso, ``{"phone": ""}`` e ``{}`` gerariam fingerprints diferentes e a mesma
        informacao viraria duas observacoes.
        """
        assert normalize_payload({"full_name": "A", "phone": "   "}) == {"full_name": "A"}
        assert normalize_payload({"full_name": "A", "phone": None}) == {"full_name": "A"}
        assert normalize_payload({"full_name": "A"}) == {"full_name": "A"}

    def test_preserva_tipos_nao_textuais(self) -> None:
        assert normalize_payload({"birth_date": "1990-01-01", "idade": 30})["idade"] == 30

    def test_texto_muito_longo_nao_quebra(self) -> None:
        grande = "a " * 100_000
        assert normalize_payload({"full_name": grande})["full_name"] == ("a " * 100_000).strip()
