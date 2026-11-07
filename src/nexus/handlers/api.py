"""Handler da API — FastAPI sobre Lambda via Mangum.

E o **mesmo** aplicativo que roda em Uvicorn no Docker local. Mangum traduz o evento do
API Gateway para ASGI e a resposta de volta; nenhuma rota, dependencia ou schema muda.

``lifespan="off"``: o ciclo de vida ASGI pressupoe um processo que sobe e desce uma vez,
o que nao corresponde ao modelo da Lambda. A configuracao que o lifespan faria acontece
abaixo, no nivel do modulo.
"""

from __future__ import annotations

from mangum import Mangum

from nexus.ingestion.api import app
from nexus.shared.config import get_settings
from nexus.shared.logging import configure_logging, get_logger

_settings = get_settings()
configure_logging(_settings.log_level, _settings.service_name)
logger = get_logger(__name__)

logger.info(
    "lambda_cold_start",
    extra={"handler": "api", "environment": _settings.env, "table": _settings.dynamo_table},
)

handler = Mangum(app, lifespan="off")
