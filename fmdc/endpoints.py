"""Registro de las colecciones de LemonSuite a extraer.

`TOP_LEVEL` son endpoints de lista planos que se paginan directo.
`PER_CLIENT` son colecciones anidadas bajo /clients/{id}/... que se recorren
por cada cliente extraído.

Fuente: openapi.yml (API v3). Marcados con volumen esperado para priorizar
y para dimensionar el full-scan de time_entries.
"""

# nombre_archivo -> path de la API
TOP_LEVEL: dict[str, str] = {
    # --- Maestros ---
    "clients": "/clients",
    "holdings": "/holdings",
    "contacts": "/contacts",
    "projects": "/projects",
    "project_areas": "/project_areas",
    "project_categories": "/project_categories",
    "users": "/users",
    "work_teams": "/work_teams",
    "requesters": "/requesters",
    "roles": "/roles",
    "user_categories": "/user_categories",
    "activities": "/activities/",  # ojo: trailing slash en el spec
    # --- Alto volumen ---
    "time_entries": "/time_entries",  # sin filtros → full scan
    # --- Financiero / operativo ---
    "expenses": "/expenses",
    "expense_categories": "/expense_categories",
    "invoices": "/invoices",  # liquidaciones
    "billing_documents": "/billing_documents",
    "billing_document_types": "/billing_document_types",
    "payments": "/payments",
    # --- Referencia / config ---
    "bank_accounts": "/bank_accounts",
    "payment_methods": "/payment_methods",
    "currencies": "/currencies",
    "fees": "/fees",
    "user_category_rates": "/user_category_rates",
    "user_rates": "/user_rates",
}

# nombre_archivo -> plantilla de path (usa {id} del cliente)
PER_CLIENT: dict[str, str] = {
    "legal_entities": "/clients/{id}/legal_entities",
    "client_contacts": "/clients/{id}/contacts",
}
