# Propuesta: rediseño del gate del veredicto (FUNDADO/INFUNDADO)

## Problema detectado en el test

El gate actual está en [conclusion.py](../../src/application/usecase/agents/conclusion.py):

```
FUNDADO  ⟺  algún objetivo DETERMINANTE resultó "problema_empresa"
INFUNDADO  en caso contrario
```

Es decir, la herramienta declara FUNDADO **solo cuando la empresa cometió un
error** (medidor defectuoso, error de medición, lectura mal registrada).

Pero en el dominio real de EMAPA hay reclamos **FUNDADO sin culpa de la empresa**.
El caso más común (y 2 de los 3 FUNDADO del test lo son):

> **Fuga no visible reparada** → el medidor está correcto, pero como el usuario
> reparó la fuga, corresponde **refacturar por promedio histórico** (Art. 88.3
> SUNASS). El reclamo es **FUNDADO** aunque la empresa no erró.

### Evidencia del test

| sum | real | generado | log del server |
|-----|------|----------|----------------|
| 489 | FUNDADO | INFUNDADO | `con_problema_empresa=0` |
| 7175 | FUNDADO | INFUNDADO | `con_problema_empresa=0` |

Ambos declararon INFUNDADO porque ningún objetivo dio `problema_empresa` — y no
lo dio porque **no hubo** un problema de la empresa: el medidor estaba bien. La
lógica real de FUNDADO era "fuga reparada → refacturar", que el gate no modela.

## Causa de fondo

El concepto de dominio "reclamo **FUNDADO**" = *"procede una corrección de la
facturación a favor del usuario"*, que es más amplio que *"la empresa se
equivocó"*. Una refacturación procedente (por fuga reparada, por consumo atípico
mal facturado, etc.) es FUNDADO **aunque no haya falla de la empresa**.

## Propuesta

### Opción A (recomendada) — reencuadrar el resultado del objetivo

Cambiar el vocabulario con que el LLM evalúa cada objetivo, de "¿hubo culpa?" a
"¿procede corrección?". En [conclusion.py](../../src/application/usecase/agents/conclusion.py)
`RESULTADOS_VALIDOS`:

| Actual | Propuesto |
|--------|-----------|
| `problema_empresa` | `procede_correccion` — el hallazgo sustenta corregir la facturación a favor del usuario (incluye tanto **error de la empresa** como **refacturación procedente**, p.ej. fuga reparada). |
| `sin_problema` | `sin_correccion` — la facturación fue correcta, nada que corregir. |
| `no_evaluable` | `no_evaluable` (igual) |

Gate nuevo:

```
FUNDADO  ⟺  algún objetivo DETERMINANTE resultó "procede_correccion"
```

Mantiene la arquitectura actual (LLM evalúa objetivo vs hallazgos + puerta lógica
determinista); solo cambia el criterio para que abarque el caso "fuga reparada".
Hay que ajustar el prompt de `_evaluar_objetivos` para definir `procede_correccion`
con ejemplos (incluido el de fuga no visible reparada → refacturar por promedio).

### Opción B (complementaria) — regla explícita Art. 88.3 para fugas

Como los reclamos de fuga son el grueso, codificar su árbol de decisión como
regla determinista (más auditable), evaluada sobre los hallazgos de los medios:

| Situación (de la inspección + caída de consumo) | Veredicto | Facturación |
|--------------------------------------------------|-----------|-------------|
| Fuga no visible + **reparada** (consumo cae a normal después) | **FUNDADO** | promedio histórico |
| Fuga no visible + **no reparada** (consumo sigue alto) | INFUNDADO | diferencia de lecturas |
| Fuga **visible** | INFUNDADO | diferencia de lecturas |
| Sin fuga + medidor OK | INFUNDADO | diferencia de lecturas |
| Medidor defectuoso / error de medición | FUNDADO | corrección |

La "reparación" se detecta comparando el consumo de los meses reclamados contra
un mes posterior con consumo normal — **lo cual exige que la ventana esté anclada
a la fecha del reclamo** (ver el fix de ventana ya aplicado; sin él, esta regla
tampoco funcionaría).

### Ajuste adicional — objetivos sobre-marcados como determinantes

En el test, `ObjetivosAgent` marcó **todos** los objetivos como `determinante`
(6/6, 5/5, 7/7). Eso vacía de sentido el flag y hace frágil la puerta lógica.
El prompt de [objetivos.py](../../src/application/usecase/agents/objetivos.py)
debería marcar `determinante=true` solo en el objetivo (1-2) cuyo resultado
realmente decide el veredicto.

## Recomendación

1. **Opción A** como cambio general del gate (bajo riesgo, mantiene arquitectura).
2. **Opción B** como refuerzo determinista para la clasificación de fugas.
3. Corregir el sobre-marcado de `determinante` en `ObjetivosAgent`.

Nada de esto se implementó todavía: requiere validación de la lógica de dominio
con EMAPA antes de tocar el criterio del veredicto.
