"""Exporta clientes de Odoo (con campos Studio LemonSuite) a CSV para cruzar en Power Query.

Universo: partners que son cliente (customer_rank>0) O empresa O tienen el campo
Studio seteado. Incluye columnas _name_norm y _studio_norm (la clave con la que
hace el match build_crosswalk.py) para auditar el merge.

Salida: data/odoo_export/odoo_clients.csv (utf-8-sig → Excel/Power Query OK).
"""

from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

from connectors.odoo_read import OdooRead

OUT = Path(__file__).resolve().parent / "data" / "odoo_export" / "odoo_clients.csv"
_SUF = re.compile(r"\b(s\.?a\.?i\.?c\.?|s\.?a\.?s\.?|s\.?r\.?l\.?|s\.?a\.?|sociedad anonima|sa|srl)\b")

FIELDS = [
    "id", "name", "x_studio_codigo_cliente_legacy", "x_studio_codigo_cliente_lemonsuite",
    "x_studio_codigo_tipo_de_empresa", "x_studio_estado_lemonsuite",
    "x_studio_fecha_alta_lemonsuite", "vat", "ref", "is_company", "customer_rank",
    "supplier_rank", "active", "email", "phone", "parent_id", "create_date",
]


def code_nolz(v: object) -> str:
    s = str(v or "").strip()
    return str(int(s)) if s.isdigit() else s


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = _SUF.sub(" ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def main() -> None:
    od = OdooRead()
    print("target:", od.url)
    domain = [
        "|", "|",
        ["customer_rank", ">", 0],
        ["is_company", "=", True],
        ["x_studio_codigo_cliente_lemonsuite", "!=", False],
    ]
    rows = od.search_read_all("res.partner", domain, FIELDS)
    print(f"partners exportados: {len(rows)}")
    with_studio = sum(1 for r in rows if r.get("x_studio_codigo_cliente_lemonsuite"))
    print(f"  con campo Studio seteado: {with_studio}")

    with_legacy = sum(1 for r in rows if r.get("x_studio_codigo_cliente_legacy"))
    print(f"  con Codigo Cliente Legacy (código LS): {with_legacy}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    cols = FIELDS + ["parent_name", "_legacy_code_nolz", "_name_norm", "_studio_norm"]
    with OUT.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            parent = r.get("parent_id")
            r["parent_id"] = parent[0] if isinstance(parent, list) else ""
            r["parent_name"] = parent[1] if isinstance(parent, list) else ""
            r["_legacy_code_nolz"] = code_nolz(r.get("x_studio_codigo_cliente_legacy"))
            r["_name_norm"] = norm(r.get("name"))
            r["_studio_norm"] = norm(r.get("x_studio_codigo_cliente_lemonsuite"))
            w.writerow(r)
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
