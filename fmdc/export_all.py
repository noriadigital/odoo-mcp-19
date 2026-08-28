"""Exporta TODO LemonSuite a CSV — un archivo por entidad + resumen.

Salida: data/lemonsuite_export/<entidad>.csv  (+ _resumen.md)
Aplana objetos anidados a columnas dotted (a.b); listas y dicts profundos → JSON.
Resiliente: si una entidad falla, la registra y sigue.

Uso (desde fmdc/):  python export_all.py
"""

from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from connectors.lemonsuite_client import LemonSuiteClient
from endpoints import PER_CLIENT, TOP_LEVEL
from worklog import _load_env

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "lemonsuite_export"


def flatten(rec: dict) -> dict:
    out: dict = {}
    for k, v in rec.items():
        if isinstance(v, dict):
            for sk, sv in v.items():
                out[f"{k}.{sk}"] = sv if not isinstance(sv, (dict, list)) else json.dumps(sv, ensure_ascii=False)
        elif isinstance(v, list):
            out[k] = json.dumps(v, ensure_ascii=False)
        else:
            out[k] = v
    return out


def write_csv(name: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    flat = [flatten(r) for r in rows if isinstance(r, dict)]
    cols: list[str] = []
    seen = set()
    for r in flat:
        for k in r:
            if k not in seen:
                seen.add(k)
                cols.append(k)
    # utf-8-sig (BOM) para que Excel detecte UTF-8 al abrir con doble clic.
    with (OUT / f"{name}.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(flat)
    return len(flat)


def main() -> None:
    _load_env()
    OUT.mkdir(parents=True, exist_ok=True)
    cli = LemonSuiteClient(os.environ["LEMONSUITE_TENANT"], os.environ["LEMONSUITE_TOKEN"])
    print(f"→ export a {OUT}")
    summary: list[tuple[str, int, int, str]] = []  # entidad, filas, columnas, estado

    def do(name: str, rows: list[dict]) -> None:
        n = write_csv(name, rows)
        ncols = len(next(iter([flatten(r) for r in rows if isinstance(r, dict)]), {})) if rows else 0
        estado = "ok" if n else "vacía (sin archivo)"
        summary.append((name, n, ncols, estado))
        print(f"  {'✓' if n else '·'} {name:24s} {n:>7} filas / {ncols} cols  {estado if not n else ''}")

    # Top-level
    for name, path in TOP_LEVEL.items():
        t0 = time.time()
        try:
            rows = cli.collect(path)
            do(name, rows)
            if time.time() - t0 > 5:
                print(f"      ({time.time()-t0:.0f}s)")
        except Exception as exc:  # noqa: BLE001
            summary.append((name, 0, 0, f"ERROR: {exc}"))
            print(f"  ✗ {name:24s} ERROR: {str(exc)[:80]}")

    # Per-client anidados
    clients = cli.collect("/clients")
    cids = [c["id"] for c in clients if "id" in c]
    for name, tmpl in PER_CLIENT.items():
        t0 = time.time()
        allrows: list[dict] = []
        try:
            for cid in cids:
                for r in cli.collect(tmpl.format(id=cid)):
                    r["_client_id"] = cid
                    allrows.append(r)
            do(name, allrows)
            print(f"      ({time.time()-t0:.0f}s, {len(cids)} clientes)")
        except Exception as exc:  # noqa: BLE001
            summary.append((name, 0, 0, f"ERROR: {exc}"))
            print(f"  ✗ {name:24s} ERROR: {str(exc)[:80]}")

    # Resumen
    total = sum(n for _, n, _, _ in summary)
    lines = [
        "# Resumen de exportación — LemonSuite",
        "",
        f"**Fecha:** {datetime.now(timezone.utc).isoformat()}  ",
        f"**Origen:** {cli.base_url}  ",
        f"**Carpeta:** `{OUT}`  ",
        f"**Total de registros exportados:** {total:,}",
        "",
        "| Entidad (archivo) | Filas | Columnas | Estado |",
        "|---|---:|---:|---|",
    ]
    for name, n, ncols, estado in summary:
        arch = f"`{name}.csv`" if n else "—"
        lines.append(f"| {arch} | {n:,} | {ncols} | {estado} |")
    (OUT / "_resumen.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n=== TOTAL {total:,} registros · resumen → {OUT/'_resumen.md'} ===")


if __name__ == "__main__":
    main()
