"""Janela deslizante persistida — ADR-010.

O ADR-009 registrou uma limitacao do Control Center: os graficos viviam na memoria da
aba. Recarregar a pagina apagava o historico, e a interface dizia isso honestamente com
o rotulo `sessao`. Este modulo fecha a limitacao.

**Amostragem oportunista.** Nao ha processo amostrando em laco — isso seria exatamente
o worker residente que COSTS.md proibe. Quem passa por `/metrics` grava uma amostra se
o balde do instante ainda estiver vazio. Na AWS o EventBridge Scheduler cobre a janela
ociosa chamando `/v1/ops/sample`.

**Limitacao assumida:** sem ninguem observando, nada e amostrado. O historico tem
buracos quando a plataforma fica parada, e a interface explica o buraco em vez de
interpola-lo. Uma linha reta sobre um periodo nao medido seria mais bonita e mentirosa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from nexus.persistence.models import MetricSample
from nexus.persistence.repository import RecordRepository
from nexus.queue.client import QueueClient
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings, get_settings
from nexus.shared.logging import get_logger

logger = get_logger(__name__)

#: Nome da serie. Uma so, com varios valores por amostra, em vez de uma serie por
#: numero: os valores de um mesmo instante so sao comparaveis se vierem do mesmo
#: instante. Separados em series distintas, cada um poderia cair num balde diferente e
#: "fila cheia enquanto o outbox esvaziava" viraria artefato da amostragem.
PLATFORM_SERIES = "platform"


@dataclass(frozen=True, slots=True)
class SampleOutcome:
    """O que aconteceu na tentativa de amostrar."""

    written: bool
    bucket: datetime
    values: dict[str, float]
    reason: str = ""


class MetricSampler:
    """Grava amostras da profundidade da plataforma em baldes de tempo fixos."""

    def __init__(
        self,
        repository: RecordRepository,
        queue: QueueClient,
        settings: Settings | None = None,
    ) -> None:
        self._repo = repository
        self._queue = queue
        self._settings = settings or get_settings()
        #: Ultimo balde que **este processo** gravou. Evita reler o armazenamento a cada
        #: chamada de `/metrics`. Nao serve como garantia: processos concorrentes tem
        #: cada um a sua memoria, e e a escrita condicional que decide de fato.
        self._last_bucket: datetime | None = None

    # ------------------------------------------------------------------ publico

    def bucket_for(self, moment: datetime) -> datetime:
        """Arredonda o instante para o inicio do balde.

        Arredondar antes de gravar e o que torna a escrita condicional util: dois
        observadores no mesmo intervalo produzem a **mesma** chave e colidem de
        proposito. Com o carimbo exato de cada um, nunca colidiriam e a densidade da
        serie mediria o numero de observadores, nao o tempo.
        """
        intervalo = self._settings.series_interval_seconds
        segundos = int(moment.timestamp()) // intervalo * intervalo
        return datetime.fromtimestamp(segundos, tz=moment.tzinfo)

    def sample(
        self, *, force: bool = False, values: dict[str, float] | None = None
    ) -> SampleOutcome:
        """Grava uma amostra do estado atual, se o balde ainda estiver livre.

        ``force`` ignora apenas a memoria local do processo, nunca a condicao de
        escrita: amostrar duas vezes no mesmo balde continua impossivel.

        ``values`` aproveita leituras que quem chama ja fez. `/metrics` consulta o
        backlog e a profundidade da fila para responder; reconsultar aqui dobraria o
        custo da rota mais chamada do painel para obter os mesmos numeros.
        """
        agora = utcnow()
        balde = self.bucket_for(agora)

        if not force and self._last_bucket == balde:
            return SampleOutcome(False, balde, {}, reason="balde ja amostrado por este processo")

        valores = values if values is not None else self._collect()
        if not valores:
            return SampleOutcome(False, balde, {}, reason="estado indisponivel")

        expira = agora + timedelta(days=self._settings.series_retention_days)
        gravou = self._repo.put_metric_sample(
            MetricSample(
                metric=PLATFORM_SERIES,
                bucket=balde,
                values=valores,
                expires_at=int(expira.timestamp()),
            )
        )
        self._last_bucket = balde
        return SampleOutcome(
            gravou,
            balde,
            valores,
            reason="" if gravou else "balde ja ocupado por outro observador",
        )

    def read(self, *, window_minutes: int) -> list[MetricSample]:
        """Devolve a serie da janela pedida, da amostra mais antiga para a mais nova."""
        desde = utcnow() - timedelta(minutes=window_minutes)
        return self._repo.get_metric_series(PLATFORM_SERIES, since=desde)

    # ----------------------------------------------------------------- internos

    def _collect(self) -> dict[str, float]:
        """Le a profundidade atual das duas fontes duraveis.

        Nenhum valor vem de contador em memoria: a serie precisa sobreviver a reinicio
        e ser a mesma entre replicas. Uma fonte indisponivel deixa de fora os seus
        valores em vez de gravar zero — zero e um numero, "nao medido" nao e.
        """
        valores: dict[str, float] = {}

        try:
            valores["outbox_pending"] = float(self._repo.count_pending_outbox())
        except Exception as exc:  # observabilidade nao derruba o observado
            logger.warning("sample_outbox_unavailable", extra={"reason": str(exc)})

        if self._queue.is_enabled:
            try:
                stats = self._queue.stats()
                valores["queue_pending"] = float(stats.pending)
                valores["queue_in_flight"] = float(stats.in_flight)
                valores["queue_dead"] = float(stats.dead)
            except Exception as exc:
                logger.warning("sample_queue_unavailable", extra={"reason": str(exc)})

        return valores
