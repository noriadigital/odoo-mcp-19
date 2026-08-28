"""Worklog de la migración FMDC.

Cada paso relevante (extracción, limpieza, carga a Odoo) se registra:
  1. SIEMPRE en un JSONL local (data/worklog.jsonl) — audit offline, sin deps.
  2. Si Plane está habilitado (PLANE_ENABLED=true + credenciales), además crea
     un work-item en el proyecto FMDC de Plane.

Push a Plane = acción hacia afuera → apagado por defecto. Se activa con
PLANE_ENABLED=true una vez cargadas las credenciales en .env y con OK explícito.

Uso programático:
    from worklog import WorkLog
    wl = WorkLog()
    wl.log("extract", "clients", detail="342 registros", done=True)

Uso CLI (registro manual de un hito):
    python worklog.py "extract" "clients" "342 registros"
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL_LOG = ROOT / "data" / "worklog.jsonl"


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class WorkLog:
    def __init__(self) -> None:
        _load_env()
        self._plane = None
        self._project_id = os.environ.get("PLANE_PROJECT_ID", "")
        self._done_state_id = os.environ.get("PLANE_DONE_STATE_ID", "")
        self._cycle_id = os.environ.get("PLANE_CYCLE_ID", "")
        if os.environ.get("PLANE_ENABLED", "").lower() == "true":
            self._init_plane()

    def _init_plane(self) -> None:
        from connectors.plane_client import PlaneClient

        base = os.environ.get("PLANE_BASE_URL", "")
        key = os.environ.get("PLANE_API_KEY", "")
        slug = os.environ.get("PLANE_WORKSPACE_SLUG", "")
        if not (base and key and slug and self._project_id):
            print("  ! PLANE_ENABLED=true pero faltan credenciales → worklog local-only")
            return
        self._plane = PlaneClient(base, key, slug)

    def log(self, phase: str, item: str, *, detail: str = "", done: bool = True) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "item": item,
            "detail": detail,
            "done": done,
        }
        LOCAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOCAL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

        if self._plane and self._project_id:
            check = "✓" if done else "…"
            name = f"[{phase}] {item} {check}"
            desc = f"<p>{detail}</p>" if detail else None
            state = self._done_state_id if done else None
            try:
                item = self._plane.create_work_item(
                    self._project_id, name, description_html=desc, state_id=state
                )
                if self._cycle_id and item.get("id"):
                    self._plane.add_issues_to_cycle(
                        self._project_id, self._cycle_id, [item["id"]]
                    )
            except Exception as exc:  # noqa: BLE001 — el worklog no debe romper la migración
                print(f"  ! Plane no registró '{name}': {exc}")

        print(f"  · worklog: [{phase}] {item} {detail}".rstrip())


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit('Uso: python worklog.py <phase> <item> [detail]')
    WorkLog().log(sys.argv[1], sys.argv[2], detail=sys.argv[3] if len(sys.argv) > 3 else "")
