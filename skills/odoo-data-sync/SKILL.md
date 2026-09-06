---
name: odoo-data-sync
description: >-
  Concilia / sincroniza datos de una fuente externa (un CSV, otra app, un export de otro
  sistema) contra un modelo de Odoo (vía el MCP odoo-mcp-19), emparejando cada registro
  por CLAVE — de la más fuerte a la más débil — y actualizando solo los casos fidedignos.
  Usa fuzzy matching con umbrales claros y MARCA en el reporte qué clave se usó en cada
  actualización. Salida: plan de sync + CSVs de auditoría (aplicados / a-revisar / sin-par)
  + reporte .ipynb legible. Úsalo cuando pidan "sincronizar/conciliar datos con Odoo",
  "cruzar una fuente externa contra Odoo", "actualizar campos desde otro sistema",
  "matchear clientes/proveedores/productos por código o nombre", "crosswalk", "traer los
  datos de X a Odoo por clave", o antes de una migración que ACTUALIZA (no crea) registros
  existentes. Genérico: cualquier modelo (res.partner, product.template, account.move…) y
  cualquier fuente. Distinto de odoo-data-cleaning (que detecta duplicados/faltantes): este
  ESCRIBE actualizaciones emparejando contra una fuente externa.
---

# Sincronización / conciliación de datos hacia Odoo por clave

## Qué resuelve

Tenés una **fuente externa** (CSV de otro sistema, export de otra app, planilla) y querés
volcar sus datos a los registros que **ya existen** en Odoo — no crear, **actualizar**. La
pregunta es *"¿qué registro de Odoo corresponde a cada registro de la fuente, y qué tan
confiable es ese emparejamiento?"*. Este skill lo resuelve de forma **auditable**:

1. Empareja por **clave, de la más fuerte a la más débil** (ver reglas abajo).
2. **Marca qué clave se usó** en cada actualización (columna `clave_usada` en todos los reportes).
3. Usa **fuzzy matching con umbrales explícitos** y separa lo que se aplica de lo que queda a revisar.
4. Escribe en Odoo **solo los casos fidedignos**; el resto queda en CSV para decisión humana.

Entregables: `sync_applied.csv` (lo escrito, con la clave por registro), `sync_fuzzy_audit.csv`
(fuzzy aplicados y no), `sync_unmatched.csv` (sin par), y un `sync_report.ipynb` legible sin kernel.

## Las 3 reglas (no negociables)

### 1. Siempre la clave más fuerte primero, cayendo a la más débil

Definí un **orden de precedencia de claves** y asigná cada registro con la primera que
resuelva **de forma unívoca** (1 solo candidato). Orden típico, de más fuerte a más débil:

| # | Clave | Por qué es más/menos fuerte |
|---|-------|------------------------------|
| 1 | **ID externo / código de negocio** (ej. `code`, `ref`, `barcode`, un legacy code) | Identificador estable y único. Máxima confianza. |
| 2 | **Documento fiscal** (CUIT/VAT, DNI) | Único por entidad legal, pero puede faltar o repetirse (extranjeros). |
| 3 | **Nombre exacto normalizado** (minúsculas, sin acentos, sin sufijos SA/SRL) | Determinístico pero el mismo nombre puede repetirse. |
| 4 | **Fuzzy fuerte** (similitud ≥ 0.90) | Inferido; auditar. |
| 5 | **Fuzzy a revisar** (0.72 ≤ sim < 0.90) | Zona gris; **no** auto-aplicar. |

- **Nunca** uses una clave más débil si una más fuerte ya emparejó.
- Si una clave da **>1 candidato** (ambiguo), no la uses para esa fila: registrala como
  `ambiguous_<clave>` y pasá a la siguiente clave (o dejala para revisión).
- La clave más fuerte disponible **depende de los datos** — inspeccioná primero el esquema
  (`odoo://model/{model}/quick-schema`) y las columnas de la fuente antes de fijar el orden.

### 2. Marcar SIEMPRE qué clave se usó

Cada fila de cada salida lleva una columna **`clave_usada`** (`legacy` / `vat` / `name_exact`
/ `fuzzy_strong` / `fuzzy_review` / `none`) y, para fuzzy, el **`score`**. Esto hace la sync
**auditable y reversible**: se puede revisar (o revertir) selectivamente lo inferido sin
tocar lo emparejado por clave dura. El reporte agrupa los conteos por clave.

### 3. Fuzzy matching con umbrales CLAROS

- Dos umbrales fijos y visibles: **STRONG = 0.90** (aplica, pero se audita) y
  **REVIEW = 0.72** (no aplica; va a CSV). Por debajo de REVIEW → `none`.
- Similitud = `max(jaccard_tokens, contención, ratio_char_ordenado)` sobre nombres
  **normalizados** (ver `reference/metodologia.md`). Blocking por token invertido para no
  comparar todos contra todos.
- Un solo token distintivo compartido es **riesgoso** → penalizarlo (nunca cae en STRONG solo por eso).
- Reportá SIEMPRE ejemplos de `fuzzy_strong` para que el humano detecte falsos positivos
  (ej. *"EL AMANECER"* vs *"LOS AMANECERES"*): pasan el umbral pero son entidades distintas.

## El input del usuario

El usuario dice **qué fuente** volcar y **a qué modelo**. Traducilo a:
- `--model` de Odoo y su `--domain` (ver mapa en odoo-data-cleaning).
- El **archivo fuente** y el mapeo **columna fuente → campo Odoo**.
- El **orden de claves** (regla 1) según qué columnas comparten fuente y Odoo.

Si hay ambigüedad en el modelo, el dominio o el orden de claves, **confirmá antes de escribir**.

## Flujo

1. **Verificá la instancia y los campos destino ANTES de escribir.**
   - Confirmá a qué Odoo apunta el MCP (`ir.config_parameter` `web.base.url`; y que el `.env`
     no haya cambiado sin reiniciar el MCP — el cliente lee env al arrancar).
   - Confirmá que **todos** los campos destino existan y su **tipo** (`ir.model.fields` o
     `fields_get`): un integer no acepta string; un selection exige el valor exacto.
2. **Traé el estado actual** del modelo (los campos clave + destino) y la fuente.
3. **Construí el plan** con `match.py` (precedencia de claves + fuzzy + `clave_usada` por fila).
4. **Mostrá el plan** (conteos por clave, ejemplos fuzzy) y **confirmá el alcance** con el
   usuario (¿incluir `fuzzy_strong`?). Los `fuzzy_review` **no** se escriben nunca sin OK.
5. **Escribí solo lo fidedigno**, vía el MCP:
   - Preferí `batch_execute` con `atomic=false`, en writes de **1 registro** (no gatean el
     safety gate; los multi-registro sí). Aplaná grupos (N registros con los mismos valores)
     a N writes de 1.
   - `res.partner` y la mayoría de modelos permiten `write`; recordá que hay
     **BLOCKED_MODELS** (ver CLAUDE.md) que nunca se tocan.
6. **Verificá** (`search_count` sobre el campo recién escrito = nº aplicado) y **generá los
   entregables** (CSVs + ipynb) con la columna `clave_usada` y la lista de fuzzy a auditar.

## Reglas de oro

- **No inventes emparejamientos.** Si ninguna clave resuelve, es `none` — no forces un fuzzy.
- **Producción manda cautela.** Antes de escribir en una instancia real, mostrá el plan y
  confirmá alcance. Los campos de metadata son reversibles; los de estado/contables **no**.
- **La clave usada va en todos lados.** Sin `clave_usada` el reporte no sirve para auditar.
- **Umbrales explícitos y citados** en el reporte (STRONG/REVIEW), nunca "mágicos".

Ver `reference/metodologia.md` para la normalización, la fórmula de similitud, y el detalle
del blocking. `match.py` es el motor reutilizable (configurable arriba).
