---
name: odoo-data-report
description: >-
  Genera un reporte de comprensión de datos de una instancia Odoo cualquiera (vía el
  MCP odoo-mcp-19): perfila qué campos de un modelo tienen datos reales y clasifica el
  origen de cada uno (USER/CUSTOM = migra, SYSTEM = no migra), con salida en JSON y
  Excel. Úsalo cuando el usuario pida "reporte de campos", "qué campos tienen datos",
  "qué se migra", "profile/coverage de un modelo", "reporte de comprensión" o esté por
  planear una migración de datos (proveedores, clientes, productos, facturas) y necesite
  saber empíricamente qué contiene la instancia. Genérico: funciona para cualquier
  modelo (res.partner, sale.order, product.product, account.move…) y cualquier cliente.
---

# Reporte de comprensión de datos de Odoo

## Qué resuelve

Antes de migrar (o simplemente de entender) una instancia, la pregunta clave es
**"¿qué campos de este modelo tienen datos de verdad, y cuáles migran?"**. El esquema
de Odoo no la responde: un modelo como `res.partner` tiene ~240 campos legibles, pero
en una instancia dada la mayoría están siempre vacíos, y muchos de los que tienen datos
los pone el sistema (no son datos que un usuario cargó). Este skill la responde
**empíricamente**: lee los registros reales y clasifica el origen de cada campo.

Es a la vez un entregable de migración y un **método didáctico**: le muestra al usuario,
en concreto y sobre su propia instancia, qué es dato maestro y qué es ruido del sistema.

## Cuándo dispararlo

- "Generá el reporte de campos de proveedores / clientes / productos."
- "¿Qué campos de `res.partner` tienen datos en esta instancia?"
- "Necesito saber qué se migra de Bejerman / del ERP viejo."
- Al empezar a planear la migración de un modelo nuevo.

## Cómo se usa

Requiere que el MCP `odoo-mcp-19` esté corriendo (Docker levantado, imagen construida) y
registrado en el `.mcp.json` del proyecto — el script descubre el wrapper solo desde ahí.

```bash
# desde el directorio del proyecto cliente (el que tiene .mcp.json apuntando a la instancia):
python /ruta/al/skill/report.py --model res.partner --domain '[["supplier_rank",">",0]]' --out proveedores
```

Necesita `openpyxl` para el `.xlsx` (`pip install openpyxl`); sin él, igual genera el
`.json` y el resumen por consola. Corré el script con un Python que lo tenga (p.ej. un
venv del proyecto). Argumentos:

| flag | default | para qué |
|---|---|---|
| `--model` | `res.partner` | modelo a perfilar |
| `--domain` | `[]` (todos) | dominio Odoo en JSON |
| `--out` | `<modelo>_report` | basename de las salidas |
| `--include-archived` | off | incluye registros archivados (`active_test=False`) |
| `--no-xlsx` | off | solo JSON + consola |
| `--wrapper` | auto | forzar la ruta a `run-docker.sh` |

Dominios útiles para `res.partner`: proveedores `[["supplier_rank",">",0]]`,
clientes `[["customer_rank",">",0]]`, compañías `[["is_company","=",true]]`.

## Pasos que seguís

1. Confirmá el **modelo** y el **dominio** con el usuario (p.ej. proveedores vs. todos
   los partners). Si no lo aclara y el modelo es `res.partner`, ofrecé los presets de
   arriba en vez de perfilar los ~6k partners completos.
2. Verificá que el MCP esté disponible: que Docker esté corriendo y que exista un
   `.mcp.json` en el proyecto. Si Docker está apagado, avisá — es el bloqueo más común.
3. Corré `report.py` con un intérprete que tenga `openpyxl`.
4. **Relatá los hallazgos** (esto es lo didáctico, no solo adjuntar el archivo): cuántos
   registros, cuántos campos tienen datos, el desglose por origen, y sobre todo **la
   lista de campos USER/CUSTOM** — esos son los que migran. Explicá en una línea por qué
   un campo quedó como SYSTEM si el usuario esperaba que migrara. Ver
   [reference/field-origin.md](reference/field-origin.md) para el detalle de la taxonomía.

## Salidas

- `<out>.json` — conteo de registros + por cada campo poblado: etiqueta, tipo, origen,
  registros con dato y % de cobertura. Ideal para versionar y diffear entre corridas.
- `<out>.xlsx` — 3 hojas: **Resumen campos** (todos los campos + origen + cobertura,
  migrables resaltados en verde), **Datos (todos)** (los registros, campos no binarios)
  y **Migracion (USUARIO)** (solo los campos USER/CUSTOM, el subconjunto que migra).

## Advertencias

- El heurístico de "vacío" trata `0`/`0.0`/`False`/`''`/`[]` como sin datos: un `0`
  legítimo (una cantidad en cero) se contaría como campo sin dato. Es un perfil de
  cobertura, no de valores.
- Algunos campos escribibles caen en USER pero son operativamente del sistema
  (`supplier_rank`, `customer_rank`, `active`, `message_*`, relaciones x2many): no son
  dato maestro aunque el origen diga USER. Mencionalo al relatar.
- El MCP capa `search_read` a 1000 registros; el script pagina solo. Para modelos muy
  grandes (facturas, líneas) la corrida puede tardar — avisá y considerá acotar el dominio.
