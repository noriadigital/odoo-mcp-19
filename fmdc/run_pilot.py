"""Pilot de migración LemonSuite → Odoo STAGING (end-to-end acotado).

Por cada liquidación LemonSuite del set PILOT:
  1. Resuelve/crea el CLIENTE (res.partner) — reusa match del crosswalk o crea nuevo
     seteando x_studio_codigo_cliente_lemonsuite = code (sin ceros a la izq).
  2. Crea/reusa los PROYECTOS (project.project) del cliente.
  3. Mapea usuario LS → hr.employee (por email; crea si falta) e importa los
     TIMESHEETS (account.analytic.line, minutos→horas).

Idempotente (busca antes de crear) y defensivo (captura errores por registro).
Escribe data/clean/pilot_result.json con el detalle para el informe/Plane.

Uso:  python run_pilot.py            # set por defecto
      python run_pilot.py 392 379    # invoice ids específicos
"""

from __future__ import annotations

import json
import os
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from connectors.lemonsuite_client import LemonSuiteClient
from connectors.odoo_write import OdooWrite
from worklog import _load_env

PILOT_DEFAULT = [392, 379]  # Familia Aberastury (studio-match) + CSH (nuevo)
ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


def main() -> None:
    _load_env()
    invoice_ids = [int(a) for a in sys.argv[1:]] or PILOT_DEFAULT
    cli = LemonSuiteClient(os.environ["LEMONSUITE_TENANT"], os.environ["LEMONSUITE_TOKEN"])
    ow = OdooWrite()
    print(f"target Odoo: {ow.host}  (guard anti-prod OK)")

    ls_clients = {c["id"]: c for c in json.loads((RAW / "clients.json").read_text())}
    ls_projects: dict[int, list] = {}
    for p in json.loads((RAW / "projects.json").read_text()):
        ls_projects.setdefault((p.get("client") or {}).get("id"), []).append(p)

    emp_cache: dict[str, int] = {}

    def resolve_employee(user: dict) -> tuple[int, str]:
        email = (user.get("email") or "").lower()
        name = user.get("name") or "Sin nombre"
        if email and email in emp_cache:
            return emp_cache[email], "cache"
        if email:
            found = ow.search_read("hr.employee", [["work_email", "=ilike", email]], ["id"], limit=1)
            if found:
                emp_cache[email] = found[0]["id"]
                return found[0]["id"], "matched"
        eid = ow.create("hr.employee", {"name": name, **({"work_email": email} if email else {})})
        if email:
            emp_cache[email] = eid
        return eid, "created"

    report: dict = {"target": ow.host, "invoices": [], "totals": {
        "partners_created": 0, "partners_reused": 0, "projects_created": 0,
        "projects_reused": 0, "employees_created": 0, "timesheets_created": 0,
        "timesheets_skipped": 0, "errors": 0}}
    T = report["totals"]

    for inv_id in invoice_ids:
        entry: dict = {"invoice_id": inv_id, "steps": [], "errors": []}
        try:
            inv = cli.get_one(f"invoices/{inv_id}")
            tes = cli.collect(f"invoices/{inv_id}/time_entries")
            lsc = inv.get("client") or {}
            clid = lsc.get("id")
            lsclient = ls_clients.get(clid, {})
            code = str(lsclient.get("code") or "")
            code_nolz = str(int(code)) if code.isdigit() else code
            entry["client"] = {"ls_id": clid, "name": lsc.get("name"), "code": code_nolz}

            # 1) PARTNER
            pid = None
            hit = ow.search_read("res.partner",
                                 [["x_studio_codigo_cliente_lemonsuite", "=", code_nolz]], ["id", "name"], limit=1)
            if hit:
                pid = hit[0]["id"]; entry["steps"].append(f"partner reusado por Studio-code #{pid}"); T["partners_reused"] += 1
            else:
                ns = ow.name_search("res.partner", lsc.get("name") or "")
                exact = [i for (i, label) in ns if norm(label).startswith(norm(lsc.get("name")))]
                if exact:
                    pid = exact[0]; entry["steps"].append(f"partner reusado por nombre #{pid} (revisar: posible match)"); T["partners_reused"] += 1
                else:
                    pid = ow.create("res.partner", {
                        "name": lsc.get("name"), "customer_rank": 1,
                        "x_studio_codigo_cliente_lemonsuite": code_nolz})
                    entry["steps"].append(f"partner CREADO #{pid} (code {code_nolz})"); T["partners_created"] += 1
            entry["partner_id"] = pid

            # 2) PROYECTOS (los de la liquidación)
            proj_map: dict[int, int] = {}  # ls_project_id -> odoo project id
            for lp in (inv.get("projects") or []):
                pname = lp.get("name") or f"Proyecto LS {lp.get('id')}"
                ex = ow.search_read("project.project",
                                    [["partner_id", "=", pid], ["name", "=", pname]], ["id"], limit=1)
                if ex:
                    proj_map[lp["id"]] = ex[0]["id"]; entry["steps"].append(f"proyecto reusado '{pname}' #{ex[0]['id']}"); T["projects_reused"] += 1
                else:
                    prid = ow.create("project.project", {"name": pname, "partner_id": pid})
                    proj_map[lp["id"]] = prid; entry["steps"].append(f"proyecto CREADO '{pname}' #{prid}"); T["projects_created"] += 1

            # 3) TIMESHEETS
            for te in tes:
                try:
                    lp = te.get("project") or {}
                    prid = proj_map.get(lp.get("id"))
                    if not prid:  # timesheet de un proyecto no incluido en inv.projects → crearlo
                        pname = lp.get("name") or f"Proyecto LS {lp.get('id')}"
                        ex = ow.search_read("project.project", [["partner_id", "=", pid], ["name", "=", pname]], ["id"], limit=1)
                        prid = ex[0]["id"] if ex else ow.create("project.project", {"name": pname, "partner_id": pid})
                        proj_map[lp.get("id")] = prid
                    eid, how = resolve_employee(te.get("user") or {})
                    if how == "created":
                        T["employees_created"] += 1
                    hours = round((te.get("duration") or 0) / 60.0, 2)
                    date = te.get("date")
                    desc = te.get("description") or "/"
                    dup = ow.search_read("account.analytic.line",
                        [["project_id", "=", prid], ["employee_id", "=", eid], ["date", "=", date],
                         ["unit_amount", "=", hours], ["name", "=", desc]], ["id"], limit=1)
                    if dup:
                        T["timesheets_skipped"] += 1; continue
                    ow.create("account.analytic.line", {
                        "project_id": prid, "employee_id": eid, "date": date,
                        "unit_amount": hours, "name": desc})
                    T["timesheets_created"] += 1
                except Exception as exc:  # noqa: BLE001
                    entry["errors"].append(f"timesheet: {exc}"); T["errors"] += 1
        except Exception as exc:  # noqa: BLE001
            entry["errors"].append(f"invoice {inv_id}: {exc}"); T["errors"] += 1
        report["invoices"].append(entry)
        print(f"\n== invoice {inv_id} ==")
        for s in entry["steps"]:
            print("  ✓", s)
        for e in entry["errors"]:
            print("  ✗", e)

    (ROOT / "data" / "clean").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "clean" / "pilot_result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("\n=== TOTALES ===")
    for k, v in T.items():
        print(f"  {k:22s} {v}")


if __name__ == "__main__":
    main()
