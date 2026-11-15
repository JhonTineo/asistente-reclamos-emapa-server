---
id: medio.tarjeta_lectura
tipo: medio
medio: tarjeta_lectura
titulo: Tarjeta de lecturas
version: 4
estado: borrador
actualizado: 2026-11-13
validado_por: pendiente
---

## Qué es

Histórico mensual de lecturas del medidor: lectura anterior y última, consumo
del mes, promedio histórico, estado de la lectura (código de EMAPA), estado del
servicio y del medidor, número de medidor y observaciones del lector. Es parte
del histórico de lecturas que la empresa debe presentar en todo reclamo por
consumo medido (RGR, Anexo 3, B.1.1).

## Cómo leerlo

- Céntrate en el mes o meses reclamados y en sus antecedentes dentro de la
  ventana de análisis. No describas todos los meses.
- Menciona, con sus cifras y meses:
  - consumos marcados como atípicos, excesivos o dobles al promedio
    (`errorConsumo`);
  - descensos de consumo posteriores a un consumo elevado
    (`descensoConsumo`). No atribuyas su causa a una fuga ni a una reparación:
    el dato solo muestra que el consumo bajó;
  - errores de lectura (lecturas iguales, consumo negativo, lectura que no
    pertenece al periodo) y estados anómalos del medidor o del servicio
    (`errorLecturas`, `errorServicio`);
  - cambios de medidor coincidentes con un consumo atípico
    (`errorReinstalacion`).
- El estado de lectura "CONSUMO ATIPICO" es la marca que el propio sistema de
  EMAPA asigna al mes. Repórtala tal cual; no la recalcules.
- Menciona solo lo que sí aparece. No enumeres lo que no ocurrió ("no se
  registraron consumos atípicos, descensos ni cambios de medidor"), salvo que
  sea justo lo que pregunta la investigación.
- No menciones metadatos ni totales de registros. Escribe un solo párrafo, sin
  anticipar el veredicto.

## Criterios de valoración

### ATI-01 · Consumo atípico en el mes reclamado
- **Estado:** por_confirmar
- **Fuerza:** decisivo
- **Requiere:** lecturaMesReclamado.atipico=true
- **Fuente:** RC Art. 92.1 a 92.4; criterio del especialista (13/11/2026)
- **Pendiente:** confirmar que "atípico es fundado" se refiere al caso en que la inspección no halló fugas o no se realizó por causa de la empresa (RC Art. 92.3 y 92.4).

**Por qué importa:** un consumo atípico (más del 100% sobre el promedio
histórico y al menos dos asignaciones de consumo, solo en la clase
residencial) obliga a la empresa a descartar primero un error de lectura y luego
los factores distorsionantes mediante inspecciones. El resultado de esas
inspecciones decide cómo se factura el mes:
- error en la toma de lectura → se corrige la lectura;
- sin fugas → se factura por **promedio histórico**;
- fuga no visible reparada en 15 días → los meses afectados se facturan por
  **promedio histórico**;
- fuga visible, o fuga no visible que persiste → se factura por **diferencia de
  lecturas**;
- inspección no realizada por causa de la empresa → **promedio histórico**;
- inspección interna no realizada por causa del usuario → **diferencia de
  lecturas**.

**Favorece al usuario cuando:** el mes reclamado es atípico y la empresa lo
facturó por diferencia de lecturas sin que una inspección haya encontrado una
fuga atribuible al usuario, o sin haber realizado las inspecciones por causa
propia.

**Pesa poco cuando:** la inspección interna comprobó una fuga visible, o una fuga
no visible que el usuario no reparó; o la inspección interna no se pudo hacer
por causa del usuario (ver INS-01 en la inspección interna).

**Si choca con otro hallazgo:** el atípico no decide solo: es la puerta de entrada
al procedimiento del RC Art. 92. Combínalo siempre con lo que digan las
inspecciones interna y externa.

**Datos que lo evidencian:** estado de lectura "CONSUMO ATIPICO" o un consumo
elevado frente al promedio en el mes reclamado (`errorConsumo`); el atípico
también puede figurar en las inspecciones.

### ATI-02 · Límite de la facturación por promedio en consumos atípicos
- **Estado:** por_confirmar
- **Fuerza:** indicio
- **Requiere:** lecturaMesReclamado.atipico=true
- **Fuente:** RC Art. 92.3 (párrafos finales); criterio del especialista ("hasta por 12 meses consecutivos", 13/11/2026)
- **Pendiente:** confirmar que el "hasta por 12 meses" del especialista corresponde a este límite.

**Por qué importa:** la facturación por promedio histórico que dispone el
Art. 92.3 solo procede **una vez cada doce (12) meses** y **como máximo por dos
(2) meses consecutivos**. El periodo de 12 meses se cuenta desde el primer mes en
que se configuró el atípico. Después del último mes atípico configurado, la
empresa vuelve a facturar por diferencia de lecturas.

**Favorece al usuario cuando:** es el primer episodio atípico en los últimos
12 meses, o el segundo mes consecutivo de ese mismo episodio.

**Pesa poco cuando:** el usuario ya tuvo meses atípicos facturados por promedio
dentro de los 12 meses anteriores, o el episodio supera los dos meses
consecutivos: en esos meses corresponde la diferencia de lecturas.

**Si choca con otro hallazgo:** no cambia la causa del consumo; solo limita
cuántos meses se pueden refacturar por promedio. Indícalo en el análisis.

**Datos que lo evidencian:** los meses marcados como atípicos en la ventana de
la tarjeta y cómo se facturó cada uno (récord de facturación).

### LEC-01 · Error en la toma de la lectura
- **Estado:** activo
- **Fuerza:** decisivo
- **Fuente:** RC Art. 92.2 (i)

**Por qué importa:** si el consumo elevado proviene de una lectura mal tomada o
mal registrada, el error es de la empresa y debe corregirse antes de facturar.

**Favorece al usuario cuando:** la tarjeta muestra un error de lectura en el mes
reclamado (lecturas iguales seguidas de un salto, consumo negativo, lectura
última menor, lectura que no pertenece al periodo) y el consumo facturado
depende de esa lectura.

**Pesa poco cuando:** el error está en un mes distinto del reclamado y no afecta
el consumo facturado en el mes reclamado.

**Si choca con otro hallazgo:** un error de lectura comprobado en el mes
reclamado explica el consumo con más fuerza que una fuga sospechada.

**Datos que lo evidencian:** `errorLecturas` con el mes reclamado; estado de
lectura distinto de "LECTURA NORMAL".

### LEC-02 · Diferencia de lecturas no válida
- **Estado:** activo
- **Fuerza:** decisivo
- **Fuente:** RC Art. 91.f y Art. 93

**Por qué importa:** para facturar por diferencia de lecturas, el periodo entre
lecturas debe estar entre 28 y 32 días calendario. Fuera de ese rango la
diferencia no es válida y no puede sustentar la facturación del mes.

**Favorece al usuario cuando:** el mes reclamado se facturó por diferencia de
lecturas con un periodo entre lecturas menor de 28 o mayor de 32 días, o con una
lectura que no pertenece al periodo facturado.

**Pesa poco cuando:** el periodo entre lecturas está dentro del rango.

**Si choca con otro hallazgo:** aunque el consumo sea real, la empresa no puede
facturarlo por diferencia de lecturas con una lectura inválida.

**Datos que lo evidencian:** fechas de lectura de la tarjeta; hallazgo "error de
fecha (lectura no pertenece al periodo)".

### MED-01 · Medidor en mal estado o cambiado en el periodo reclamado
- **Estado:** por_confirmar
- **Fuerza:** indicio
- **Fuente:** criterio a validar con el especialista
- **Pendiente:** ¿qué estados del medidor (luna rota, nublado, paralizado, invertido…) hacen dudar del registro? ¿Qué artículo cita EMAPA en estos casos?

**Por qué importa:** si el medidor no estaba en condiciones de registrar
correctamente, el volumen facturado puede no reflejar el consumo real. Un
cambio de medidor junto a un consumo atípico sugiere un problema en la
instalación o en la lectura inicial del medidor nuevo.

**Favorece al usuario cuando:** el estado del medidor en el mes reclamado indica
un daño que afecta el registro, o hubo un cambio de medidor con consumo atípico
en ese mes.

**Pesa poco cuando:** el estado anómalo no afecta el registro (p.ej. un daño en
la tapa) o se dio en un mes distinto del reclamado.

**Si choca con otro hallazgo:** contrástalo con la inspección externa, que
verifica si el medidor funciona correctamente.

**Datos que lo evidencian:** `errorServicio` con prefijo "medidor:",
`errorReinstalacion`.

## Preguntas abiertas

- ¿El "hasta por 12 meses consecutivos" se refiere al límite del RC Art. 92.3
  (una vez cada 12 meses, máximo 2 meses consecutivos)?
- ¿Qué estados del medidor considera EMAPA que invalidan el registro?
