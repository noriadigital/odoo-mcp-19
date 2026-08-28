"""Profiling de cobertura de campos sobre lo extraído en data/raw/*.json.

Para cada colección: nº de registros y, por campo de primer nivel, el % de
registros con valor no vacío (None, "", [], {} cuentan como vacío). No imprime
valores → sin PII, solo nombres de campo y cobertura.

Uso (desde fmdc/):
    python profile_coverage.py                # todas las colecciones extraídas
    python profile_coverage.py clients projects
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAW = Path(__file__).resolve().parent / "data" / "raw"


def _empty(v: object) -> bool:
    return v is None or v == "" or v == [] or v == {}


def profile(name: str) -> None:
    path = RAW / f"{name}.json"
    if not path.exists():
        print(f"  ! {name}: no extraído todavía")
        return
    rows = json.loads(path.read_text())
    if not isinstance(rows, list) or not rows:
        print(f"\n{name}: {len(rows) if isinstance(rows, list) else '1'} registros (sin filas)")
        return
    n = len(rows)
    fields: dict[str, int] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        for k, v in r.items():
            fields.setdefault(k, 0)
            if not _empty(v):
                fields[k] += 1
    print(f"\n{name}: {n} registros")
    for k in sorted(fields, key=lambda k: -fields[k]):
        pct = 100 * fields[k] / n
        bar = "█" * int(pct / 5)
        print(f"    {k:24s} {pct:5.1f}%  {bar}")


def main() -> None:
    names = sys.argv[1:] or sorted(
        p.stem for p in RAW.glob("*.json") if not p.stem.startswith("_")
    )
    for name in names:
        profile(name)


if __name__ == "__main__":
    main()
