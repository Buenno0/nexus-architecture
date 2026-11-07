"""Testes dos comparadores — funcoes puras, sem I/O."""

from __future__ import annotations

import pytest

from nexus.resolution.comparators import (
    DOCUMENT_FLOOR,
    NAME_FLOOR,
    document_similarity,
    email_similarity,
    exact,
    name_similarity,
    phone_similarity,
    rescale,
)
from nexus.resolution.text import alnum, digits, fold, tokens


class TestFold:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("José da Silva", "jose da silva"),
            ("  MARIA   SOUZA  ", "maria souza"),
            ("Câmara", "camara"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normaliza(self, entrada: str | None, esperado: str) -> None:
        assert fold(entrada) == esperado

    def test_composto_e_decomposto_colidem(self) -> None:
        """Ruido de codificacao nao pode separar o que e igual."""
        assert fold("José") == fold("José")

    def test_tokens(self) -> None:
        assert tokens("Maria  Aparecida-Souza") == ["maria", "aparecida", "souza"]

    def test_alnum_e_digits(self) -> None:
        assert alnum("123.456.789-09") == "12345678909"
        assert alnum("AB-12/cd") == "ab12cd"
        assert digits("+55 (11) 98765-4321") == "5511987654321"


class TestRescale:
    def test_abaixo_do_piso_zera(self) -> None:
        """Similaridade fraca nao pode contribuir pouco: precisa contribuir nada."""
        assert rescale(0.5, 0.7) == 0.0

    def test_no_topo_vale_um(self) -> None:
        assert rescale(1.0, 0.7) == 1.0

    def test_reescala_linearmente(self) -> None:
        assert rescale(0.85, 0.7) == pytest.approx(0.5)


class TestExact:
    def test_ignora_acento_e_caixa(self) -> None:
        assert exact("José", "JOSE") == 1.0

    @pytest.mark.parametrize(("a", "b"), [("a", "b"), (None, "a"), ("a", None), ("", "")])
    def test_divergente_ou_ausente(self, a: str | None, b: str | None) -> None:
        assert exact(a, b) == 0.0


class TestNameSimilarity:
    def test_identico(self) -> None:
        assert name_similarity("Maria Souza", "Maria Souza") == 1.0

    def test_acento_nao_separa(self) -> None:
        assert name_similarity("José da Silva", "Jose da Silva") == 1.0

    def test_ordem_dos_tokens_nao_separa(self) -> None:
        """Fontes diferentes entregam nome em ordens diferentes."""
        assert name_similarity("Maria Souza", "Souza Maria") == 1.0

    def test_erro_de_digitacao_pontua(self) -> None:
        assert 0.0 < name_similarity("Maria Souza", "Maria Suza") < 1.0

    def test_nome_do_meio_omitido_pontua_alto(self) -> None:
        """Variacao mais comum entre fontes, e a que mais custou recall.

        Jaro-Winkler e token_sort pontuam baixo aqui: o nome mais curto simplesmente
        parece diferente. Sem o criterio de subconjunto, um par com documento, e-mail
        e telefone identicos caia para POSSIBLE_MATCH por causa do nome.
        """
        assert name_similarity("Enzo Cunha", "Enzo Gabriel da Cunha") > 0.8
        assert name_similarity("Maria Aparecida Souza", "Maria Souza") > 0.8

    def test_um_token_em_comum_nao_basta(self) -> None:
        """ "Maria" casaria igualmente com "Maria Souza" e "Maria Pereira"."""
        curto = name_similarity("Maria", "Maria Souza")
        completo = name_similarity("Maria Aparecida Souza", "Maria Souza")
        assert curto < completo

    def test_sobrenome_diferente_pontua_menos_que_subconjunto(self) -> None:
        assert name_similarity("Maria Souza", "Maria Pereira") < name_similarity(
            "Maria Aparecida Souza", "Maria Souza"
        )

    def test_subconjunto_nao_vale_identidade(self) -> None:
        """Conter todos os tokens do outro nome e evidencia forte, nao prova."""
        assert name_similarity("Maria Souza", "Maria Aparecida Souza") < 1.0
        assert name_similarity("Maria Souza", "Maria Souza") == 1.0

    def test_nomes_sem_relacao_zeram(self) -> None:
        """Sem o piso, nomes sem relacao pontuariam ~0,4 e inflariam o score."""
        assert name_similarity("Maria Souza", "Carlos Pereira") == 0.0

    @pytest.mark.parametrize(("a", "b"), [(None, "Maria"), ("Maria", None), ("", "Maria")])
    def test_ausente(self, a: str | None, b: str | None) -> None:
        assert name_similarity(a, b) == 0.0

    def test_emoji_nao_quebra(self) -> None:
        assert 0.0 <= name_similarity("Loja 🏪 Central", "Loja Central") <= 1.0


class TestDocumentSimilarity:
    def test_pontuacao_irrelevante(self) -> None:
        assert document_similarity("123.456.789-09", "12345678909") == 1.0

    def test_digito_trocado_pontua_fraco(self) -> None:
        """Positivo fraco de proposito: pode ser erro de digitacao ou outra pessoa."""
        score = document_similarity("12345678909", "12345678908")
        assert 0.0 < score < 0.5

    def test_documentos_distintos_zeram(self) -> None:
        assert document_similarity("12345678909", "98765432100") == 0.0

    def test_piso_alto(self) -> None:
        assert DOCUMENT_FLOOR > NAME_FLOOR

    def test_ausente(self) -> None:
        assert document_similarity(None, "123") == 0.0


class TestEmailSimilarity:
    def test_identico_ignorando_caixa(self) -> None:
        assert email_similarity("Maria@Example.com", "maria@example.com") == 1.0

    def test_mesma_parte_local_dominio_diferente(self) -> None:
        """A mesma pessoa com dois provedores e plausivel."""
        assert email_similarity("maria@x.com", "maria@y.com") == pytest.approx(0.75)

    def test_mesmo_dominio_locais_sem_relacao(self) -> None:
        """Compartilhar dominio e evidencia fraca: todos em example.com compartilham."""
        assert email_similarity("maria@x.com", "carlos@x.com") == pytest.approx(0.25)

    def test_mesmo_dominio_locais_parecidos(self) -> None:
        score = email_similarity("maria.souza@x.com", "maria.souza2@x.com")
        assert score > 0.5

    def test_ausente(self) -> None:
        assert email_similarity(None, "a@b.com") == 0.0


class TestPhoneSimilarity:
    def test_formatacao_e_ddi_irrelevantes(self) -> None:
        assert phone_similarity("+55 (11) 98765-4321", "11987654321") == 1.0

    def test_um_digito_diferente_zera(self) -> None:
        """Telefone parecido nao e evidencia: e outra linha."""
        assert phone_similarity("11987654321", "11987654322") == 0.0

    def test_curto_compara_inteiro(self) -> None:
        assert phone_similarity("1234", "1234") == 1.0
        assert phone_similarity("1234", "1235") == 0.0

    def test_ausente(self) -> None:
        assert phone_similarity(None, "11987654321") == 0.0
