"""Testes do resolvedor de identidade."""

from __future__ import annotations

from typing import Any

import pytest

from nexus.persistence.models import RecordType, StoredRecord
from nexus.resolution.engine import ResolutionProcessor, pair_id
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings
from nexus.shared.identity import natural_key, new_ulid, record_fingerprint
from tests.fakes import FakeRepository

PESSOA: dict[str, Any] = {
    "document": "12345678909",
    "email": "maria.souza@example.com",
    "full_name": "Maria Souza",
    "phone": "11987654321",
}


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def settings() -> Settings:
    return Settings(env="local", resolution_max_candidates=50, resolution_review_shards=2)


@pytest.fixture
def engine(repo: FakeRepository, settings: Settings) -> ResolutionProcessor:
    return ResolutionProcessor(repo, settings)


def gravar(
    repo: FakeRepository, normalized: dict[str, Any], record_type: RecordType = RecordType.PERSON
) -> StoredRecord:
    record = StoredRecord(
        record_id=new_ulid(),
        record_type=record_type,
        source="testes",
        natural_key=natural_key(record_type.value, normalized),
        record_fingerprint=record_fingerprint(record_type.value, normalized),
        payload=normalized,
        normalized=normalized,
        correlation_id="corr",
        created_at=utcnow(),
    )
    repo.records[record.record_id] = record
    return record


class TestPrimeiraObservacao:
    def test_sem_candidatos(self, engine: ResolutionProcessor, repo: FakeRepository) -> None:
        resumo = engine.process(gravar(repo, PESSOA))
        assert resumo["candidates_compared"] == 0
        assert resumo["matches"] == 0
        assert resumo["entity_id"] is None

    def test_grava_as_chaves_de_bloco(
        self, engine: ResolutionProcessor, repo: FakeRepository
    ) -> None:
        engine.process(gravar(repo, PESSOA))
        assert "doc:12345678909" in repo.blocks
        assert "name:m|souza" in repo.blocks

    def test_nao_e_candidato_de_si_mesmo(
        self, engine: ResolutionProcessor, repo: FakeRepository
    ) -> None:
        """As chaves sao gravadas depois da comparacao, nunca antes."""
        record = gravar(repo, PESSOA)
        assert engine.process(record)["candidates_compared"] == 0

    def test_declara_a_versao(self, engine: ResolutionProcessor) -> None:
        assert engine.version == "resolution-v1"


class TestCorrespondencia:
    def test_variante_do_mesmo_registro_funde(
        self, engine: ResolutionProcessor, repo: FakeRepository
    ) -> None:
        """Mesma pessoa com telefone atualizado: o caso que o ADR-002 preserva."""
        primeiro = gravar(repo, PESSOA)
        engine.process(primeiro)

        segundo = gravar(repo, {**PESSOA, "phone": "11777776666"})
        resumo = engine.process(segundo)

        assert resumo["matches"] == 1
        assert resumo["entity_id"] is not None
        assert repo.find_entity_id_for_record(primeiro.record_id) == resumo["entity_id"]

    def test_pessoa_diferente_nao_funde(
        self, engine: ResolutionProcessor, repo: FakeRepository
    ) -> None:
        engine.process(gravar(repo, PESSOA))
        outra = gravar(
            repo,
            {
                "document": "98765432100",
                "email": "carlos@outro.com",
                "full_name": "Carlos Pereira",
                "phone": "21911112222",
            },
        )
        resumo = engine.process(outra)
        assert resumo["matches"] == 0
        assert resumo["entity_id"] is None

    def test_tipos_diferentes_nunca_sao_comparados(
        self, engine: ResolutionProcessor, repo: FakeRepository
    ) -> None:
        engine.process(gravar(repo, PESSOA))
        org = gravar(
            repo,
            {"document": "12345678909", "legal_name": "Acme", "email": PESSOA["email"]},
            RecordType.ORGANIZATION,
        )
        resumo = engine.process(org)
        assert resumo["matches"] == 0

    def test_evidencia_do_melhor_par(
        self, engine: ResolutionProcessor, repo: FakeRepository
    ) -> None:
        engine.process(gravar(repo, PESSOA))
        resumo = engine.process(gravar(repo, {**PESSOA, "phone": "11777776666"}))

        topo = resumo["top_match"]
        assert topo is not None
        assert topo["decision"] == "MATCH"
        assert any(campo["field"] == "document" for campo in topo["fields"])


class TestRevisao:
    def _par_duvidoso(self, repo: FakeRepository, engine: ResolutionProcessor) -> None:
        engine.process(gravar(repo, PESSOA))
        # Documento com um digito trocado: fica entre os limiares.
        engine.process(gravar(repo, {**PESSOA, "document": "12345678908"}))

    def test_possivel_correspondencia_abre_revisao(
        self, engine: ResolutionProcessor, repo: FakeRepository
    ) -> None:
        self._par_duvidoso(repo, engine)
        pendentes = repo.list_pending_reviews(limit=10)
        assert len(pendentes) == 1
        assert pendentes[0].evidence["decision"] == "POSSIBLE_MATCH"

    def test_possivel_correspondencia_nao_funde(
        self, engine: ResolutionProcessor, repo: FakeRepository
    ) -> None:
        """A regra inegociavel: duvida nunca vira fusao automatica."""
        self._par_duvidoso(repo, engine)
        assert repo.entities == {}

    def test_par_repetido_nao_duplica_revisao(
        self, engine: ResolutionProcessor, repo: FakeRepository
    ) -> None:
        """Reprocessar nao pode ressuscitar uma decisao ja tomada."""
        primeiro = gravar(repo, PESSOA)
        segundo = gravar(repo, {**PESSOA, "document": "12345678908"})
        engine.process(primeiro)
        engine.process(segundo)
        engine.process(segundo)
        assert len(repo.reviews) == 1

    def test_identificador_de_par_independe_da_ordem(self) -> None:
        assert pair_id("a", "b") == pair_id("b", "a")

    def test_identificadores_distintos_para_pares_distintos(self) -> None:
        assert pair_id("a", "b") != pair_id("a", "c")


class TestTetoDeCandidatos:
    def test_sinaliza_truncagem(self, repo: FakeRepository) -> None:
        """Truncar em silencio esconderia falso negativo."""
        apertado = ResolutionProcessor(repo, Settings(env="local", resolution_max_candidates=2))
        for i in range(5):
            apertado.process(
                gravar(repo, {**PESSOA, "phone": f"1198765432{i}", "document": f"1234567890{i}"})
            )

        resumo = apertado.process(gravar(repo, PESSOA))
        assert resumo["candidates_truncated"] is True
        assert resumo["candidates_compared"] <= 2


class TestContadores:
    def test_registra_estatisticas_duraveis(
        self, engine: ResolutionProcessor, repo: FakeRepository
    ) -> None:
        engine.process(gravar(repo, PESSOA))
        engine.process(gravar(repo, {**PESSOA, "phone": "11777776666"}))

        stats = repo.get_resolution_stats()
        assert stats["records_analyzed"] == 2
        assert stats["matches"] == 1
        assert stats["entities_created"] == 1


class TestResumoSerializavel:
    def test_resumo_vai_para_json(self, engine: ResolutionProcessor, repo: FakeRepository) -> None:
        import json

        engine.process(gravar(repo, PESSOA))
        resumo = engine.process(gravar(repo, {**PESSOA, "phone": "11777776666"}))
        json.dumps(resumo)
        assert resumo["stage"] == "entity-resolution"
