# FMDC — Migración LemonSuite → Odoo 19

Engagement FMDC dentro de `odoo-mcp-19` (branch `fmdc-odoomcp19`). Limpieza y
migración del time-billing desde **LemonSuite (TimeBillingX v3)** hacia
**Odoo 19** (`fmdclegal.odoo.com`).

Origen: API REST v3 (bearer, JSON, paginación). Destino: Odoo 19 vía el MCP
`odoo-mcp-19` (JSON-2) para maestros; ETL directo para alto volumen/financiero.
Avance registrado en **Plane self-hosted** (worklog).

> ⚠️ Este repo es un **fork con `upstream`**. `fmdc/.env` y `fmdc/data/` están
> gitignoreados en la raíz y acá. **Nunca** commitear PII (CUIT, emails) ni tokens.

## Estructura

```
fmdc/
├── connectors/
│   ├── lemonsuite_client.py   # v3, bearer, paginación, backoff 429 (solo GET)
│   └── plane_client.py        # Plane self-hosted, X-API-Key, work-items
├── endpoints.py               # registro de colecciones LemonSuite
├── extract.py                 # Fase 0: extracción → data/raw/*.json
├── worklog.py                 # registro de avance (JSONL local + Plane opcional)
└── data/                      # gitignored (raw/, clean/, worklog.jsonl)
```

## Fases

0. **Extracción + profiling** ← *estamos acá*. Volcar colecciones a `data/raw/` y medir cobertura.
1. **Limpieza** (dedup por CUIT/email/nombre, faltantes) → `data/clean/`.
2. **Mapeo** LemonSuite → Odoo (doc de campos + reglas de transformación).
3. **Carga** idempotente a Odoo **staging** primero, con crosswalk id↔id.

Alcance de datos: **se define tras el profiling**.

## Uso — Fase 0

```bash
cd fmdc
pip install -r requirements.txt        # requests (venv opcional; ya está en el sistema)
cp .env.example .env                    # completar LEMONSUITE_TENANT y LEMONSUITE_TOKEN

python extract.py                       # extrae todo → data/raw/
python extract.py clients projects      # solo algunas colecciones
```

`data/raw/_manifest.json` queda con los conteos por colección.

## Worklog (Plane)

Local siempre; push a Plane apagado por defecto (`PLANE_ENABLED=false`). Para
activarlo: completar credenciales `PLANE_*` en `.env` y poner `PLANE_ENABLED=true`.

```bash
python worklog.py extract clients "342 registros"   # hito manual
```

## Notas del origen (de openapi.yml)

- `/time_entries` **no acepta filtros** → full scan paginado (mayor volumen).
- `duration` en **minutos** (float) → Odoo timesheets en **horas** (÷60).
- `legal_entities` y `contacts` están **anidados** bajo `/clients/{id}/...`.
- `billing_documents.external_id` = clave de idempotencia (↔ XML-ID de Odoo).
- Facturas legales con CAE (AFIP): se importan como histórico posteado, sin re-emitir.
