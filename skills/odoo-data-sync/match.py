"""Motor de matching por clave (fuerte -> debil) + fuzzy, con umbrales claros.

REUTILIZABLE: configurá el bloque CONFIG y corré. Produce un plan con la columna
`clave_usada` por registro (regla 2) y separa fuzzy_strong (aplica) de fuzzy_review (revisar).

Entradas:
  - SOURCE_CSV : export de la fuente externa (una fila por registro fuente).
  - ODOO_JSON  : lista JSON de registros Odoo (dump de un search_read del MCP; si el MCP
                 guardó el resultado en archivo por tamaño, apuntá a ese .txt — trae {"result":[...]}).
Salida:
  - OUT_PLAN (.json) con, por registro Odoo: clave_usada, score, valores objetivo y actuales.
  - Resumen por consola (conteos por clave).

Adaptá CONFIG a tu caso. El resto es el motor (no tocar salvo para afinar `sim`).
"""
from __future__ import annotations
import csv, json, re, unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

# ============================ CONFIG (editar) ============================
SOURCE_CSV = "fuente/clients.csv"          # export de la fuente
ODOO_JSON  = "odoo_records.json"           # dump del search_read (o el .txt del MCP con {"result":[...]})
OUT_PLAN   = "sync_plan.json"

STRONG, REVIEW = 0.90, 0.72                # umbrales fuzzy (regla 3)

# Claves fuente: cómo leer cada clave DEL registro fuente
SRC = {
    "code": lambda r: r.get("code"),       # código/legacy en la fuente
    "vat":  lambda r: r.get("vat"),        # documento fiscal (o None si la fuente no lo tiene)
    "name": lambda r: r.get("name"),       # nombre en la fuente
}
# Claves Odoo: cómo leer cada clave DEL registro Odoo
ODO = {
    "code": lambda p: p.get("x_studio_codigo_cliente_legacy"),
    "vat":  lambda p: p.get("vat"),
    "name": lambda p: p.get("name"),
}
# Precedencia de claves duras, de MAS FUERTE a MAS DEBIL (regla 1).
#   ("legacy","code","code")  -> nombre_del_tier, clave_odoo, clave_fuente  (match exacto normalizado)
HARD_KEYS = [
    ("legacy",     "code", "code"),   # código exacto (nolz ambos lados)
    ("vat",        "vat",  "vat"),    # documento fiscal exacto
    ("name_exact", "name", "name"),   # nombre normalizado exacto
]
FUZZY_ODOO_KEY = "name"                 # sobre qué campo Odoo corre el fuzzy
FUZZY_SRC_KEY  = "name"                 # contra qué campo fuente

# Mapeo fuente -> campos Odoo a escribir (para el plan/target). Editá a gusto.
def build_target(src_row: dict) -> dict:
    return {
        "x_studio_codigo_cliente_lemonsuite": src_row.get("name"),
        "x_studio_codigo_cliente_legacy": nolz(src_row.get("code")),
        "x_studio_estado_lemonsuite": "Activo" if str(src_row.get("active")).strip() == "True" else "Inactivo",
        "x_studio_id_interno_lemonsuite": to_int(src_row.get("id")),
        # integer opcional: si viene vacío NO se incluye (no forzar 0)
        **({"x_studio_integration_code_lemonsuite": to_int(src_row.get("integration_code"))}
           if to_int(src_row.get("integration_code")) is not None else {}),
    }
# ========================================================================

_SUF = re.compile(r"\b(s\.?a\.?i\.?c\.?|s\.?a\.?s\.?|s\.?r\.?l\.?|s\.?a\.?|sociedad anonima|sa|srl|saic)\b")

def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = _SUF.sub(" ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()

def nolz(v) -> str:
    s = str(v or "").strip()
    return str(int(s)) if s.isdigit() else s

def to_int(v):
    s = str(v or "").strip()
    return int(s) if s.isdigit() else None

def keyval(kind, raw):
    """Normaliza el valor de una clave segun su tipo."""
    return nolz(raw) if kind in ("code", "vat") else norm(raw)

def toks(n): return {t for t in n.split() if len(t) > 1}

def sim(a, b):
    A, B = toks(a), toks(b)
    if not A or not B: return 0.0
    inter = len(A & B)
    jac = inter / len(A | B)
    contain = inter / min(len(A), len(B))
    contain *= 0.8 if min(len(A), len(B)) == 1 else 0.95
    sm = SequenceMatcher(None, " ".join(sorted(A)), " ".join(sorted(B))).ratio()
    return max(jac, contain, sm)

def load_odoo(path):
    data = json.load(open(path, encoding="utf-8"))
    return data["result"] if isinstance(data, dict) and "result" in data else data

def main():
    src = list(csv.DictReader(open(SOURCE_CSV, encoding="utf-8-sig")))
    odoo = load_odoo(ODOO_JSON)

    # indices de la fuente por cada clave dura
    idx = {name: defaultdict(list) for _, _, name in [(a, b, c) for a, b, c in HARD_KEYS]}
    idx = {tier: defaultdict(list) for tier, _, _ in HARD_KEYS}
    for r in src:
        for tier, _, skey in HARD_KEYS:
            v = keyval(skey, SRC[skey](r))
            if v: idx[tier][v].append(r)
    # indice fuzzy (nombre fuente normalizado)
    src_names = [(norm(SRC[FUZZY_SRC_KEY](r)), r) for r in src]
    tok_idx = defaultdict(list)
    for i, (nn, _) in enumerate(src_names):
        for t in toks(nn): tok_idx[t].append(i)
    common = {t for t, v in tok_idx.items() if len(v) > 60}

    def best_fuzzy(nn):
        cand = set()
        for t in toks(nn):
            if t not in common: cand.update(tok_idx[t])
        best, hit = 0.0, None
        for i in cand:
            s = sim(nn, src_names[i][0])
            if s > best: best, hit = s, src_names[i][1]
        return best, hit

    plan, counts, ambig = [], defaultdict(int), []
    for p in odoo:
        tier, score, hit = None, None, None
        for t, okey, skey in HARD_KEYS:
            v = keyval(skey, ODO[okey](p))
            if not v: continue
            cand = idx[t].get(v)
            if not cand: continue
            if len(cand) == 1: tier, hit = t, cand[0]; break
            ambig.append((p.get("id"), t, v)); # >1 candidato: ambiguo, probar siguiente clave
        if tier is None:
            nn = norm(ODO[FUZZY_ODOO_KEY](p))
            if nn:
                sc, hc = best_fuzzy(nn)
                if hc is not None and sc >= STRONG: tier, hit, score = "fuzzy_strong", hc, round(sc, 3)
                elif hc is not None and sc >= REVIEW: tier, hit, score = "fuzzy_review", hc, round(sc, 3)
        if tier is None: tier = "none"
        counts[tier] += 1
        entry = {"odoo_id": p.get("id"), "odoo_name": p.get("name"),
                 "clave_usada": tier, "score": score}
        if hit is not None:
            entry["source"] = hit
            entry["target"] = build_target(hit)
        plan.append(entry)

    json.dump(plan, open(OUT_PLAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    APPLY = {"legacy", "vat", "name_exact", "fuzzy_strong"}
    print("Conteo por clave_usada:")
    for t, _, _ in HARD_KEYS: print(f"  {t:12s}: {counts.get(t,0)}")
    print(f"  fuzzy_strong: {counts.get('fuzzy_strong',0)}  (aplica; auditar)")
    print(f"  fuzzy_review: {counts.get('fuzzy_review',0)}  (NO aplica; revisar)")
    print(f"  none        : {counts.get('none',0)}")
    print(f"  ambiguos    : {len(ambig)}")
    print(f"Aplicables (fidedignos): {sum(counts[t] for t in APPLY if t in counts)}")
    print(f"-> {OUT_PLAN}")

if __name__ == "__main__":
    main()
