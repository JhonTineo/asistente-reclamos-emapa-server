---
id: paso.objetivos
tipo: paso
paso: objetivos
titulo: Objetivos de investigación
version: 3
estado: activo
actualizado: 2026-11-20
validado_por: pendiente
---

## Instrucciones

En este paso, a partir del motivo del reclamo, defines los OBJETIVOS de investigación: qué verificar en los medios probatorios para determinar si el reclamo procede (FUNDADO) o no (INFUNDADO).

MÉTODO:
1. Primero identifica la PREGUNTA DECISIVA: dado el motivo, ¿qué hecho, por sí solo, haría FUNDADO este reclamo?
2. Deriva de 2 a 4 OBJETIVOS concretos y verificables. NO generes uno por cada medio: solo los que realmente importan para este reclamo.
3. Formula cada objetivo como PREGUNTA NEUTRAL verificable (no como una afirmación que dé por hecho el resultado), para no sesgar el análisis.

Para objetivos de inspección, asigna el medio principal: el análisis también recibirá la otra inspección como contexto complementario, sin confundir una revisión externa con una revisión del interior.
DETERMINANTE:
- Marca determinante=true SOLO el objetivo (uno; a lo sumo dos) cuyo resultado POR SÍ SOLO cambia el veredicto FUNDADO↔INFUNDADO (el que responde la pregunta decisiva).
- Distingue SÍNTOMA de CAUSA: un objetivo que solo CONFIRMA el síntoma que reclama el cliente (p. ej. «¿el consumo del mes es más alto que el promedio?») NO es determinante por sí solo — confirmar que el consumo es alto no resuelve el reclamo, solo indica que hay algo que explicar. Son determinantes los objetivos que establecen la CAUSA o la legitimidad del cobro (inspección de fugas o del medidor, método/historial de facturación, error de medición): cada uno puede, por sí solo, inclinar el veredicto.
- MEDIOS OBLIGATORIOS DEL TIPO DE RECLAMO: si recibes la sección «Qué debe probar la empresa» del tipo de reclamo, cada medio que esa sección exige y que esté en la lista de medios disponibles debe tener un objetivo con determinante=true, AUNQUE el motivo no lo mencione (p. ej. en consumo medido, el informe del área de control operacional: «¿El informe operacional acredita la continuidad del servicio y la ausencia de interrupciones en el mes reclamado y, si hubo discontinuidad, la existencia y operatividad de las válvulas de purga de aire?»). Si falta, el reclamo es FUNDADO (RGR, Art. 12.1). Esta regla se suma al límite de uno o dos determinantes de arriba.
- Los objetivos de contexto o soporte van con determinante=false, aunque sean útiles.
- En "porque_determinante" explica en una frase por qué ese objetivo decide (o no) el veredicto.

Ejemplo (reclamo por fuga no visible):
[{"descripcion": "¿Una inspección o documento acredita la existencia, visibilidad y eventual reparación de la fuga?", "medio": "inspeccion_interna", "determinante": true, "porque_determinante": "la inspección aporta evidencia directa; una variación mensual de consumo no acredita por sí sola una fuga ni su reparación"}, {"descripcion": "¿Hubo un descenso posterior al consumo elevado y cuáles fueron sus cifras?", "medio": "tarjeta_lectura", "determinante": false, "porque_determinante": "describe la serie de consumo sin establecer su causa"}]

Ejemplo (reclamo por consumo medido alto; el cliente NO menciona fuga, solo que su consumo habitual es menor):
[{"descripcion": "¿El consumo del mes reclamado es realmente mayor que el promedio histórico del predio?", "medio": "tarjeta_lectura", "determinante": false, "porque_determinante": "solo confirma el síntoma; que el consumo sea alto no resuelve el reclamo por sí solo"}, {"descripcion": "¿La facturación previa venía por promedio y pasó a medido, generando el desajuste?", "medio": "record_facturacion", "determinante": true, "porque_determinante": "si el alza se explica por el paso de promedio a medido, el cobro es correcto (INFUNDADO)"}, {"descripcion": "¿La inspección halló una fuga (visible o no visible) que explique el consumo?", "medio": "inspeccion_interna", "determinante": true, "porque_determinante": "la inspección acredita la existencia y visibilidad de la fuga; cualquier reparación debe estar respaldada por una fuente adicional"}]

Responde SOLO con el JSON (lista de objetos con las claves "descripcion", "medio", "determinante", "porque_determinante"), sin texto adicional.

## Notas

El código añade la lista de medios probatorios disponibles (MEDIOS en pasos/objetivos.py) y, según la clasificación del reclamo, la sección «Qué debe probar la empresa» de la skill del tipo (skills/tipos/). Los medios obligatorios se mantienen allí, no aquí.
