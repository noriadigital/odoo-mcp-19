"""Fase 0 — Extracción de LemonSuite a JSON crudo.

Lee credenciales de .env (LEMONSUITE_TENANT / LEMONSUITE_TOKEN), pagina cada
colección y las vuelca a data/raw/<nombre>.json. Escribe un manifest con
conteos y timestamp para el profiling posterior.

Uso (desde fmdc/):
    python extract.py                # todo
    python extract.py clients projects   # solo algunas colecciones top-level
    python extract.py --skip-per-client  # sin las anidadas por cliente

Es idempotente: reescribe los .json en cada corrida (es un snapshot).
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from connectors.lemonsuite_client import LemonSuiteClient, LemonSuiteError
from endpoints import PER_CLIENT, TOP_LEVEL

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"


def _load_env() -> tuple[str, str]:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    tenant = os.environ.get("LEMONSUITE_TENANT", "")
    token = os.environ.get("LEMONSUITE_TOKEN", "")
    if not tenant or not token:
        sys.exit(
            "Faltan credenciales. Copiá .env.example a .env y completá "
            "LEMONSUITE_TENANT y LEMONSUITE_TOKEN."
        )
    return tenant, token


def _dump(name: str, rows: list) -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f"{name}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return len(rows)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    skip_per_client = "--skip-per-client" in sys.argv

    tenant, token = _load_env()
    client = LemonSuiteClient(tenant, token)
    print(f"→ tenant: {tenant}")

    selected = args or list(TOP_LEVEL)
    manifest: dict[str, object] = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "tenant": tenant,
        "counts": {},
    }
    counts: dict[str, int] = manifest["counts"]  # type: ignore[assignment]

    for name in selected:
        path = TOP_LEVEL.get(name)
        if not path:
            print(f"  ! colección desconocida: {name} (omitida)")
            continue
        t0 = time.time()
        try:
            rows = client.collect(path)
        except LemonSuiteError as exc:
            print(f"  ✗ {name}: {exc}")
            counts[name] = -1
            continue
        n = _dump(name, rows)
        counts[name] = n
        print(f"  ✓ {name:24s} {n:>7,d} registros  ({time.time() - t0:.1f}s)")

    # Colecciones anidadas por cliente (legal_entities, contacts).
    if not skip_per_client and (not args or "clients" in args):
        clients_file = RAW / "clients.json"
        if clients_file.exists():
            clients = json.loads(clients_file.read_text())
            client_ids = [c["id"] for c in clients if "id" in c]
            for name, tmpl in PER_CLIENT.items():
                t0 = time.time()
                all_rows: list = []
                for cid in client_ids:
                    try:
                        rows = client.collect(tmpl.format(id=cid))
                    except LemonSuiteError as exc:
                        print(f"  ! {name} cliente {cid}: {exc}")
                        continue
                    for r in rows:
                        r["_client_id"] = cid  # crosswalk al padre
                    all_rows.extend(rows)
                counts[name] = _dump(name, all_rows)
                print(
                    f"  ✓ {name:24s} {counts[name]:>7,d} registros "
                    f"(de {len(client_ids)} clientes, {time.time() - t0:.1f}s)"
                )
        else:
            print("  ! sin clients.json → salteo legal_entities/contacts anidados")

    (RAW / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nManifest → {RAW / '_manifest.json'}")


if __name__ == "__main__":
    main()
