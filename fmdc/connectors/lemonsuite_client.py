"""Cliente HTTP mínimo para la API v3 de LemonSuite (TimeBillingX).

- Auth: Bearer token en el header Authorization.
- Base URL: https://{tenant}.timebillingapp.com/api/v3
- Paginación: query params page/per_page (per_page máx 1000), headers
  total_pages / next_page en la respuesta.
- Rate limiting: la API responde 429; se reintenta con backoff exponencial
  respetando Retry-After cuando está presente.

Es un lector puro: solo hace GET. La extracción no debe mutar el origen.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

import requests

MAX_PER_PAGE = 1000


class LemonSuiteError(RuntimeError):
    """Error no recuperable al hablar con la API de LemonSuite."""


class LemonSuiteClient:
    def __init__(
        self,
        tenant: str,
        token: str,
        *,
        timeout: int = 60,
        max_retries: int = 5,
        language: str = "es",
    ) -> None:
        if not tenant or not token:
            raise ValueError("tenant y token son obligatorios")
        # Aceptar tenant "pelado" (fmdclegal) o una URL completa
        # (https://fmdclegal.lemonsuiteapp.com) → nos quedamos con el subdominio.
        # La API v3 vive en timebillingapp.com aunque la app esté en lemonsuiteapp.com.
        if "://" in tenant or "." in tenant:
            tenant = tenant.split("://")[-1].split("/")[0].split(".")[0]
        self.tenant = tenant
        self.base_url = f"https://{tenant}.timebillingapp.com/api/v3"
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "X-Language": language,
            }
        )

    def _request(self, path: str, params: dict[str, Any] | None = None) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        backoff = 1.0
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:  # network hiccup → retry
                last_exc = exc
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else backoff
                time.sleep(wait)
                backoff = min(backoff * 2, 30)
                last_exc = LemonSuiteError(f"{resp.status_code} en {path}")
                continue

            if resp.status_code == 401:
                raise LemonSuiteError(
                    "401 Unauthorized: token inválido o expirado (revisá LEMONSUITE_TOKEN)."
                )
            if resp.status_code >= 400:
                raise LemonSuiteError(f"{resp.status_code} en {path}: {resp.text[:300]}")
            return resp

        raise LemonSuiteError(f"Agotados los reintentos en {path}: {last_exc}")

    def get_one(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET de un recurso único (no colección)."""
        return self._request(path, params).json()

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, per_page: int = MAX_PER_PAGE
    ) -> Iterator[dict[str, Any]]:
        """Itera todos los elementos de una colección paginada."""
        params = dict(params or {})
        params["per_page"] = min(per_page, MAX_PER_PAGE)
        page = 1
        while True:
            params["page"] = page
            resp = self._request(path, params)
            items = resp.json()
            if not isinstance(items, list):
                # Algunos endpoints devuelven un objeto, no una lista.
                yield items
                return
            yield from items
            # La última página se detecta de forma robusta por tamaño;
            # el header next_page sirve de atajo cuando está disponible.
            if len(items) < params["per_page"]:
                return
            next_page = resp.headers.get("next_page")
            if next_page and next_page not in ("", "null"):
                page = int(next_page)
            else:
                page += 1

    def collect(
        self, path: str, params: dict[str, Any] | None = None, per_page: int = MAX_PER_PAGE
    ) -> list[dict[str, Any]]:
        return list(self.paginate(path, params=params, per_page=per_page))
