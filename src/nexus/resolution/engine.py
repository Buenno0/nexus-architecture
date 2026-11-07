"""Resolvedor de identidade — o processador da Fase 5.

Substitui o `DefaultProcessor` sem que worker, fila ou persistencia mudem: implementa o
mesmo contrato `RecordProcessor` que a Fase 2 definiu exatamente para isso.

O fluxo por observacao:

1. gerar chaves de bloco;
2. buscar candidatos que compartilhem alguma chave;
3. pontuar cada candidato campo a campo;
4. `MATCH` liga clusters, `POSSIBLE_MATCH` abre revisao, `NO_MATCH` nao faz nada;
5. gravar as chaves de bloco, para que observacoes futuras encontrem esta.

O passo 5 vem por ultimo de proposito: gravar antes faria o registro aparecer entre os
proprios candidatos.
"""

from __future__ import annotations

import hashlib
from typing import Any

from nexus.persistence.models import ReviewItem, StoredRecord
from nexus.persistence.repository import RecordRepository
from nexus.resolution.blocking import blocking_keys
from nexus.resolution.clustering import ClusterAction, ClusterManager
from nexus.resolution.scoring import MatchDecision, MatchScore, score_pair
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings, get_settings
from nexus.shared.logging import get_logger

logger = get_logger(__name__)


def pair_id(record_a: str, record_b: str) -> str:
    """Identificador estavel de um par, independente da ordem.

    O mesmo par precisa produzir sempre o mesmo identificador: e isso que impede que
    cada reprocessamento ressuscite uma revisao ja decidida.
    """
    first, second = sorted((record_a, record_b))
    return hashlib.sha256(f"{first}\x00{second}".encode()).hexdigest()[:32]


class ResolutionProcessor:
    """Resolve identidade comparando a observacao contra seus candidatos."""

    def __init__(self, repository: RecordRepository, settings: Settings | None = None) -> None:
        self._repo = repository
        self._settings = settings or get_settings()
        self._clusters = ClusterManager(repository, self._settings)

    @property
    def version(self) -> str:
        return "resolution-v1"

    def process(self, record: StoredRecord) -> dict[str, Any]:
        keys = blocking_keys(record.record_type.value, record.normalized)
        candidates, truncated = self._repo.find_block_candidates(
            keys,
            limit=self._settings.resolution_max_candidates,
            exclude=record.record_id,
        )

        matches: list[tuple[str, MatchScore]] = []
        possibles: list[tuple[str, MatchScore]] = []

        for candidate_id in candidates:
            other = self._repo.get_record(candidate_id)
            if other is None or other.record_type != record.record_type:
                continue
            result = score_pair(
                record.record_type.value, record.normalized, other.normalized, self._settings
            )
            if result.decision is MatchDecision.MATCH:
                matches.append((candidate_id, result))
            elif result.decision is MatchDecision.POSSIBLE_MATCH:
                possibles.append((candidate_id, result))

        # Da correspondencia mais forte para a mais fraca: o vinculo que primeiro forma
        # o cluster fica sendo o de maior evidencia, o que torna a auditoria mais util.
        matches.sort(key=lambda pair: pair[1].total, reverse=True)

        actions: list[str] = []
        for candidate_id, result in matches:
            outcome = self._clusters.link(
                record.record_id,
                candidate_id,
                record.record_type,
                result.total,
                result.to_evidence(),
            )
            actions.append(outcome.action.value)

        reviews_created = sum(
            1
            for candidate_id, result in possibles
            if self._open_review(record, candidate_id, result)
        )

        # Depois de comparar: agora o registro passa a ser candidato dos proximos.
        self._repo.put_blocking_keys(record.record_id, record.record_type, keys)

        entity_id = self._repo.find_entity_id_for_record(record.record_id)

        self._repo.increment_resolution_stats(
            records_analyzed=1,
            candidates_compared=len(candidates),
            matches=len(matches),
            possible_matches=len(possibles),
            reviews_created=reviews_created,
            entities_created=sum(1 for a in actions if a == ClusterAction.CREATED.value),
            merges=sum(1 for a in actions if a == ClusterAction.MERGED.value),
            refused_too_large=sum(1 for a in actions if a == ClusterAction.REFUSED_TOO_LARGE.value),
        )

        logger.info(
            "record_resolved",
            extra={
                "record_id": record.record_id,
                "blocking_keys": len(keys),
                "candidates": len(candidates),
                "matches": len(matches),
                "possible_matches": len(possibles),
                "entity_id": entity_id,
            },
        )

        return {
            "stage": "entity-resolution",
            "processor_version": self.version,
            "record_type": record.record_type.value,
            "blocking_keys": keys,
            "candidates_compared": len(candidates),
            # Nao e enfeite: sinaliza que o teto cortou candidatos e o resultado pode
            # conter falso negativo. Truncar em silencio esconderia isso.
            "candidates_truncated": truncated,
            "matches": len(matches),
            "possible_matches": len(possibles),
            "reviews_created": reviews_created,
            "cluster_actions": actions,
            "entity_id": entity_id,
            "top_match": self._describe_top(matches),
        }

    # ------------------------------------------------------------------ internos

    def _describe_top(self, matches: list[tuple[str, MatchScore]]) -> dict[str, Any] | None:
        if not matches:
            return None
        candidate_id, result = matches[0]
        return {"record_id": candidate_id, **result.to_evidence()}

    def _open_review(self, record: StoredRecord, candidate_id: str, result: MatchScore) -> bool:
        """Registra o par para revisao humana. ``False`` se ja era conhecido."""
        identifier = pair_id(record.record_id, candidate_id)
        shard = int(identifier[:8], 16) % self._settings.resolution_review_shards
        item = ReviewItem(
            pair_id=identifier,
            record_a=record.record_id,
            record_b=candidate_id,
            record_type=record.record_type,
            score=result.total,
            evidence=result.to_evidence(),
            created_at=utcnow(),
            review_shard=f"REVIEW#{shard}",
        )
        created = self._repo.put_review(item)
        if created:
            logger.info(
                "review_opened",
                extra={
                    "pair_id": identifier,
                    "record_id": record.record_id,
                    "candidate_id": candidate_id,
                    "score": result.total,
                },
            )
        return created
