---
id: medio.inspeccion_externa
tipo: medio
medio: inspeccion_externa
titulo: Inspección externa
version: 4
estado: borrador
actualizado: 2026-11-13
validado_por: pendiente
---

## Qué es

Inspección fuera del predio (RGR, Art. 14.1): funcionamiento del medidor, fugas
en la conexión y en la caja del medidor, estado de la caja y de la conexión, y
observaciones del inspector. Es un medio de prueba obligatorio en los reclamos
por consumo medido, "para detectar posibles fugas que incrementen el consumo"
(RGR, Anexo 3, B.1.1).

## Cómo leerlo

- Prioriza la fecha, si el medidor funciona y se puede leer, las fugas y el
  estado de la caja y de la conexión.
- Indica **dónde** está la fuga si el dato lo dice (en la caja, antes del
  medidor, después del medidor): esa ubicación determina de quién es la
  responsabilidad.
- Si el campo de fugas indica ausencia y el tipo de fuga dice "No Hay", escribe
  una sola vez "No se detectaron fugas".
- Agrupa el buen estado del medidor, la caja y la conexión en una oración, pero
  conserva cualquier anomalía concreta (luna opaca, medidor nublado) aunque otro
  dato diga que funciona.
- Omite un cierre genérico como "no se detectaron condiciones atípicas" si
  solo repite lo normal ya descrito, y no enumeres lo que no se encontró más
  allá de las fugas.
- No es necesario nombrar al responsable de la inspección. Un solo párrafo, sin
  anticipar el veredicto.

## Criterios de valoración

### CAJ-01 · Fuga en la caja del medidor o en la conexión domiciliaria
- **Estado:** por_confirmar
- **Fuerza:** decisivo
- **Requiere:** fugasInspeccionExterna.ubicacion=caja | fugasInspeccionExterna.ubicacion=antes_medidor
- **Fuente:** RC Art. 8.2; criterio del especialista (13/11/2026)
- **Pendiente:** ¿aplica si la fuga está antes del medidor? En ese caso el agua no pasa por el medidor y no explicaría un consumo registrado.

**Por qué importa:** la empresa es responsable de la operatividad y el
mantenimiento de la infraestructura hasta la conexión domiciliaria **inclusive**,
de la que forma parte la caja del medidor; si la caja está dentro del predio,
también del tramo hasta la caja. Una fuga en ese tramo es un problema de la
infraestructura de la empresa, no de las instalaciones del usuario.

**Favorece al usuario cuando:** la inspección halla una fuga en la caja del
medidor o en la conexión domiciliaria en el periodo reclamado.

**Pesa poco cuando:** la fuga está claramente antes del medidor y el consumo
facturado no se explica por ella, o se detectó en un periodo distinto del
reclamado.

**Si choca con otro hallazgo:** si la inspección interna halló además una fuga
visible dentro del predio, expón ambas causas y marca el caso para revisión.

**Datos que lo evidencian:** tipo de fuga "Fuga en la Caja de Registro…" o
"Fuga antes del Medidor"; caja o conexión en mal estado; observaciones del
inspector.

### FUG-05 · Fuga después del medidor detectada desde el exterior
- **Estado:** por_confirmar
- **Fuerza:** indicio
- **Requiere:** fugasInspeccionExterna.ubicacion=despues_medidor
- **Fuente:** RC Art. 45 y Art. 92.3
- **Pendiente:** ¿cómo distingue EMAPA una fuga "después del medidor" en la caja de una fuga en las instalaciones internas del usuario?

**Por qué importa:** después del medidor comienzan las instalaciones a cargo del
usuario. El agua que se pierde ahí pasa por el medidor y se registra.

**Favorece a la empresa cuando:** la fuga después del medidor es visible y está
en las instalaciones del usuario; se analiza como una fuga visible (FUG-01).

**Pesa poco cuando:** la fuga está dentro de la caja del medidor, que es parte
de la conexión domiciliaria (ver CAJ-01).

**Si choca con otro hallazgo:** contrástalo con la inspección interna.

**Datos que lo evidencian:** tipo de fuga "Fuga despues del Medidor".

### MEX-01 · El medidor no funciona correctamente
- **Estado:** por_confirmar
- **Fuerza:** indicio
- **Fuente:** criterio a validar con el especialista
- **Pendiente:** ¿qué artículo aplica EMAPA cuando la inspección externa encuentra el medidor sin funcionar?

**Por qué importa:** si el medidor no funciona correctamente, el volumen que
registró no es una base confiable para facturar por diferencia de lecturas.

**Favorece al usuario cuando:** la inspección del periodo reclamado indica que
el medidor no funciona correctamente.

**Pesa poco cuando:** la anomalía es estética (tapa, luna) y la inspección
confirma que el medidor registra con normalidad.

**Si choca con otro hallazgo:** contrástalo con la tarjeta de lecturas (MED-01).

**Datos que lo evidencian:** "El medidor no funciona correctamente"; estado del
medidor en la tarjeta.

### CON-01 · Contradicción entre el campo de fugas y las observaciones
- **Estado:** activo
- **Fuerza:** decisivo
- **Requiere:** contradiccionFuga
- **Fuente:** criterio de análisis de Yumi (la evidencia se contradice a sí misma)

**Por qué importa:** si el campo estructurado dice una cosa y la observación del
inspector dice lo contrario, la inspección no acredita ninguna de las dos
versiones por sí sola.

**Favorece a:** ninguna parte. No decidas con este medio hasta resolver la
contradicción: si aplica, usa `"favorece": "revision"` para que el caso pase a
revisión del especialista.

**Datos que lo evidencian:** hallazgo `contradiccionFuga`.

## Preguntas abiertas

- EMAPA rotula el código de fuga 002 como "Fuga en la Caja de Registro". En el
  RC, "caja de registro" es la caja de la conexión de **alcantarillado**, no la
  del medidor. ¿Ese código se refiere a la caja del medidor?
- ¿"Fuga en caja" es fundado aunque la fuga esté antes del medidor?
