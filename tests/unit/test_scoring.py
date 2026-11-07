"""Testes de pontuacao e decisao — a logica que decide fundir ou nao."""

from __future__ import annotations

from typing import Any

import pytest

from nexus.resolution.scoring import MatchDecision, score_pair
from nexus.shared.config import Settings

PESSOA: dict[str, Any] = {
    "document": "12345678909",
    "email": "maria@example.com",
    "full_name": "Maria Souza",
    "phone": "11987654321",
}


@pytest.fixture
def settings() -> Settings:
    return Settings(env="local")


def decide(a: dict[str, Any], b: dict[str, Any], settings: Settings) -> MatchDecision:
    return score_pair("person", a, b, settings).decision


class TestCorrespondenciaCerta:
    def test_registros_identicos(self, settings: Settings) -> None:
        resultado = score_pair("person", PESSOA, PESSOA, settings)
        assert resultado.total == 1.0
        assert resultado.decision is MatchDecision.MATCH

    def test_campo_nao_identificador_diferente(self, settings: Settings) -> None:
        """Mesma pessoa com telefone atualizado — o caso que o ADR-002 preserva."""
        assert decide(PESSOA, {**PESSOA, "phone": "11777776666"}, settings) is MatchDecision.MATCH

    def test_acento_e_ordem_do_nome(self, settings: Settings) -> None:
        assert (
            decide(PESSOA, {**PESSOA, "full_name": "Souza María"}, settings) is MatchDecision.MATCH
        )


class TestGuardaDeCamposMinimos:
    def test_um_campo_fraco_nao_funde(self, settings: Settings) -> None:
        """Duas pessoas chamadas Maria Souza sao plausiveis; fundir seria temerario."""
        resultado = score_pair(
            "person", {"full_name": "Maria Souza"}, {"full_name": "Maria Souza"}, settings
        )
        assert resultado.total == 1.0
        assert resultado.decision is MatchDecision.POSSIBLE_MATCH
        assert "campo(s) comparado(s)" in resultado.reason

    def test_identificador_forte_dispensa_a_guarda(self, settings: Settings) -> None:
        """Dois CPFs identicos sao a mesma pessoa; exigir um segundo campo perderia o par."""
        resultado = score_pair(
            "person", {"document": "12345678909"}, {"document": "12345678909"}, settings
        )
        assert resultado.decision is MatchDecision.MATCH
        assert resultado.reason == "identificador forte exato"

    def test_identificador_forte_apenas_parecido_nao_dispensa(self, settings: Settings) -> None:
        resultado = score_pair(
            "person", {"document": "12345678909"}, {"document": "12345678908"}, settings
        )
        assert resultado.decision is not MatchDecision.MATCH

    def test_guarda_configuravel(self) -> None:
        aberto = Settings(env="local", resolution_min_compared_fields=1)
        resultado = score_pair(
            "person", {"full_name": "Maria Souza"}, {"full_name": "Maria Souza"}, aberto
        )
        assert resultado.decision is MatchDecision.MATCH


class TestFaixaDeDuvida:
    def test_documento_com_digito_trocado_vai_para_revisao(self, settings: Settings) -> None:
        resultado = score_pair("person", PESSOA, {**PESSOA, "document": "12345678908"}, settings)
        assert resultado.decision is MatchDecision.POSSIBLE_MATCH

    def test_pessoas_distintas(self, settings: Settings) -> None:
        outra = {
            "document": "98765432100",
            "email": "carlos@outro.com",
            "full_name": "Carlos Pereira",
            "phone": "21911112222",
        }
        assert decide(PESSOA, outra, settings) is MatchDecision.NO_MATCH

    def test_limiares_configuraveis(self) -> None:
        estrito = Settings(
            env="local", resolution_match_threshold=0.99, resolution_possible_threshold=0.98
        )
        assert decide(PESSOA, {**PESSOA, "phone": "11777776666"}, estrito) is MatchDecision.NO_MATCH


class TestCamposAusentes:
    def test_sem_campo_em_comum(self, settings: Settings) -> None:
        resultado = score_pair("person", {"document": "123"}, {"phone": "11987654321"}, settings)
        assert resultado.compared_fields == 0
        assert resultado.decision is MatchDecision.NO_MATCH
        assert "nenhum campo comparavel" in resultado.reason

    def test_campo_ausente_nao_penaliza(self, settings: Settings) -> None:
        """Registro esparso nao pode ser punido por nao informar um campo.

        Contar ausencia como divergencia produziria falso negativo: um registro so com
        documento e outro com documento e telefone nao divergem no telefone.
        """
        completo = score_pair("person", PESSOA, PESSOA, settings).total
        esparso = score_pair(
            "person", {"document": PESSOA["document"], "email": PESSOA["email"]}, PESSOA, settings
        ).total
        assert esparso == completo == 1.0

    def test_tipo_desconhecido_nao_quebra(self, settings: Settings) -> None:
        resultado = score_pair("desconhecido", PESSOA, PESSOA, settings)
        assert resultado.decision is MatchDecision.NO_MATCH


class TestAuditoria:
    def test_detalha_campo_a_campo(self, settings: Settings) -> None:
        """Sem o detalhamento, nao da para auditar por que dois registros foram unidos."""
        resultado = score_pair("person", PESSOA, {**PESSOA, "phone": "11777776666"}, settings)
        campos = {item.field: item for item in resultado.fields}

        assert campos["document"].score == 1.0
        assert campos["phone"].score == 0.0
        assert campos["phone"].left == "11987654321"
        assert campos["phone"].right == "11777776666"

    def test_evidencia_serializavel(self, settings: Settings) -> None:
        import json

        evidencia = score_pair("person", PESSOA, PESSOA, settings).to_evidence()
        json.dumps(evidencia)
        assert evidencia["decision"] == "MATCH"
        assert len(evidencia["fields"]) == 4

    def test_contribuicao_por_campo(self, settings: Settings) -> None:
        resultado = score_pair("person", PESSOA, PESSOA, settings)
        assert sum(item.contribution for item in resultado.fields) == pytest.approx(1.0)


class TestOrganizacao:
    def test_usa_os_pesos_da_organizacao(self, settings: Settings) -> None:
        org = {
            "document": "12345678000195",
            "legal_name": "Acme Servicos Ltda",
            "email": "c@acme.com",
        }
        assert score_pair("organization", org, org, settings).decision is MatchDecision.MATCH

    def test_nome_fantasia_diferente_nao_separa(self, settings: Settings) -> None:
        a = {
            "document": "12345678000195",
            "legal_name": "Acme Servicos Ltda",
            "email": "c@acme.com",
        }
        b = {**a, "trade_name": "Acme"}
        assert score_pair("organization", a, b, settings).decision is MatchDecision.MATCH
