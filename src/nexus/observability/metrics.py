"""Metricas operacionais em processo.

**Limitacao deliberada e importante:** este registro vive na memoria do processo. Os
numeros zeram a cada reinicio e nao sao compartilhados entre replicas. Para a Fase 1,
com um unico processo local, isso e suficiente e honesto.

Na Fase 3 as metricas passam a vir do CloudWatch. Apresentar os numeros deste modulo
como metricas agregadas de plataforma seria falso — ver README e COSTS.md.

Percentis em vez de media: a media esconde a cauda. Com 95 requisicoes de 10 ms e 5 de
2 s, a media diz 110 ms e parece saudavel, mas 5% dos clientes esperaram 2 segundos.
"""

from __future__ import annotations

import threading
from collections import Counter, deque
from typing import Any

#: Amostras retidas por serie. Limite fixo para que a memoria nao cresca com o trafego.
_MAX_SAMPLES = 4_096


class MetricsRegistry:
    """Contadores e amostras de latencia, seguros para uso concorrente."""

    def __init__(self, max_samples: int = _MAX_SAMPLES) -> None:
        self._lock = threading.Lock()
        self._counters: Counter[str] = Counter()
        self._samples: dict[str, deque[float]] = {}
        self._max_samples = max_samples

    def increment(self, name: str, amount: int = 1, **labels: str) -> None:
        key = _key(name, labels)
        with self._lock:
            self._counters[key] += amount

    def observe(self, name: str, value_ms: float, **labels: str) -> None:
        key = _key(name, labels)
        with self._lock:
            series = self._samples.get(key)
            if series is None:
                series = deque(maxlen=self._max_samples)
                self._samples[key] = series
            series.append(value_ms)

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._samples.clear()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            latencies = {
                name: _summarize(list(series)) for name, series in self._samples.items() if series
            }
        return {"counters": counters, "latency_ms": latencies}


def _key(name: str, labels: dict[str, str]) -> str:
    if not labels:
        return name
    rendered = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    return f"{name}{{{rendered}}}"


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Percentil pelo metodo do vizinho mais proximo.

    Sem interpolacao: o valor devolvido e sempre uma observacao real, nao uma media
    entre duas. Para latencia isso e preferivel — o numero corresponde a uma requisicao
    que de fato aconteceu.
    """
    if not sorted_values:
        return 0.0
    index = max(0, min(len(sorted_values) - 1, round(fraction * len(sorted_values) + 0.5) - 1))
    return sorted_values[index]


def _summarize(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "count": float(len(ordered)),
        "min": round(ordered[0], 3),
        "max": round(ordered[-1], 3),
        "mean": round(sum(ordered) / len(ordered), 3),
        "p50": round(_percentile(ordered, 0.50), 3),
        "p95": round(_percentile(ordered, 0.95), 3),
        "p99": round(_percentile(ordered, 0.99), 3),
    }


#: Registro do processo.
registry = MetricsRegistry()
