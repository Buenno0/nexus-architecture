"""Pontuacao e decisao de correspondencia.

Produz um score entre 0 e 1 **com o detalhamento campo a campo**. O detalhamento nao e
enfeite: e o que permite auditar por que dois registros foram unidos e ajustar pesos com
evidencia em vez de adivinhacao.

Tres faixas, nunca duas. `POSSIBLE_MATCH` existe exatamente para que a duvida nao vire
fusao automatica — o risco critico do projeto e fundir pessoas distintas.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from nexus.resolution.comparators import COMPARATORS
from nexus.shared.config import Settings, get_settings


class MatchDecision(StrEnum):
    MATCH = "MATCH"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    NO_MATCH = "NO_MATCH"


@dataclass(frozen=True, slots=True)
class FieldScore:
    """Contribuicao de um campo para o score final."""

    field: str
    weight: float
    score: float
    left: str | None = None
    right: str | None = None

    @property
    def contribution(self) -> float:
        return self.weight * self.score


@dataclass(frozen=True, slots=True)
class MatchScore:
    """Resultado completo da comparacao de um par."""

    total: float
    decision: MatchDecision
    compared_fields: int
    reason: str
    fields: list[FieldScore] = field(default_factory=list)

    def to_evidence(self) -> dict[str, Any]:
        """Representacao serializavel para persistencia e auditoria."""
        return {
            "total": round(self.total, 4),
            "decision": self.decision.value,
            "compared_fields": self.compared_fields,
            "reason": self.reason,
            "fields": [
                {
                    "field": item.field,
                    "weight": item.weight,
                    "score": round(item.score, 4),
                    "left": item.left,
                    "right": item.right,
                }
                for item in self.fields
            ],
        }


def score_pair(
    record_type: str,
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    settings: Settings | None = None,
) -> MatchScore:
    """Compara dois registros normalizados e decide a faixa.

    **Apenas campos presentes nos dois registros entram na conta**, numerador e
    denominador. Tratar campo ausente como divergencia penalizaria registros esparsos e
    produziria falso negativo: um registro so com documento e outro com documento e
    telefone nao divergem no telefone — um deles simplesmente nao o informou.
    """
    settings = settings or get_settings()
    weights = settings.resolution_weights.get(record_type, {})

    scored: list[FieldScore] = []
    weighted_sum = 0.0
    weight_total = 0.0

    for name, weight in weights.items():
        comparator = COMPARATORS.get(name)
        if comparator is None:
            continue
        left_value = left.get(name)
        right_value = right.get(name)
        if not left_value or not right_value:
            continue

        value = comparator(str(left_value), str(right_value))
        scored.append(
            FieldScore(
                field=name,
                weight=weight,
                score=value,
                left=str(left_value),
                right=str(right_value),
            )
        )
        weighted_sum += weight * value
        weight_total += weight

    if weight_total == 0.0:
        return MatchScore(
            total=0.0,
            decision=MatchDecision.NO_MATCH,
            compared_fields=0,
            reason="nenhum campo comparavel em comum",
            fields=scored,
        )

    total = weighted_sum / weight_total
    return _decide(total, scored, settings)


def _decide(total: float, scored: list[FieldScore], settings: Settings) -> MatchScore:
    """Aplica limiares e a guarda de campos minimos."""
    compared = len(scored)
    strong_exact = any(
        item.field in settings.resolution_strong_fields and item.score >= 1.0 for item in scored
    )

    if total >= settings.resolution_match_threshold:
        # Guarda de precisao: um unico campo em comum, por melhor que pontue, e base
        # fragil para fundir duas entidades. A excecao sao identificadores fortes, onde
        # correspondencia exata e evidencia suficiente por si.
        if compared >= settings.resolution_min_compared_fields or strong_exact:
            reason = (
                "identificador forte exato"
                if strong_exact and compared < settings.resolution_min_compared_fields
                else "acima do limiar de correspondencia"
            )
            return MatchScore(total, MatchDecision.MATCH, compared, reason, scored)
        return MatchScore(
            total,
            MatchDecision.POSSIBLE_MATCH,
            compared,
            f"acima do limiar, mas apenas {compared} campo(s) comparado(s)",
            scored,
        )

    if total >= settings.resolution_possible_threshold:
        return MatchScore(
            total,
            MatchDecision.POSSIBLE_MATCH,
            compared,
            "entre os limiares; exige revisao",
            scored,
        )

    return MatchScore(total, MatchDecision.NO_MATCH, compared, "abaixo do limiar de duvida", scored)
