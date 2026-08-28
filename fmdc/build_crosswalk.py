"""Crosswalk clientes LemonSuite ↔ Odoo (SOLO LECTURA de Odoo).

Precedencia de match:
  1. CÓDIGO legacy: LS.code (sin ceros) == x_studio_codigo_cliente_legacy (sin ceros) — clave dura
  2. campo Studio x_studio_codigo_cliente_lemonsuite (= nombre) normalizado
  3. nombre normalizado exacto contra todos los partners
  4. sin match → 'new'

Salida: data/clean/client_crosswalk.csv  +  resumen por consola.
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
OUT = ROOT / "data" / "clean" / "client_crosswalk.csv"

_SUF = re.compile(r"\b(s\.?a\.?i\.?c\.?|s\.?a\.?s\.?|s\.?r\.?l\.?|s\.?a\.?|sociedad anonima|sa|srl)\b")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = _SUF.sub(" ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def code_nolz(v: object) -> str:
    s = str(v or "").strip()
    return str(int(s)) if s.isdigit() else s


def main() -> None:
    ls = json.loads(CLIENTS.read_text())
    od = OdooRead()
    domain = [
        "|", "|", "|",
        ["is_company", "=", True],
        ["customer_rank", ">", 0],
        ["x_studio_codigo_cliente_lemonsuite", "!=", False],
        ["x_studio_codigo_cliente_legacy", "!=", False],
    ]
    partners = od.search_read_all(
        "res.partner", domain,
        ["id", "name", "vat", "x_studio_codigo_cliente_legacy", "x_studio_codigo_cliente_lemonsuite"],
    )
    print(f"LS clients: {len(ls)} · Odoo partners candidatos: {len(partners)}")

    legacy_idx: dict[str, list[dict]] = {}
    studio_idx: dict[str, list[dict]] = {}
    name_idx: dict[str, list[dict]] = {}
    for p in partners:
        name_idx.setdefault(norm(p["name"]), []).append(p)
        lg = p.get("x_studio_codigo_cliente_legacy")
        if lg:
            legacy_idx.setdefault(code_nolz(lg), []).append(p)
        sv = p.get("x_studio_codigo_cliente_lemonsuite")
        if sv:
            studio_idx.setdefault(norm(sv), []).append(p)

    counts = {"legacy": 0, "studio": 0, "name": 0, "ambiguous": 0, "new": 0, "with_vat": 0}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["ls_id", "ls_name", "ls_code", "method", "odoo_id", "odoo_name", "odoo_vat"])
        for c in ls:
            code = code_nolz(c.get("code"))
            nkey = norm(c.get("name", ""))
            hits = legacy_idx.get(code) if code else None
            method = "legacy"
            if not hits:
                hits = studio_idx.get(nkey)
                method = "studio"
            if not hits:
                hits = name_idx.get(nkey)
                method = "name"
            if not hits:
                counts["new"] += 1
                w.writerow([c.get("id"), c.get("name"), c.get("code"), "new", "", "", ""])
            elif len(hits) == 1:
                p = hits[0]
                counts[method] += 1
                if p.get("vat"):
                    counts["with_vat"] += 1
                w.writerow([c.get("id"), c.get("name"), c.get("code"), method,
                            p["id"], p["name"], p.get("vat") or ""])
            else:
                counts["ambiguous"] += 1
                ids = "|".join(str(h["id"]) for h in hits)
                w.writerow([c.get("id"), c.get("name"), c.get("code"), f"ambiguous_{method}", ids, "", ""])

    tot = len(ls)
    m = counts["legacy"] + counts["studio"] + counts["name"]
    print("\n--- Crosswalk ---")
    print(f"  match por CÓDIGO legacy  {counts['legacy']:4d}")
    print(f"  match por Studio(nombre) {counts['studio']:4d}")
    print(f"  match por nombre         {counts['name']:4d}")
    print(f"  TOTAL matcheados         {m:4d}  ({100*m/tot:.1f}%)")
    print(f"    de esos, con CUIT      {counts['with_vat']:4d}")
    print(f"  ambiguos                 {counts['ambiguous']:4d}")
    print(f"  nuevos (a crear)         {counts['new']:4d}")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
