"""Parsea las planillas de Drive (guardadas por el MCP) a CSV limpios y cruza
usuarios LemonSuite ↔ empleados. One-off del engagement FMDC.

Maneja tablas markdown (| ) y bloques de código (``` csv ```), clasificando por
título de sección (Proveedores / Empleados / Clientes).
"""
import csv
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TR = Path.home() / ".claude/projects/-home-mph-odoo-mcp-19"
# archivos guardados por read_file_content (los 2 más recientes de esta sesión)
saved = sorted(glob.glob(str(TR / "**/tool-results/mcp-claude_ai_Google_Drive-read_file_content-*.txt"), recursive=True))


def load(path):
    return json.load(open(path))["fileContent"]


def parse_blocks(txt):
    """Devuelve lista de (titulo, filas) para tablas markdown y bloques ```csv```."""
    out = []
    title = None
    lines = txt.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        low = s.lower()
        if s.startswith("```"):  # bloque de código CSV
            j = i + 1
            rows = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                if lines[j].strip():
                    rows.append(next(csv.reader([lines[j]])))
                j += 1
            if rows:
                out.append((title, rows))
            i = j + 1
            continue
        if s.startswith("|"):  # tabla markdown
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip().replace("\\", "") for c in lines[i].strip().strip("|").split("|")]
                if not set("".join(cells)) <= set(": -"):
                    rows.append(cells)
                i += 1
            if rows:
                out.append((title, rows))
            continue
        if s and not s.startswith("|"):
            if any(k in low for k in ("proveedor", "empleado", "cliente")) and len(s) < 60:
                title = s
        i += 1
    return out


def classify(title, header):
    t = (title or "").lower()
    h = " ".join(header).lower()
    if "apellido" in h or "empleado" in t:
        return "empleados"
    if "proveedor" in t:
        return "proveedores"
    if "cliente" in t:
        return "clientes"
    return "otros"


def main():
    # File1 = el que tiene secciones Proveedores/Empleados/Clientes
    buckets = {}
    for path in saved:
        for title, rows in parse_blocks(load(path)):
            hdr, data = rows[0], [r for r in rows[1:] if any(r)]
            if not data:
                continue
            kind = classify(title, hdr)
            if kind in ("empleados", "proveedores", "clientes"):
                buckets.setdefault(kind, (hdr, []))
                buckets[kind][1].extend(data)

    (ROOT / "data" / "external").mkdir(parents=True, exist_ok=True)
    emp = []
    for kind, (hdr, data) in buckets.items():
        with (ROOT / "data" / "external" / f"{kind}.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(hdr)
            w.writerows(data)
        print(f"  {kind}: {len(data)} filas · cols={hdr[:6]}")
        if kind == "empleados":
            emp = [dict(zip(hdr, r)) for r in data]

    # cruce usuarios LS ↔ empleados por email
    users = json.loads((ROOT / "data" / "raw" / "users.json").read_text())
    emp_email = {}
    for e in emp:
        for k, v in e.items():
            if "mail" in k.lower() and v and "@" in v:
                emp_email[v.lower().strip()] = e
    matched = [u for u in users if (u.get("email") or "").lower().strip() in emp_email]
    print(f"\nusuarios LS: {len(users)} · empleados: {len(emp)} · emails empleados: {len(emp_email)}")
    print(f"usuarios LS con empleado (por email): {len(matched)}/{len(users)}")
    print("sin match:", [u.get("email") for u in users if u not in matched])


if __name__ == "__main__":
    main()
