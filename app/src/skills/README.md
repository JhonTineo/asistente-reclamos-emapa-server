# Skills de Yumi

Las skills son el **conocimiento del oficio** que Yumi usa para analizar un
reclamo: cómo leer cada medio probatorio y cómo pesa cada dato en el veredicto,
según el Reglamento de Calidad y el Reglamento de Reclamos de la SUNASS y el
criterio del especialista.

No son reglas automáticas del tipo "si pasa X, entonces FUNDADO". Cada criterio
explica **por qué** un hecho importa, **cuándo** favorece al usuario o a la
empresa y **con qué otros hechos** se combina. Así el modelo puede aplicarlo a
casos que nadie previó, y reconocer cuándo no aplica.

## Estructura

```
skills/
  base/<nombre>.md     rol de Yumi y reglas comunes a todos los pasos
                       (sección obligatoria: "Rol")
  tipos/<tipo>.md      qué debe probar la empresa en ese tipo de reclamo y
                       cómo se decide (una skill por tipo de reclamo)
  medios/<medio>.md    cómo leer un medio probatorio y qué criterios de
                       valoración aporta (una skill por medio)
  pasos/<paso>.md      instrucciones fijas de un paso del workflow
                       (objetivos, fundamentación, conclusión, conciliación,
                       resolución y extractores; sección obligatoria:
                       "Instrucciones")
```

Todas las llamadas al modelo pasan por el constructor de contexto
(`application/services/contexto`). Cada paso tiene una especificación en
`especificaciones.py` que dice qué capas lleva; los pasos simples llevan:

- `rol_base`: la skill base, según lo que hace el paso: completa en los que
  redactan texto del informe; solo "Rol" y "Reglas sobre los datos" en los que
  razonan sobre los hechos sin redactar (objetivos, dictamen); y ninguna en los
  que solo eligen índices o clasifican (selección y aplicabilidad de la
  fundamentación, evaluación de objetivos) y en los extractores;
- `skill`: la sección "Instrucciones" de `pasos/<paso>.md`;
- `instrucciones`: lo que el código añade porque depende del caso (por
  ejemplo, la fórmula de cierre según el veredicto o la oración de cierre de
  la conciliación);
- `entrada`: los datos del caso, siempre en el mensaje del usuario.

Si falta la skill de un paso, la llamada falla con un error que nombra el
archivo esperado. La sección "Notas" de cualquier skill es para personas: no se
envía al modelo.

En la skill base y en las de paso, los ejemplos **no deben llevar códigos de
hechos, fechas ni cifras concretas**: el modelo los copia en la respuesta como
si fueran datos del caso. Y una skill de paso que lleva el rol base no declara
otro rol ("Eres un analista…"): empieza por "En este paso…".

## Editar en producción sin redesplegar

Además de esta carpeta, Yumi lee una **carpeta de reemplazos** (por defecto
`volumes/skills`; en el VPS, `/opt/yumi-data/skills`, configurable con
`YUMI_SKILLS_PATH`). Un archivo ahí con la **misma ruta relativa** que una skill
de este repositorio la reemplaza:

```
/opt/yumi-data/skills/base/reglas_generales.md   → reemplaza skills/base/reglas_generales.md
/opt/yumi-data/skills/medios/tarjeta_lectura.md  → reemplaza skills/medios/tarjeta_lectura.md
```

- El cambio se aplica en la siguiente llamada al modelo, sin reiniciar.
- Si el reemplazo tiene errores de formato, se usa la versión del repositorio
  y el error queda en el log (`[SKILLS]`).
- Cada informe guarda la versión exacta de la skill con que se generó
  (`llamadas_llm.skill_version`), así se sabe si salió de un reemplazo.
- Un reemplazo que funciona bien debe llevarse después a este repositorio:
  si no, el próximo cambio en el repositorio quedará oculto por el reemplazo.

## Formato de un archivo

Cabecera YAML entre `---`, seguida de secciones `##`:

```markdown
---
id: medio.tarjeta_lectura         # único entre todas las skills
tipo: medio                       # base | medio | tipo_reclamo | paso
medio: tarjeta_lectura            # solo en skills de medio
# paso: objetivos                 # solo en skills de paso (nombre del paso)
codigos_tipo_reclamo: ["001"]     # solo en skills de tipo de reclamo
clasificaciones: ["A1"]           # solo en skills de tipo de reclamo
titulo: Tarjeta de lecturas
version: 1                        # súbelo cuando cambies el contenido
estado: activo                    # activo | borrador | inactivo
actualizado: 2026-11-13
validado_por: pendiente           # quién revisó los criterios
---

## Qué es
## Cómo leerlo                    # instrucciones para resumir el medio
## Criterios de valoración        # cómo pesa cada dato en el veredicto
## Preguntas abiertas             # solo para personas: no se envía al modelo
```

Secciones de una skill de tipo de reclamo: `Qué es`, `Qué debe probar la
empresa`, `Método de decisión`, `Criterios de valoración` y `Preguntas abiertas`.

### Criterios

Cada criterio es un subtítulo `###` con un ID único en **todas** las skills,
seguido de sus metadatos y su explicación:

```markdown
### VPA-01 · Sin válvula de purga de aire en zona con discontinuidad
- **Estado:** por_confirmar
- **Fuerza:** decisivo
- **Fuente:** Art. 75 RC; RGR Anexo 3 (consumo medido); criterio del especialista (13/11/2026)
- **Pendiente:** ¿aplica también con servicio continuo 24 h?

**Por qué importa:** ...
**Favorece al usuario cuando:** ...
**Pesa poco cuando:** ...
**Si choca con otro hallazgo:** ...
**Datos que lo evidencian:** ...
```

- **Estado:** `activo` (se aplica), `por_confirmar` (se aplica, pero el modelo
  lo ve marcado como pendiente de validar con el especialista) o `inactivo`
  (no se envía al modelo; se conserva para el historial).
- **Fuerza:** `decisivo` (si aplica, puede decidir el veredicto por sí solo) o
  `indicio` (apoya, pero no decide). Es obligatoria. El dictamen la usa así:
  - un criterio decisivo a favor del usuario y ninguno a favor de la empresa →
    FUNDADO; al revés → INFUNDADO;
  - decisivos en ambas direcciones → revisión del especialista;
  - sin criterios decisivos → INFUNDADO (régimen de diferencia de lecturas,
    RC Art. 93), salvo que el modelo proponga FUNDADO: entonces, revisión.
- **Requiere** (opcional): qué hecho debe existir en el caso para que el
  criterio pueda aplicar. Formato `tipoDeHecho` o `tipoDeHecho.campo=valor`
  (`true`, `false`, `null` o un texto); `&` = "y", `|` = "o". Ejemplo:
  `vpaZona.existe=false & horarioAbastecimiento.continuo=false`. La condición
  la comprueba el código, no el modelo (que solo ve el texto de cada hecho, no
  sus valores):
  - si **ningún hecho del caso** la cumple, el criterio queda como `no_aplica`
    sin enviarse al modelo (evita, por ejemplo, declarar atípico un consumo que
    no lo es, y acorta el contexto y la respuesta);
  - si se envía y el modelo lo marca como aplicable, el verificador exige que
    alguno de los hechos que cita la cumpla.
  La condición no se muestra al modelo: no escribas en el cuerpo del criterio
  nombres de campos internos.
- **Fuente:** el artículo y/o quién lo definió. Es obligatoria: un criterio sin
  fuente no se carga.
- **Pendiente:** dudas para el especialista. No se envía al modelo.

## Cómo administrarlas

- **Agregar un criterio:** nuevo `###` con un ID que no exista (p.ej. `ATI-03`).
- **Cambiar un criterio:** edita su texto y sube `version` en la cabecera.
- **Quitar un criterio:** cambia su estado a `inactivo` (no lo borres: los
  informes antiguos guardan con qué versión se decidieron).
- Valida los archivos con:
  `python -m app.src.infrastructure.adapters.skills.skill_file_repository`

## Abreviaturas

- **RC:** Reglamento de Calidad de la Prestación de los Servicios de Saneamiento
  (texto según Res. 058-2023-SUNASS-CD).
- **RGR:** Reglamento General de Reclamos de Usuarios de Servicios de
  Saneamiento (texto según Res. 015-2023-SUNASS-CD).
