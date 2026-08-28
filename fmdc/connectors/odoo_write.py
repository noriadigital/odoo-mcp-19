"""Cliente Odoo JSON-2 de escritura para el ETL de migración.

Reusa ODOO_* del .env raíz (igual que odoo_read). Permite create/write además
de lectura. GUARD anti-prod: se niega a operar contra fmdclegal.odoo.com
(producción). Solo debe correr contra staging (fmdclegal-ultpruebas...).

Idempotencia: es responsabilidad del script que lo use (buscar antes de crear).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROD_HOST = "fmdclegal.odoo.com"


def _load_repo_env() -> None:
    env = _REPO_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class OdooWrite:
    def __init__(self, timeout: int = 60) -> None:
        _load_repo_env()
        url = os.environ.get("ODOO_URL", "")
        db = os.environ.get("ODOO_DB", "")
        key = os.environ.get("ODOO_API_KEY", "")
        if not (url and key):
            raise ValueError("Faltan ODOO_URL / ODOO_API_KEY")
        if not url.startswith("http"):
            url = f"https://{url}"
        self.url = url.rstrip("/")
        host = self.url.split("://")[-1].split("/")[0].lower()
        if host == _PROD_HOST:
            raise PermissionError(
                f"GUARD: {host} es PRODUCCIÓN. OdooWrite solo opera contra staging. Abortado."
            )
        self.host = host
        self.timeout = timeout
        self._s = requests.Session()
        self._s.headers["Content-Type"] = "application/json"
        self._s.headers["Authorization"] = f"Bearer {key}"
        if db and not (host.endswith(".odoo.com") or host == "odoo.com"):
            self._s.headers["X-Odoo-Database"] = db

    def _call(self, model: str, method: str, **kwargs: Any) -> Any:
        r = self._s.post(f"{self.url}/json/2/{model}/{method}", json=kwargs, timeout=self.timeout)
        if r.status_code >= 400:
            raise ValueError(f"{r.status_code} {model}.{method}: {r.text[:400]}")
        return r.json()

    def search_read(self, model: str, domain: list, fields: list[str], limit: int | None = None) -> list[dict]:
        kw: dict[str, Any] = {"domain": domain, "fields": fields}
        if limit is not None:
            kw["limit"] = limit
        return self._call(model, "search_read", **kw)

    def name_search(self, model: str, name: str, limit: int = 8) -> list:
        return self._call(model, "name_search", name=name, limit=limit)

    def create(self, model: str, vals: dict) -> int:
        res = self._call(model, "create", vals_list=[vals])
        # create devuelve lista de ids (o un id según versión)
        return res[0] if isinstance(res, list) else res

    def write(self, model: str, ids: list[int], vals: dict) -> bool:
        return self._call(model, "write", ids=ids, vals=vals)
