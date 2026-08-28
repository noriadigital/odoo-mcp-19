"""Matcheo maximal clientes LemonSuite ↔ Odoo (SOLO LECTURA de Odoo).

Estrategia por cliente LS (precedencia):
  1. CÓDIGO legacy exacto (LS.code sin ceros == x_studio_codigo_cliente_legacy).
     - 1 partner → match directo.
     - N partners (mismo código, varios clientes en Odoo = ERROR de dato) → se
       resuelve eligiendo el partner cuyo NOMBRE mejor matchea; el resto se marca
       como conflicto para revisar.
  2. Nombre exacto normalizado (nombre o campo Studio-nombre).
  3. Fuzzy por nombre (token-set + SequenceMatcher, con blocking por token).

Además, pasada inversa Odoo→LS para medir cobertura: qué clientes de Odoo NO
tienen par en LemonSuite (esperado: proveedores colados; o clientes reales que
faltan revisar).

Salidas (data/clean/):
  client_match_full.csv     — cada cliente LS → su match Odoo (método + score)
  odoo_unmatched.csv        — clientes Odoo sin par LS (a revisar)
  legacy_code_conflicts.csv — códigos legacy en >1 partner (error de dato)
  + stats por consola para el informe.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from connectors.odoo_read import OdooRead

ROOT = Path(__file__).resolve().parent
CLEAN = ROOT / "data" / "clean"
_SUF = re.compile(r"\b(s\.?a\.?i\.?c\.?|s\.?a\.?s\.?|s\.?r\.?l\.?|s\.?a\.?|sociedad anonima|sa|srl|saic)\b")
STRONG, REVIEW = 0.90, 0.72


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = _SUF.sub(" ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def nolz(v: object) -> str:
    s = str(v or "").strip()
    return str(int(s)) if s.isdigit() else s


def toks(n: str) -> set[str]:
    return {t for t in n.split() if len(t) > 1}


def sim(a: str, b: str) -> float:
    A, B = toks(a), toks(b)
    if not A or not B:
        return 0.0
    inter = len(A & B)
    jac = inter / len(A | B)
    # contención: un nombre (casi) contenido en el otro — capta "Blue Star" ⊂ "Blue Star Group"
    contain = inter / min(len(A), len(B))
    if min(len(A), len(B)) == 1:
        contain *= 0.8  # un solo token distintivo es más riesgoso → a revisar, no fuerte
    else:
        contain *= 0.95
    # char-level sobre tokens ordenados — capta typos y orden invertido
    sm = SequenceMatcher(None, " ".join(sorted(A)), " ".join(sorted(B))).ratio()
    return max(jac, contain, sm)


def build_index(items: list[dict], nkey: str):
    """Inverted token index → ids; ignora tokens demasiado frecuentes (blocking)."""
    idx: dict[str, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        for t in toks(it[nkey]):
            idx[t].append(i)
    common = {t for t, v in idx.items() if len(v) > 60}
    return idx, common


def best_match(query: str, items: list[dict], nkey: str, idx, common) -> tuple[int, float]:
    cand: set[int] = set()
    for t in toks(query):
        if t not in common:
            cand.update(idx.get(t, []))
    best_i, best_s = -1, 0.0
    for i in cand:
        s = sim(query, items[i][nkey])
        if s > best_s:
            best_i, best_s = i, s
    return best_i, best_s


def main() -> None:
    CLEAN.mkdir(parents=True, exist_ok=True)
    ls = json.loads((ROOT / "data" / "raw" / "clients.json").read_text())
    for c in ls:
        c["_n"] = norm(c.get("name"))
        c["_code"] = nolz(c.get("code"))

    od = OdooRead()
    domain = ["|", "|", "|",
              ["is_company", "=", True], ["customer_rank", ">", 0],
              ["x_studio_codigo_cliente_lemonsuite", "!=", False],
              ["x_studio_codigo_cliente_legacy", "!=", False]]
    part = od.search_read_all("res.partner", domain,
        ["id", "name", "vat", "x_studio_codigo_cliente_legacy",
         "x_studio_codigo_cliente_lemonsuite", "customer_rank", "supplier_rank"])
    for p in part:
        p["_n"] = norm(p.get("name"))
        p["_studio"] = norm(p.get("x_studio_codigo_cliente_lemonsuite"))
        p["_code"] = nolz(p.get("x_studio_codigo_cliente_legacy"))
    print(f"LS clients: {len(ls)} · Odoo partners: {len(part)}")

    # índices
    legacy_idx: dict[str, list[int]] = defaultdict(list)
    exact_idx: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(part):
        if p["_code"]:
            legacy_idx[p["_code"]].append(i)
        exact_idx[p["_n"]].append(i)
        if p["_studio"]:
            exact_idx[p["_studio"]].append(i)
    p_tok_idx, p_common = build_index(part, "_n")

    # conflictos de código (mismo legacy en >1 partner)
    conflicts = {code: idxs for code, idxs in legacy_idx.items() if len(idxs) > 1}

    # LS → Odoo
    matched_odoo: set[int] = set()
    counts = {"legacy": 0, "legacy_multi": 0, "exact": 0, "fuzzy_strong": 0,
              "fuzzy_review": 0, "none": 0, "with_vat": 0}
    with (CLEAN / "client_match_full.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["ls_id", "ls_name", "ls_code", "method", "score", "odoo_id", "odoo_name", "odoo_vat"])
        for c in ls:
            method, score, pi = "none", 0.0, -1
            if c["_code"] and c["_code"] in legacy_idx:
                cands = legacy_idx[c["_code"]]
                if len(cands) == 1:
                    pi, score, method = cands[0], 1.0, "legacy"
                else:  # 1:N → elegir por mejor nombre
                    pi = max(cands, key=lambda i: sim(c["_n"], part[i]["_n"]))
                    score, method = sim(c["_n"], part[pi]["_n"]), "legacy_multi"
            elif c["_n"] in exact_idx:
                pi, score, method = exact_idx[c["_n"]][0], 1.0, "exact"
            else:
                bi, bs = best_match(c["_n"], part, "_n", p_tok_idx, p_common)
                if bs >= STRONG:
                    pi, score, method = bi, bs, "fuzzy_strong"
                elif bs >= REVIEW:
                    pi, score, method = bi, bs, "fuzzy_review"
            counts[method] += 1
            if pi >= 0:
                p = part[pi]
                matched_odoo.add(pi)
                if p.get("vat"):
                    counts["with_vat"] += 1
                w.writerow([c["id"], c.get("name"), c.get("code"), method, f"{score:.2f}",
                            p["id"], p["name"], p.get("vat") or ""])
            else:
                w.writerow([c["id"], c.get("name"), c.get("code"), "none", "", "", "", ""])

    # Odoo → LS (cobertura): clientes Odoo (customer_rank>0) sin par LS
    ls_tok_idx, ls_common = build_index(ls, "_n")
    ls_exact = {c["_n"] for c in ls}
    ls_codes = {c["_code"] for c in ls if c["_code"]}
    odoo_customers = [p for p in part if (p.get("customer_rank") or 0) > 0]
    unmatched_rows = []
    cov = {"matched": 0, "unmatched": 0, "unmatched_vendor": 0}
    for p in odoo_customers:
        hit = (p["_code"] in ls_codes) or (p["_n"] in ls_exact) or (p["_studio"] in ls_exact)
        if not hit:
            _, bs = best_match(p["_n"], ls, "_n", ls_tok_idx, ls_common)
            hit = bs >= REVIEW
        if hit:
            cov["matched"] += 1
        else:
            cov["unmatched"] += 1
            is_vendor = (p.get("supplier_rank") or 0) > 0
            if is_vendor:
                cov["unmatched_vendor"] += 1
            unmatched_rows.append([p["id"], p["name"], p.get("vat") or "",
                                   p.get("customer_rank"), p.get("supplier_rank"),
                                   "proveedor?" if is_vendor else "revisar"])

    with (CLEAN / "odoo_unmatched.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["odoo_id", "name", "vat", "customer_rank", "supplier_rank", "nota"])
        w.writerows(unmatched_rows)

    with (CLEAN / "legacy_code_conflicts.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["legacy_code", "n_partners", "odoo_id", "odoo_name", "vat"])
        for code, idxs in sorted(conflicts.items(), key=lambda x: -len(x[1])):
            for i in idxs:
                w.writerow([code, len(idxs), part[i]["id"], part[i]["name"], part[i].get("vat") or ""])

    # stats para el informe
    stats = {"counts": counts, "coverage": cov,
             "conflicts_codes": len(conflicts),
             "conflicts_partners": sum(len(v) for v in conflicts.values()),
             "ls_total": len(ls), "odoo_total": len(part),
             "odoo_customers": len(odoo_customers)}
    (CLEAN / "match_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2))

    m = counts["legacy"] + counts["legacy_multi"] + counts["exact"] + counts["fuzzy_strong"] + counts["fuzzy_review"]
    print("\n=== LS → Odoo (de", len(ls), "clientes LS) ===")
    for k in ("legacy", "legacy_multi", "exact", "fuzzy_strong", "fuzzy_review", "none"):
        print(f"  {k:14s} {counts[k]:4d}")
    print(f"  TOTAL match    {m:4d} ({100*m/len(ls):.1f}%) · con CUIT {counts['with_vat']}")
    print(f"\n=== Odoo → LS (de {len(odoo_customers)} clientes Odoo) ===")
    print(f"  con par LS     {cov['matched']:4d}")
    print(f"  sin par LS     {cov['unmatched']:4d}  (de esos, proveedores: {cov['unmatched_vendor']})")
    print(f"\n=== Conflictos código legacy: {len(conflicts)} códigos / {stats['conflicts_partners']} partners ===")


if __name__ == "__main__":
    main()
