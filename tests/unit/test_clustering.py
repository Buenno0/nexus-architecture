"""Testes de clusterizacao.

Fecho transitivo e onde um falso positivo deixa de afetar um par e passa a contaminar
um grupo inteiro. Os testes cobrem principalmente os limites que impedem isso.
"""

from __future__ import annotations

import pytest

from nexus.persistence.models import RecordType
from nexus.resolution.clustering import ClusterAction, ClusterManager
from nexus.shared.config import Settings
from tests.fakes import FakeRepository

EVIDENCIA = {"total": 0.95, "decision": "MATCH"}


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def settings() -> Settings:
    return Settings(env="local", resolution_max_cluster_size=5)


@pytest.fixture
def manager(repo: FakeRepository, settings: Settings) -> ClusterManager:
    return ClusterManager(repo, settings)


def ligar(manager: ClusterManager, a: str, b: str, score: float = 0.95) -> ClusterAction:
    return manager.link(a, b, RecordType.PERSON, score, EVIDENCIA).action


class TestFormacao:
    def test_cria_entidade_para_par_novo(
        self, manager: ClusterManager, repo: FakeRepository
    ) -> None:
        assert ligar(manager, "r1", "r2") is ClusterAction.CREATED
        entity_id = repo.find_entity_id_for_record("r1")
        assert entity_id == repo.find_entity_id_for_record("r2")
        assert repo.get_entity(entity_id).member_count == 2

    def test_entra_em_entidade_existente(
        self, manager: ClusterManager, repo: FakeRepository
    ) -> None:
        ligar(manager, "r1", "r2")
        assert ligar(manager, "r3", "r2") is ClusterAction.JOINED
        assert repo.get_entity(repo.find_entity_id_for_record("r3")).member_count == 3

    def test_entra_quando_o_novo_e_o_primeiro_argumento(
        self, manager: ClusterManager, repo: FakeRepository
    ) -> None:
        ligar(manager, "r1", "r2")
        assert ligar(manager, "r2", "r9") is ClusterAction.JOINED
        assert repo.find_entity_id_for_record("r9") == repo.find_entity_id_for_record("r1")

    def test_par_ja_ligado_nao_faz_nada(
        self, manager: ClusterManager, repo: FakeRepository
    ) -> None:
        ligar(manager, "r1", "r2")
        antes = repo.get_entity(repo.find_entity_id_for_record("r1")).version
        assert ligar(manager, "r1", "r2") is ClusterAction.ALREADY_LINKED
        assert repo.get_entity(repo.find_entity_id_for_record("r1")).version == antes


class TestFechoTransitivo:
    def test_a_b_e_b_c_reunem_os_tres(self, manager: ClusterManager, repo: FakeRepository) -> None:
        """A propriedade central: A~B e B~C colocam A, B e C juntos."""
        ligar(manager, "A", "B")
        ligar(manager, "B", "C")
        entidades = {repo.find_entity_id_for_record(r) for r in ("A", "B", "C")}
        assert len(entidades) == 1

    def test_funde_dois_clusters(self, manager: ClusterManager, repo: FakeRepository) -> None:
        ligar(manager, "A", "B")
        ligar(manager, "C", "D")
        assert ligar(manager, "B", "C") is ClusterAction.MERGED
        entidades = {repo.find_entity_id_for_record(r) for r in ("A", "B", "C", "D")}
        assert len(entidades) == 1
        assert repo.get_entity(entidades.pop()).member_count == 4

    def test_funde_a_menor_na_maior(self, manager: ClusterManager, repo: FakeRepository) -> None:
        """Menos itens na transacao e menos reescrita de vinculos."""
        ligar(manager, "A", "B")
        ligar(manager, "B", "X")  # cluster com 3
        maior = repo.find_entity_id_for_record("A")
        ligar(manager, "C", "D")  # cluster com 2
        ligar(manager, "B", "C")
        assert repo.find_entity_id_for_record("C") == maior

    def test_registra_evento_auditavel(self, manager: ClusterManager, repo: FakeRepository) -> None:
        """Sem o par que causou a fusao, desfaze-la seria adivinhacao."""
        ligar(manager, "A", "B")
        ligar(manager, "C", "D")
        ligar(manager, "B", "C", score=0.91)

        eventos = repo.list_merge_events(repo.find_entity_id_for_record("A"))
        assert len(eventos) == 1
        assert {eventos[0].record_a, eventos[0].record_b} == {"B", "C"}
        assert eventos[0].score == 0.91
        assert eventos[0].moved_members == 2

    def test_vinculo_guarda_a_evidencia(
        self, manager: ClusterManager, repo: FakeRepository
    ) -> None:
        ligar(manager, "r1", "r2")
        membros = repo.list_entity_members(repo.find_entity_id_for_record("r1"))
        assert all(m.evidence == EVIDENCIA for m in membros)
        assert {m.matched_record_id for m in membros} == {"r1", "r2"}


class TestTetoDeTamanho:
    def test_recusa_entrada_acima_do_teto(
        self, manager: ClusterManager, repo: FakeRepository
    ) -> None:
        """Prefere falso negativo visivel a falso positivo silencioso."""
        ligar(manager, "r0", "r1")
        for i in range(2, 5):
            ligar(manager, f"r{i}", "r0")
        entity_id = repo.find_entity_id_for_record("r0")
        assert repo.get_entity(entity_id).member_count == 5

        assert ligar(manager, "r99", "r0") is ClusterAction.REFUSED_TOO_LARGE
        assert repo.get_entity(entity_id).member_count == 5
        assert repo.find_entity_id_for_record("r99") is None

    def test_recusa_sinaliza_a_entidade(
        self, manager: ClusterManager, repo: FakeRepository
    ) -> None:
        ligar(manager, "r0", "r1")
        for i in range(2, 5):
            ligar(manager, f"r{i}", "r0")
        ligar(manager, "r99", "r0")

        entidade = repo.get_entity(repo.find_entity_id_for_record("r0"))
        assert entidade.flagged is True
        assert "teto" in entidade.flag_reason

    def test_recusa_fusao_que_estouraria(
        self, manager: ClusterManager, repo: FakeRepository
    ) -> None:
        ligar(manager, "a1", "a2")
        ligar(manager, "a3", "a1")  # 3 membros
        ligar(manager, "b1", "b2")
        ligar(manager, "b3", "b1")  # 3 membros

        assert ligar(manager, "a1", "b1") is ClusterAction.REFUSED_TOO_LARGE
        assert repo.find_entity_id_for_record("a1") != repo.find_entity_id_for_record("b1")

    def test_recusa_sinaliza_ambas_as_entidades(
        self, manager: ClusterManager, repo: FakeRepository
    ) -> None:
        ligar(manager, "a1", "a2")
        ligar(manager, "a3", "a1")
        ligar(manager, "b1", "b2")
        ligar(manager, "b3", "b1")
        ligar(manager, "a1", "b1")

        for record_id in ("a1", "b1"):
            assert repo.get_entity(repo.find_entity_id_for_record(record_id)).flagged is True

    def test_teto_configuravel(self, repo: FakeRepository) -> None:
        amplo = ClusterManager(repo, Settings(env="local", resolution_max_cluster_size=100))
        ligar(amplo, "r0", "r1")
        for i in range(2, 20):
            assert ligar(amplo, f"r{i}", "r0") is ClusterAction.JOINED


class TestEntidadeAusente:
    def test_vinculo_apontando_para_entidade_inexistente(
        self, manager: ClusterManager, repo: FakeRepository
    ) -> None:
        """Pode ocorrer se uma fusao concorrente acabou de remove-la."""
        ligar(manager, "r1", "r2")
        entity_id = repo.find_entity_id_for_record("r1")
        repo.entities.pop(entity_id)

        assert ligar(manager, "r3", "r1") is ClusterAction.REFUSED_TOO_LARGE
