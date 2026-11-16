"""Gera o retrato local das fontes versionadas para o build do Control Center.

Execute apos alterar ADRs ou corridas: python scripts/export_lab_data.py.
O arquivo gerado permite builds em que control-center e a raiz publicada.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
adrs = sorted((root / "docs/adr").glob("ADR-*.md"))
runs = sorted((root / "docs/performance/runs").glob("*.json"))
data = {
    "adrs": [{"path": str(p.relative_to(root)), "content": p.read_text()} for p in adrs],
    "runs": [{"path": str(p.relative_to(root)), "data": json.loads(p.read_text())} for p in runs],
}
dest = root / "control-center/src/generated/lab-data.json"
result = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
if "--check" in sys.argv:
    if not dest.exists() or dest.read_text() != result:
        raise SystemExit("Dados do lab desatualizados: execute python scripts/export_lab_data.py")
else:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(result)
