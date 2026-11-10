"""Alertas calculados — ADR-010.

Nenhuma condicao aqui e configurada em outro lugar: todas sao **derivadas do estado
real** no instante da pergunta. E a mesma licao que a Fase 4 custou caro para aprender.
A API declarava `entity_resolution: not_implemented` porque alguem escreveu isso a mao
na Fase 2 e a Fase 5 esqueceu de corrigir — estado declarado envelhece em silencio,
estado derivado nao tem como.

**Sem CloudWatch.** A infraestrutura AWS esta destruida, e alarme que so existe na
nuvem nao serve ao ambiente onde a plataforma roda hoje. Quando a infraestrutura
voltar, estas mesmas condicoes viram metricas customizadas e alarmes; o calculo ja
estara pronto e continua valendo local.

**Cada alerta declara a sua origem**, pela mesma regra do ADR-009: `persistido` para o
que vem do armazenamento e sobrevive a reinicio, `processo` para o que vive em memoria
e zera no proximo deploy. Um alerta de taxa de erro que some sozinho ao reiniciar o
processo precisa dizer que e assim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Any

from nexus.observability.metrics import registry
from nexus.persistence.repository import RecordRepository
from nexus.queue.client import QueueClient
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings, get_settings
from nexus.shared.logging import get_logger

logger = get_logger(__name__)


class Severity(StrEnum):
    """Gravidade do alerta.

    Apenas dois niveis. `ERROR` e "ha trabalho parado ou perdido e alguem precisa
    agir"; `WARNING` e "esta fora do esperado e tende a piorar". Uma terceira faixa
    informativa so produziria linhas que ninguem le, e alerta que ninguem le treina a
    ignorar os outros.
    """

    ERROR = "error"
    WARNING = "warning"


class Origin(StrEnum):
    """De onde veio o numero que acendeu o alerta — ADR-009."""

    PERSISTED = "persistido"
    PROCESS = "processo"


@dataclass(frozen=True, slots=True)
class Alert:
    """Uma condicao ativa."""

    id: str
    severity: Severity
    title: str
    detail: str
    origin: Origin
    value: float | None = None
    threshold: float | None = None
    context: dict[str, Any] = field(default_factory=dict)


class AlertEvaluator:
    """Avalia todas as condicoes e devolve as que estao ativas."""

    def __init__(
        self,
        repository: RecordRepository,
        queue: QueueClient,
        settings: Settings | None = None,
    ) -> None:
        self._repo = repository
        self._queue = queue
        self._settings = settings or get_settings()

    def evaluate(self) -> list[Alert]:
        """Devolve os alertas ativos, os mais graves primeiro.

        Uma condicao que nao pode ser avaliada nao vira alerta nem silencio: a
        indisponibilidade da fonte **e** o alerta — ver `_persistencia`. Fingir que
        esta tudo bem porque a leitura falhou e o pior resultado possivel para um
        painel de operacao.
        """
        ativos: list[Alert] = []
        indisponivel = self._persistencia()
        if indisponivel is not None:
            # Sem persistencia, backlog e idade do outbox nao sao avaliaveis. Devolver
            # so este alerta e mais honesto que acompanha-lo de numeros inventados.
            ativos.append(indisponivel)
        else:
            ativos.extend(self._outbox())
            ativos.extend(self._clusters())

        ativos.extend(self._dlq())
        ativos.extend(self._taxa_de_erro())

        ordem = {Severity.ERROR: 0, Severity.WARNING: 1}
        return sorted(ativos, key=lambda a: (ordem[a.severity], a.id))

    # ----------------------------------------------------------------- condicoes

    def _persistencia(self) -> Alert | None:
        try:
            disponivel = self._repo.ping()
        except Exception as exc:
            logger.warning("alert_ping_failed", extra={"reason": str(exc)})
            disponivel = False
        if disponivel:
            return None
        return Alert(
            id="persistence_unavailable",
            severity=Severity.ERROR,
            title="Persistencia indisponivel",
            detail=(
                "A tabela nao respondeu. Ingestao, consumo e resolucao estao parados; "
                "os demais indicadores nao sao avaliaveis enquanto isso durar."
            ),
            origin=Origin.PERSISTED,
        )

    def _dlq(self) -> list[Alert]:
        if not self._queue.is_enabled:
            return []
        try:
            stats = self._queue.stats()
        except Exception as exc:
            logger.warning("alert_queue_stats_failed", extra={"reason": str(exc)})
            return []
        if stats.dead == 0:
            return []
        return [
            Alert(
                id="dlq_not_empty",
                severity=Severity.ERROR,
                title="Mensagens na DLQ",
                detail=(
                    f"{stats.dead} mensagem(ns) esgotaram as tentativas. "
                    "Nenhuma sera reprocessada sem um redrive explicito."
                ),
                origin=Origin.PERSISTED,
                value=float(stats.dead),
                threshold=0.0,
            )
        ]

    def _outbox(self) -> list[Alert]:
        alertas: list[Alert] = []

        try:
            backlog = self._repo.count_pending_outbox()
        except Exception as exc:
            logger.warning("alert_backlog_failed", extra={"reason": str(exc)})
            return alertas

        limite = self._settings.alert_outbox_backlog
        if backlog > limite:
            alertas.append(
                Alert(
                    id="outbox_backlog",
                    severity=Severity.WARNING,
                    title="Backlog do outbox acima do limite",
                    detail=(
                        f"{backlog} eventos aguardam publicacao (limite {limite}). "
                        "Um dispatch resolve se for acumulo normal."
                    ),
                    origin=Origin.PERSISTED,
                    value=float(backlog),
                    threshold=float(limite),
                )
            )

        # Backlog grande e backlog parado sao problemas diferentes. Sessenta eventos
        # que chegaram agora sao vazao; tres parados ha vinte minutos sao um dispatcher
        # que nao roda — e so o segundo caso perde dados pela expiracao do TTL.
        try:
            mais_antigo = self._repo.oldest_pending_outbox_at()
        except Exception as exc:
            logger.warning("alert_oldest_failed", extra={"reason": str(exc)})
            return alertas

        if mais_antigo is None:
            return alertas

        idade = utcnow() - mais_antigo
        teto = timedelta(minutes=self._settings.alert_outbox_age_minutes)
        if idade > teto:
            minutos = idade / timedelta(minutes=1)
            alertas.append(
                Alert(
                    id="outbox_stalled",
                    severity=Severity.WARNING,
                    title="Evento de outbox parado",
                    detail=(
                        f"O evento pendente mais antigo espera ha {minutos:.0f} minutos "
                        f"(limite {self._settings.alert_outbox_age_minutes}). "
                        "Indica dispatcher sem execucao, nao volume."
                    ),
                    origin=Origin.PERSISTED,
                    value=round(minutos, 1),
                    threshold=float(self._settings.alert_outbox_age_minutes),
                )
            )
        return alertas

    def _clusters(self) -> list[Alert]:
        try:
            stats = self._repo.get_resolution_stats()
        except Exception as exc:
            logger.warning("alert_resolution_stats_failed", extra={"reason": str(exc)})
            return []

        recusas = int(stats.get("refused_too_large", 0))
        if recusas == 0:
            return []
        return [
            Alert(
                id="cluster_cap_refusals",
                severity=Severity.WARNING,
                title="Fusoes recusadas pelo teto de cluster",
                detail=(
                    f"{recusas} fusao(oes) foram recusadas por excederem o teto de "
                    f"{self._settings.resolution_max_cluster_size} membros. O teto evita "
                    "que um erro de correspondencia colapse a base numa entidade so; "
                    "recusas repetidas sugerem revisar os pesos."
                ),
                origin=Origin.PERSISTED,
                value=float(recusas),
                threshold=0.0,
            )
        ]

    def _taxa_de_erro(self) -> list[Alert]:
        """Proporcao de respostas 5xx sobre o total, nos contadores deste processo.

        Nao e taxa de plataforma: zera a cada reinicio e nao soma entre replicas. O
        alerta declara `processo` por isso, e some sozinho num deploy — limitacao real,
        dita em vez de escondida.
        """
        counters = registry.snapshot()["counters"]
        total = erros = 0
        for chave, valor in counters.items():
            if not chave.startswith("http_requests_total"):
                continue
            total += int(valor)
            if "status=5" in chave:
                erros += int(valor)

        # Amostra pequena produz taxa instavel: a primeira 500 numa amostra de tres
        # requisicoes daria 33% e acenderia um alerta que nao significa nada.
        if total < 20 or erros == 0:
            return []

        taxa = erros / total
        limite = self._settings.alert_error_rate
        if taxa <= limite:
            return []
        return [
            Alert(
                id="http_error_rate",
                severity=Severity.WARNING,
                title="Taxa de erro HTTP acima do limite",
                detail=(
                    f"{erros} de {total} respostas foram 5xx ({taxa:.1%}, limite "
                    f"{limite:.1%}). Contagem deste processo desde o ultimo reinicio."
                ),
                origin=Origin.PROCESS,
                value=round(taxa, 4),
                threshold=limite,
                context={"errors": erros, "requests": total},
            )
        ]
