"""Formacao de clusters a partir de arestas de correspondencia.

Implementa fecho transitivo **auditavel**: se A corresponde a B e B a C, os tres acabam
na mesma entidade, mas cada vinculo guarda o par e a evidencia que o produziram.

## Por que auditavel e nao apenas union-find

Union-find simples e algumas linhas de codigo e resolve a estrutura. O que ele nao
resolve e a pergunta que aparece quando algo da errado: *por que estes dois registros
estao no mesmo cluster?*

Com fecho transitivo, **um unico falso positivo contamina todo o cluster**. Sem rastro,
a unica saida e refazer tudo. Com o par e o score gravados em cada vinculo, da para
localizar a aresta culpada e desfazer apenas ela.

## O teto de tamanho

Um cluster que cresce demais quase sempre indica fusao em cadeia por evidencia fraca,
nao uma entidade realmente observada cinquenta vezes. Ao estourar o teto, o sistema
**recusa a fusao e sinaliza** — prefere um falso negativo visivel a um falso positivo
silencioso.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from nexus.persistence.models import Entity, EntityMember, MergeEvent, RecordType
from nexus.persistence.repository import RecordRepository
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings, get_settings
from nexus.shared.identity import new_ulid
from nexus.shared.logging import get_logger

logger = get_logger(__name__)


class ClusterAction(StrEnum):
    CREATED = "created"
    JOINED = "joined"
    MERGED = "merged"
    ALREADY_LINKED = "already_linked"
    REFUSED_TOO_LARGE = "refused_too_large"


@dataclass(frozen=True, slots=True)
class ClusterOutcome:
    """O que aconteceu ao tentar ligar dois registros."""

    action: ClusterAction
    entity_id: str | None = None
    merged_from: str | None = None
    reason: str | None = None


class ClusterManager:
    """Aplica arestas de correspondencia sobre as entidades existentes."""

    def __init__(self, repository: RecordRepository, settings: Settings | None = None) -> None:
        self._repo = repository
        self._settings = settings or get_settings()

    def link(
        self,
        record_id: str,
        candidate_id: str,
        record_type: RecordType,
        score: float,
        evidence: dict[str, Any],
    ) -> ClusterOutcome:
        """Liga duas observacoes, criando, expandindo ou fundindo entidades."""
        entity_a = self._repo.find_entity_id_for_record(record_id)
        entity_b = self._repo.find_entity_id_for_record(candidate_id)

        if entity_a and entity_b and entity_a == entity_b:
            return ClusterOutcome(ClusterAction.ALREADY_LINKED, entity_id=entity_a)

        if entity_a is None and entity_b is None:
            return self._create(record_id, candidate_id, record_type, score, evidence)

        if entity_a is None and entity_b is not None:
            return self._join(entity_b, record_id, candidate_id, score, evidence)

        if entity_a is not None and entity_b is None:
            return self._join(entity_a, candidate_id, record_id, score, evidence)

        assert entity_a is not None and entity_b is not None
        return self._merge(entity_a, entity_b, record_id, candidate_id, score, evidence)

    # ------------------------------------------------------------------ internos

    def _create(
        self,
        record_id: str,
        candidate_id: str,
        record_type: RecordType,
        score: float,
        evidence: dict[str, Any],
    ) -> ClusterOutcome:
        now = utcnow()
        entity = Entity(
            entity_id=new_ulid(),
            record_type=record_type,
            member_count=2,
            version=0,
            created_at=now,
            updated_at=now,
        )
        members = [
            EntityMember(entity.entity_id, candidate_id, now, score, record_id, evidence),
            EntityMember(entity.entity_id, record_id, now, score, candidate_id, evidence),
        ]
        self._repo.create_entity(entity, members)
        logger.info(
            "entity_created",
            extra={"entity_id": entity.entity_id, "record_id": record_id, "score": score},
        )
        return ClusterOutcome(ClusterAction.CREATED, entity_id=entity.entity_id)

    def _join(
        self,
        entity_id: str,
        joining_id: str,
        anchor_id: str,
        score: float,
        evidence: dict[str, Any],
    ) -> ClusterOutcome:
        entity = self._repo.get_entity(entity_id)
        if entity is None:
            # O vinculo reverso aponta para uma entidade que nao existe mais. Pode
            # acontecer se uma fusao concorrente acabou de remove-la; a retentativa
            # da fila resolve.
            logger.warning("entity_vanished", extra={"entity_id": entity_id})
            return ClusterOutcome(ClusterAction.REFUSED_TOO_LARGE, reason="entidade inexistente")

        if entity.member_count + 1 > self._settings.resolution_max_cluster_size:
            return self._refuse(entity_id, None, entity.member_count + 1)

        member = EntityMember(entity_id, joining_id, utcnow(), score, anchor_id, evidence)
        self._repo.add_member(entity, member)
        logger.info(
            "entity_member_added",
            extra={"entity_id": entity_id, "record_id": joining_id, "score": score},
        )
        return ClusterOutcome(ClusterAction.JOINED, entity_id=entity_id)

    def _merge(
        self,
        entity_a: str,
        entity_b: str,
        record_id: str,
        candidate_id: str,
        score: float,
        evidence: dict[str, Any],
    ) -> ClusterOutcome:
        left = self._repo.get_entity(entity_a)
        right = self._repo.get_entity(entity_b)
        if left is None or right is None:
            logger.warning("entity_vanished_on_merge", extra={"a": entity_a, "b": entity_b})
            return ClusterOutcome(ClusterAction.REFUSED_TOO_LARGE, reason="entidade inexistente")

        combined = left.member_count + right.member_count
        if combined > self._settings.resolution_max_cluster_size:
            return self._refuse(entity_a, entity_b, combined)

        # A menor e movida para a maior: menos itens na transacao e menos reescrita.
        target, source = (left, right) if left.member_count >= right.member_count else (right, left)
        members = self._repo.list_entity_members(source.entity_id)

        event = MergeEvent(
            entity_id=target.entity_id,
            event_id=new_ulid(),
            source_entity_id=source.entity_id,
            record_a=record_id,
            record_b=candidate_id,
            score=score,
            moved_members=len(members),
            created_at=utcnow(),
        )
        self._repo.merge_entities(target, source, members, event)
        logger.info(
            "entities_merged",
            extra={
                "target": target.entity_id,
                "source": source.entity_id,
                "moved": len(members),
                "score": score,
                "evidence_total": evidence.get("total"),
            },
        )
        return ClusterOutcome(
            ClusterAction.MERGED, entity_id=target.entity_id, merged_from=source.entity_id
        )

    def _refuse(self, entity_a: str, entity_b: str | None, size: int) -> ClusterOutcome:
        """Recusa a fusao e sinaliza as entidades envolvidas.

        Um falso negativo visivel e preferivel a um falso positivo silencioso.
        """
        reason = (
            f"cluster alcancaria {size} membros, acima do teto de "
            f"{self._settings.resolution_max_cluster_size}"
        )
        for entity_id in (entity_a, entity_b):
            if entity_id:
                self._repo.flag_entity(entity_id, reason)
        logger.warning(
            "cluster_merge_refused",
            extra={"entity_a": entity_a, "entity_b": entity_b, "size": size},
        )
        return ClusterOutcome(ClusterAction.REFUSED_TOO_LARGE, entity_id=entity_a, reason=reason)
