# Metodología — matching por clave + fuzzy

## Normalización de nombres (`norm`)

Para comparar nombres se normaliza antes de indexar/comparar:

1. Unicode NFKD → ASCII (saca acentos: `Neuquén` → `neuquen`).
2. Minúsculas.
3. Saca sufijos societarios: `s.a.`, `s.r.l.`, `s.a.i.c.`, `s.a.s.`, `sociedad anonima`,
   `sa`, `srl`, `saic` (como palabras completas).
4. Deja solo `[a-z0-9 ]`, colapsa espacios.

`norm("AGROPECUARIA EL AMANECER SRL")` → `agropecuaria el amanecer`.

## Normalización de códigos (`nolz`)

Los códigos suelen venir con ceros a la izquierda en una fuente y sin ellos en Odoo.
`nolz("000221") == nolz("221") == "221"`. Si no es numérico, se deja tal cual.
**Regla:** compará SIEMPRE códigos con `nolz` de ambos lados.

## Similitud (`sim`) — entre 0 y 1

Sobre nombres normalizados, tokenizados (tokens de largo > 1):

```
A, B = tokens(a), tokens(b)
jaccard   = |A ∩ B| / |A ∪ B|
contain   = |A ∩ B| / min(|A|, |B|)        # capta "Blue Star" ⊂ "Blue Star Group"
            × 0.8  si min(|A|,|B|)==1        # un solo token distintivo = riesgoso
            × 0.95 en caso contrario
seqmatch  = SequenceMatcher(sorted(A), sorted(B)).ratio()   # typos y orden invertido
sim       = max(jaccard, contain, seqmatch)
```

Tomar el `max` capta distintos tipos de parecido (subconjunto, typo, orden). La penalización
del token único evita que *"SP ARGENTINA"* matchee fuerte contra cualquier *"… ARGENTINA"*.

## Umbrales

| Constante | Valor | Efecto |
|-----------|-------|--------|
| `STRONG`  | 0.90  | `sim ≥ 0.90` → `fuzzy_strong`: se aplica, pero se audita. |
| `REVIEW`  | 0.72  | `0.72 ≤ sim < 0.90` → `fuzzy_review`: **no** se aplica, va a CSV. |
| (resto)   | <0.72 | `none`. |

Ajustables por dataset, pero **siempre explícitos en el reporte**. Subir STRONG = menos
falsos positivos, más a revisión. Bajar REVIEW = más candidatos a mano.

## Blocking (para no comparar N×M)

Índice invertido `token → [ids de la fuente]`. Para una fila solo se comparan los candidatos
que comparten algún token **no demasiado frecuente** (se ignoran tokens presentes en >60
registros, p. ej. "argentina", "familia", "grupo"). Así el fuzzy es O(candidatos), no O(N²).

## Resolución por precedencia (por registro de Odoo)

```
para cada registro odoo:
    para clave en [legacy, vat, name_exact]:        # claves duras, en orden
        cand = indice_fuente[clave][valor_normalizado(odoo, clave)]
        si len(cand)==1: asignar, clave_usada=clave; break
        si len(cand)>1 : registrar ambiguous_<clave>; continue
    si sin asignar:
        score, hit = mejor_fuzzy(nombre_odoo)
        si score>=STRONG: asignar, clave_usada=fuzzy_strong, score
        elif score>=REVIEW: asignar, clave_usada=fuzzy_review, score   # NO se escribe
    si sin asignar: clave_usada=none
```

Notas:
- **Relación N:1 es válida.** Varios registros de Odoo pueden apuntar a un mismo registro
  fuente (p. ej. un grupo económico con varias razones sociales). No es un duplicado a
  limpiar; todos reciben los mismos valores.
- Al escribir, **aplaná** cada grupo a writes de 1 registro: no gatean el safety gate del MCP
  (los writes multi-registro sí), y aíslan fallos.
- `integration_code`/campos integer: si la fuente lo trae vacío, **no** escribas el campo
  (dejalo en su default) en vez de forzar 0/None.

## Qué reportar (siempre)

- Conteo por `clave_usada` (cuántos por cada nivel).
- Qué campos cambiaron realmente (comparando valor actual vs objetivo).
- Lista completa de `fuzzy_strong` **aplicados** (para cazar falsos positivos).
- Lista de `fuzzy_review` **no aplicados** (para decisión humana).
- Verificación post-escritura (`search_count` del campo escrito == nº aplicado).
- Cómo revertir lo inferido (los `odoo_id` fuzzy y el `write` que los limpia).
