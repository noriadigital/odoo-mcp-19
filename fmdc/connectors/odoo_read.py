"""Cliente Odoo JSON-2 de SOLO LECTURA para la fase de comparación.

Reusa las credenciales del MCP (`.env` en la raíz del repo: ODOO_URL/ODOO_DB/
ODOO_API_KEY). Habla el mismo contrato v2 que src/odoo_mcp/odoo_client.py:
POST {url}/json/2/{model}/{method}, Bearer, named args, respuesta sin envelope.
En SaaS (*.odoo.com) NO se manda X-Odoo-Database (la DB va por subdominio).

Guardarraíl: solo permite métodos de lectura. Cualquier otro método lanza error
→ imposible mutar prod desde acá por accidente.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

_READ_ONLY = {"search_read", "search_count", "read", "search", "fields_get", "name_search", "read_group", "formatted_read_group"}
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_repo_env() -> None:
    env = _REPO_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class OdooRead:
    def __init__(self, timeout: int = 60) -> None:
        _load_repo_env()
        url = os.environ.get("ODOO_URL", "")
        db = os.environ.get("ODOO_DB", "")
        key = os.environ.get("ODOO_API_KEY", "")
        if not (url and key):
            raise ValueError("Faltan ODOO_URL / ODOO_API_KEY en el .env de la raíz del repo")
        if not url.startswith("http"):
            url = f"https://{url}"
        self.url = url.rstrip("/")
        self.timeout = timeout
        self._s = requests.Session()
        self._s.headers["Content-Type"] = "application/json"
        self._s.headers["Authorization"] = f"Bearer {key}"
        host = self.url.split("://")[-1].split("/")[0].lower()
        if db and not (host.endswith(".odoo.com") or host == "odoo.com"):
            self._s.headers["X-Odoo-Database"] = db

    def _call(self, model: str, method: str, **kwargs: Any) -> Any:
        if method not in _READ_ONLY:
            raise PermissionError(f"OdooRead es solo-lectura; '{method}' no está permitido")
        r = self._s.post(f"{self.url}/json/2/{model}/{method}", json=kwargs, timeout=self.timeout)
        if r.status_code >= 400:
            raise ValueError(f"{r.status_code} {model}.{method}: {r.text[:300]}")
        return r.json()

    def search_count(self, model: str, domain: list) -> int:
        return self._call(model, "search_count", domain=domain)

    def search_read(
        self, model: str, domain: list, fields: list[str], *, limit: int | None = None, offset: int = 0
    ) -> list[dict]:
        kw: dict[str, Any] = {"domain": domain, "fields": fields, "offset": offset}
        if limit is not None:
            kw["limit"] = limit
        return self._call(model, "search_read", **kw)

    def search_read_all(
        self, model: str, domain: list, fields: list[str], *, page: int = 1000
    ) -> list[dict]:
        """Pagina hasta traer todos los registros."""
        out: list[dict] = []
        offset = 0
        while True:
            batch = self.search_read(model, domain, fields, limit=page, offset=offset)
            out.extend(batch)
            if len(batch) < page:
                return out
            offset += page
