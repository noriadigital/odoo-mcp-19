"""Cliente REST para Plane (self-hosted) — API v1.

Auth: header `X-API-Key` (Perfil > Personal Access Tokens en tu instancia).
Base URL: configurable (self-hosted) vía PLANE_BASE_URL, p.ej.
`https://plane.tudominio.com`. Los paths siguen el patrón v1:

    {base}/api/v1/workspaces/{slug}/projects/
    {base}/api/v1/workspaces/{slug}/projects/{project_id}/work-items/
    {base}/api/v1/workspaces/{slug}/projects/{project_id}/states/

Rate limit: 60 req/min por API key → backoff en 429.

Se usa solo para el worklog de la migración (crear/actualizar work-items que
registran el avance). Escribir en Plane es una acción hacia afuera: requiere
credenciales y confirmación explícita antes de crear el primer item.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

import requests


class PlaneError(RuntimeError):
    pass


class PlaneClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        workspace_slug: str,
        *,
        timeout: int = 30,
        max_retries: int = 5,
    ) -> None:
        if not (base_url and api_key and workspace_slug):
            raise ValueError("base_url, api_key y workspace_slug son obligatorios")
        self.api_root = f"{base_url.rstrip('/')}/api/v1/workspaces/{workspace_slug}"
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(
            {"X-API-Key": api_key, "Content-Type": "application/json", "Accept": "application/json"}
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.api_root}/{path.lstrip('/')}"
        backoff = 1.0
        for _ in range(self.max_retries):
            resp = self._session.request(method, url, timeout=self.timeout, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after else backoff)
                backoff = min(backoff * 2, 60)
                continue
            if resp.status_code == 401:
                raise PlaneError("401: PLANE_API_KEY inválida.")
            if resp.status_code >= 400:
                raise PlaneError(f"{resp.status_code} en {method} {path}: {resp.text[:300]}")
            return resp
        raise PlaneError(f"Agotados los reintentos en {method} {path}")

    def _paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict]:
        params = dict(params or {})
        while True:
            data = self._request("GET", path, params=params).json()
            # Plane devuelve {results, next_cursor, next_page_results} o una lista.
            if isinstance(data, list):
                yield from data
                return
            yield from data.get("results", [])
            if not data.get("next_page_results"):
                return
            params["cursor"] = data.get("next_cursor")

    # --- Lecturas de apoyo ---
    def list_projects(self) -> list[dict]:
        return list(self._paginate("projects/"))

    def list_states(self, project_id: str) -> list[dict]:
        return list(self._paginate(f"projects/{project_id}/states/"))

    # --- Cycles ---
    def list_cycles(self, project_id: str) -> list[dict]:
        return list(self._paginate(f"projects/{project_id}/cycles/"))

    def create_cycle(
        self,
        project_id: str,
        name: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        description: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"name": name[:255]}
        if start_date:
            payload["start_date"] = start_date
        if end_date:
            payload["end_date"] = end_date
        if description:
            payload["description"] = description
        return self._request("POST", f"projects/{project_id}/cycles/", json=payload).json()

    def add_issues_to_cycle(self, project_id: str, cycle_id: str, issue_ids: list[str]) -> dict:
        return self._request(
            "POST",
            f"projects/{project_id}/cycles/{cycle_id}/cycle-issues/",
            json={"issues": issue_ids},
        ).json()

    # --- Escrituras (worklog) ---
    def create_work_item(
        self,
        project_id: str,
        name: str,
        *,
        description_html: str | None = None,
        state_id: str | None = None,
        priority: str | None = None,
        parent: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"name": name[:255]}
        if description_html:
            payload["description_html"] = description_html
        if state_id:
            payload["state"] = state_id
        if priority:
            payload["priority"] = priority
        if parent:
            payload["parent"] = parent
        return self._request("POST", f"projects/{project_id}/work-items/", json=payload).json()

    def update_work_item(self, project_id: str, item_id: str, **fields: Any) -> dict:
        return self._request(
            "PATCH", f"projects/{project_id}/work-items/{item_id}/", json=fields
        ).json()
