"""Comparación LemonSuite clients ↔ Odoo partners (SOLO LECTURA de Odoo).

Objetivo: antes de migrar, saber cuántos clientes de LemonSuite YA existen en
Odoo (match por nombre normalizado) y cuántos de esos ya tienen CUIT cargado en
Odoo — dado que en LemonSuite el CUIT casi no existe.

Salida:
  - resumen por consola (conteos, sin PII)
  - data/clean/client_match.csv (gitignored): crosswalk accionable

Uso (desde fmdc/):  python compare_clients.py
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

from connectors.odoo_read import OdooRead

ROOT = Path(__file__).resolve().parent
CLIENTS = ROOT / "data" / "raw" / "clients.json"
OUT = ROOT / "data" / "clean" / "client_match.csv"

_SUFFIXES = re.compile(
    r"\b(s\.?a\.?i\.?c\.?|s\.?a\.?s\.?|s\.?r\.?l\.?|s\.?a\.?|sociedad anonima|sa|srl)\b"
)


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = _SUFFIXES.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def main() -> None:
    ls = json.loads(CLIENTS.read_text())
    print(f"LemonSuite clients: {len(ls)}")

    od = OdooRead()
    domain = ["|", ["is_company", "=", True], ["customer_rank", ">", 0]]
    partners = od.search_read_all("res.partner", domain, ["id", "name", "vat", "customer_rank"])
    print(f"Odoo partners (empresas ∪ clientes): {len(partners)}")

    index: dict[str, list[dict]] = {}
    for p in partners:
        index.setdefault(norm(p["name"]), []).append(p)

    matched = matched_vat = ambiguous = new = 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["ls_id", "ls_name", "ls_code", "match", "odoo_id", "odoo_name", "odoo_vat", "note"]
        )
        for c in ls:
            key = norm(c.get("name", ""))
            hits = index.get(key, [])
            if not hits:
                new += 1
                w.writerow([c.get("id"), c.get("name"), c.get("code"), "no", "", "", "", "nuevo"])
            elif len(hits) == 1:
                matched += 1
                p = hits[0]
                if p.get("vat"):
                    matched_vat += 1
                w.writerow(
                    [c.get("id"), c.get("name"), c.get("code"), "si", p["id"], p["name"],
                     p.get("vat") or "", ""]
                )
            else:
                ambiguous += 1
                ids = "|".join(str(h["id"]) for h in hits)
                w.writerow(
                    [c.get("id"), c.get("name"), c.get("code"), "ambiguo", ids, "", "",
                     f"{len(hits)} candidatos"]
                )

    print("\n--- Resultado del match por nombre ---")
    print(f"  ya en Odoo (1:1)        {matched:4d}  ({100*matched/len(ls):.1f}%)")
    print(f"    de esos, con CUIT     {matched_vat:4d}")
    print(f"  ambiguos (>1 candidato) {ambiguous:4d}")
    print(f"  nuevos (a crear)        {new:4d}")
    print(f"\nCrosswalk → {OUT}")


if __name__ == "__main__":
    main()
