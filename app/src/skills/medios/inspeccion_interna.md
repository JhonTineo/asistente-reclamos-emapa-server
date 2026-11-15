---
id: medio.inspeccion_interna
tipo: medio
medio: inspeccion_interna
titulo: Inspección interna
version: 4
estado: borrador
actualizado: 2026-11-13
validado_por: pendiente
---

## Qué es

Inspección al interior del predio (RGR, Art. 14.1): estado de las instalaciones
sanitarias internas, fugas visibles o no visibles, abastecimiento, puntos de
agua y categoría. Es la prueba que permite atribuir el consumo a una causa
dentro del predio, que es responsabilidad del titular y del usuario (RC,
Art. 45).

## Cómo leerlo

- Lo primero es saber **si se pudo inspeccionar el interior**. Si nadie atendió
  o no hubo acceso, empieza diciendo que no se pudo realizar la inspección
  interna, con su causa y el tiempo de espera si están documentados. Nunca
  empieces diciendo que se realizó para luego negarlo.
- Si no hubo acceso, los campos de normalidad del formulario no son
  comprobaciones del interior: no digas que se descartaron fugas ni consumos
  atípicos.
- Si se realizó, presenta la fecha y lo hallado: fugas (y si son visibles o no
  visibles), si fueron reparadas, el abastecimiento. Menciona los puntos de agua
  solo si ayudan a explicar el consumo.
- Omite datos de localización (colores de fachada, número de caja de luz) que no
  expliquen el hallazgo ni la falta de acceso.
- Omite los campos genéricos de normalidad ("no hubo consumos atípicos en la
  inspección", "abastecimiento normal") cuando solo repiten que todo estaba
  bien; menciónalos si contradicen otro dato o responden la pregunta de la
  investigación. No enumeres lo que no se encontró más allá de las fugas.
- Un solo párrafo, con el tono de un inspector de campo y sin anticipar el
  veredicto.

## Criterios de valoración

### FUG-01 · Fuga visible en las instalaciones internas
- **Estado:** activo
- **Fuerza:** decisivo
- **Requiere:** fugaVisible
- **Fuente:** RC Art. 92.3 (primer párrafo); RC Art. 45

**Por qué importa:** una fuga visible a través de los puntos de salida de agua
del predio es detectable por el propio usuario, y las instalaciones internas son
su responsabilidad. El agua que se pierde pasó por el medidor y fue consumida
en el predio.

**Favorece a la empresa cuando:** la inspección comprobó una fuga visible en el
interior durante el periodo reclamado. Corresponde facturar por diferencia de
lecturas, se haya reparado o no.

**Pesa poco cuando:** la fuga es de un periodo distinto del reclamado, o su
magnitud no puede explicar el volumen facturado.

**Si choca con otro hallazgo:** por ejemplo, falta de VPA en una zona con
discontinuidad (VPA-01). La fuga no descarta que también se haya registrado
aire: expón ambos factores y marca el caso para revisión.

**Datos que lo evidencian:** observaciones de la inspección clasificadas como
fuga visible.

### FUG-02 · Fuga no visible reparada dentro del plazo
- **Estado:** activo
- **Fuerza:** decisivo
- **Requiere:** fugaNoVisible
- **Fuente:** RC Art. 92.3 (segundo párrafo)

**Por qué importa:** una fuga no visible no es detectable a simple vista. Si el
usuario la repara dentro de los 15 días calendario que le otorga la empresa, la
norma traslada el costo de ese consumo extraordinario: los meses afectados se
facturan por promedio histórico.

**Favorece al usuario cuando:** la inspección halló una fuga no visible
(verificada cerrando todos los puntos de agua con el medidor aún registrando) y
consta que fue reparada dentro del plazo.

**Pesa poco cuando:** no consta la reparación, o consta fuera del plazo.

**Si choca con otro hallazgo:** solo aplica si los hallazgos dicen
explícitamente "no visible". No lo deduzcas de una fuga sin calificar.

**Datos que lo evidencian:** observaciones con fuga "no visible" y constancia
de su reparación; un descenso de consumo posterior en la tarjeta puede
acompañarlo, pero no lo prueba por sí solo.

### FUG-03 · Fuga no visible que persiste
- **Estado:** activo
- **Fuerza:** decisivo
- **Requiere:** fugaNoVisible
- **Fuente:** RC Art. 92.3 (segundo párrafo)

**Por qué importa:** si la fuga no visible persiste después del plazo de 15
días, la norma dispone facturar por diferencia de lecturas: el usuario fue
advertido y no reparó una instalación a su cargo.

**Favorece a la empresa cuando:** la verificación posterior confirma que la fuga
no visible sigue presente.

**Pesa poco cuando:** no consta que se haya hecho la verificación posterior.

**Si choca con otro hallazgo:** si no hay verificación posterior, no presumas que
la fuga persiste ni que fue reparada: indícalo como dato faltante.

**Datos que lo evidencian:** observaciones de una segunda visita.

### FUG-04 · Inspección interna realizada sin hallar fugas
- **Estado:** activo
- **Fuerza:** decisivo
- **Requiere:** inspeccionInternaRealizada & lecturaMesReclamado.atipico=true
- **Fuente:** RC Art. 92.3 (tercer párrafo)

**Por qué importa:** en un consumo atípico, si la inspección no revela fugas no
hay una causa en el predio que explique el exceso; la norma dispone facturar
por promedio histórico.

**Favorece al usuario cuando:** el mes reclamado es atípico (ATI-01) y la
inspección interna se realizó sin hallar fugas.

**Pesa poco cuando:** el consumo no es atípico: sin un exceso que explicar, la
ausencia de fugas solo confirma el buen estado de las instalaciones.

**Si choca con otro hallazgo:** si la inspección externa sí halló una fuga en la
conexión o en la caja, analízala con su propio criterio (CAJ-01).

**Datos que lo evidencian:** observaciones que niegan fugas
(`fugaNoDetectada`) en una inspección efectivamente realizada.

### INS-01 · No se pudo realizar la inspección interna
- **Estado:** activo
- **Fuerza:** decisivo
- **Requiere:** inspeccionInternaSinAcceso
- **Fuente:** RC Art. 92.4; RGR Art. 14.4 a 14.6; RC Art. 46

**Por qué importa:** quién causó que no se hiciera la inspección decide el caso.
El usuario está obligado a facilitar el acceso (RC, Art. 46). Si la empresa no
pudo acceder por causas que no le son atribuibles, la prueba deja de ser
necesaria y ese hecho se toma en cuenta al decidir (RGR, Art. 14.6); en un
consumo atípico se factura por diferencia de lecturas (RC, Art. 92.4). Si no se
hizo por causa de la empresa, el mes se factura por promedio histórico.

**Favorece al usuario cuando:** la inspección no se hizo por causa de la empresa:
no se notificó correctamente, el inspector llegó fuera del horario comunicado o
no se presentó.

**Favorece a la empresa cuando:** el usuario fue notificado correctamente y no
estuvo presente, o no permitió el ingreso.

**Pesa poco cuando:** no hay información sobre la causa. En ese caso no decidas
con este criterio: indica que falta saber por qué no se hizo la inspección y
marca el caso para revisión.

**Si choca con otro hallazgo:** no presentes la inspección como realizada ni sus
campos genéricos como comprobaciones.

**Datos que lo evidencian:** observaciones de la visita ("nadie atendió", "no
permitió el ingreso", tiempo de espera) y la fecha de notificación de la
inspección del reclamo.

## Preguntas abiertas

- ¿EMAPA registra en la inspección por qué no se pudo acceder (ausencia del
  usuario pese a la notificación, negativa al ingreso)? Es lo que decide INS-01.
