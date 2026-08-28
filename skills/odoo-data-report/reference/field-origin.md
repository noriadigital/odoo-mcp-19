# Taxonomía de origen de campos (el "por qué" del reporte)

Odoo **no guarda proveniencia por registro** — no hay un flag "esto lo cargó un
usuario" vs. "esto lo puso el sistema". Pero sí expone, en el modelo `ir.model.fields`,
*cómo se puebla* cada campo. Eso alcanza para clasificar el origen, que es lo que decide
el alcance de una migración: solo los datos que un humano cargó necesitan viajar del ERP
viejo al nuevo; el resto lo recalcula/regenera Odoo solo.

La clasificación se evalúa **en este orden** (el primero que matchea gana):

| Origen | Condición en `ir.model.fields` | Significado | ¿Migra? |
|---|---|---|---|
| **CUSTOM** | `state == 'manual'` | Campo agregado a mano (los `x_studio_*` de Studio, o cualquier campo custom). Casi siempre es dato maestro que alguien decidió capturar. | ✅ sí |
| **SYSTEM: related** | `related` seteado | Espejo de un campo de otro registro (p.ej. `country_id` traído del `state_id`). No tiene valor propio; se deriva. | ❌ no |
| **SYSTEM: computed** | `compute` seteado, o `store == False` | Lo calcula Odoo a partir de otros datos (totales, saldos, contadores). | ❌ no |
| **SYSTEM: audit** | nombre en `create_uid/create_date/write_uid/write_date/id` | Metadatos del ORM: quién y cuándo creó/modificó el registro. | ❌ no |
| **SYSTEM: readonly** | `readonly == True` | Almacenado y no calculado, pero de solo lectura: lo setea la lógica de negocio, no el usuario (p.ej. estados, secuencias). | ❌ no |
| **USER** | almacenado, escribible, no calculado, no auditoría | Un usuario lo cargó (o lo puede cargar). **Es el dato maestro que migra.** | ✅ sí |

## Gotchas al interpretar

- **`limit=0` obligatorio** al consultar `ir.model.fields`: ese modelo tiene un tope por
  defecto de ~100 filas que trunca *en silencio* (y alfabéticamente), así que sin
  `limit=0` te perdés campos. El script ya lo hace.
- **Escribibles pero operativamente del sistema.** Unos pocos campos quedan en USER pero
  no son dato maestro real: `supplier_rank`/`customer_rank` (los mueve Odoo al facturar),
  `active` (archivado), `message_*` / `activity_*` (mensajería y actividades), y las
  relaciones x2many (se reconstruyen desde el otro lado). Trátalos con criterio.
- **Cobertura ≠ importancia.** Un campo USER con 3% de cobertura igual puede ser
  crítico (p.ej. un CUIT alternativo); la columna de % ordena, no decide.
- **Localización.** En instancias con localización (p.ej. Argentina) los `l10n_*`
  relevantes suelen caer en USER/CUSTOM y son parte del alcance impositivo de la
  migración: revisá `l10n_ar_vat`, `l10n_ar_afip_responsibility_type_id`, etc.

## Por qué es didáctico

Mostrarle al usuario esta tabla *sobre su propia instancia* — "de tus 121 campos con
datos, 40 son USER y migran; estos 81 los pone Odoo solo" — convierte una pregunta
difusa ("¿qué migramos?") en una lista concreta y auditable. Ese es el objetivo: sortear
la deuda de comprensión con evidencia, no con supuestos.
