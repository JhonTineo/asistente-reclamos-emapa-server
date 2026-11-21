---
id: medio.tecnico_operacional
tipo: medio
medio: tecnico_operacional
titulo: Informe técnico operacional
version: 4
estado: borrador
actualizado: 2026-11-20
validado_por: pendiente
---

## Qué es

Informe del área de control operacional sobre las condiciones del servicio en
el sector del predio durante el periodo reclamado: horario de abastecimiento,
interrupciones, existencia y estado de las válvulas de purga de aire (VPA),
presión y curvas de nivel. Es el medio con el que la empresa acredita que el
medidor operó en condiciones adecuadas (RGR, Anexo 3, B.1.1).

Llega en dos formatos: un **formulario** con casillas (SI/NO, "Si hay VPA" /
"No hay VPA", "Operativa" / "Inoperativa") y un **informe narrativo** en prosa.

## Cómo leerlo

- Identifica, si están escritos:
  - el **horario de abastecimiento** del sector y si el servicio es continuo
    (24 horas) o restringido a ciertas horas;
  - si hubo **interrupciones** en el periodo reclamado, cuándo y cuánto duraron;
  - si **existe una VPA** en la zona y, si existe, si está **operativa**;
  - la presión registrada y si se adjunta el plano de curvas de nivel.
- Un servicio que solo llega en ciertas franjas horarias (p.ej. de 2:40 a 8:20 y
  de 17:30 a 21:50) es un **servicio discontinuo**, aunque el informe diga que
  "no hubo interrupciones": la red se vacía y se vuelve a llenar todos los días.
  Descríbelo como tal.
- Una casilla del formulario marcada como "No determinada" significa que no se
  pudo leer la respuesta: dilo así y no la completes por tu cuenta.
- Escribe un solo párrafo, con las horas y fechas tal como figuran. No atribuyas
  causas al consumo ni anticipes el veredicto.

## Criterios de valoración

### VPA-01 · No existe válvula de purga de aire en una zona con discontinuidad
- **Estado:** por_confirmar
- **Fuerza:** decisivo
- **Requiere:** vpaZona.existe=false & horarioAbastecimiento.continuo=false | vpaZona.existe=false & interrupcionesPeriodo.hubo=true
- **Fuente:** RC Art. 75; RGR Art. 12.1 y Anexo 3 (B.1.1); criterio del especialista (13/11/2026)
- **Pendiente:** ¿aplica también si el servicio es continuo 24 h y sin interrupciones?

**Por qué importa:** cuando la red se vacía (horario restringido o
interrupciones), al volver el servicio el aire acumulado empuja el medidor y se
registra como consumo sin que pase agua. Por eso el RC obliga a la empresa a
contar con válvulas de aire, especialmente donde hay discontinuidad, y el RGR le
exige acreditar su ubicación y operatividad en los reclamos por consumo medido.

**Favorece al usuario cuando:** el sector tiene servicio discontinuo o hubo
interrupciones en el periodo reclamado y el informe confirma que no existe VPA
en la zona. La empresa no puede acreditar que el volumen registrado corresponde
solo a agua consumida.

**Pesa poco cuando:** el servicio es continuo las 24 horas y no hubo
interrupciones en el periodo reclamado: sin vaciado de la red, la falta de VPA
no explica por sí sola el consumo registrado.

**NO lo neutralizan:** una lectura «normal», un medidor en buen estado o que
funciona correctamente, la ausencia de fugas en las inspecciones, ni que el
consumo no llegue a ser atípico. El aire pasa por un medidor sano y queda
registrado como una lectura normal: esos hechos son justamente lo que produce
el aire, no lo descartan. La carga de acreditar que el medidor reflejó solo
agua es de la empresa (RGR, Anexo 3, B.1.1), y sin VPA en un sector con
discontinuidad no puede acreditarlo. Si este criterio aplica, el reclamo es
FUNDADO aunque el resto de la evidencia sea regular; solo lo cambia un hecho de
«Pesa poco cuando» o un conflicto de «Si choca con otro hallazgo».

**Si choca con otro hallazgo:** por ejemplo, una fuga visible comprobada en el
interior del predio. La fuga explica el consumo por una causa del usuario, pero
no descarta que el aire también se haya registrado. Expón ambos factores y marca
el caso para revisión.

**Datos que lo evidencian:** "Existencia de VPA en la zona: No hay VPA" en el
formulario, o la frase equivalente del informe narrativo; el horario de
abastecimiento y las interrupciones del periodo.

### VPA-02 · La válvula de purga de aire existe pero está inoperativa
- **Estado:** por_confirmar
- **Fuerza:** decisivo
- **Requiere:** vpaZona.operativa=false & horarioAbastecimiento.continuo=false | vpaZona.operativa=false & interrupcionesPeriodo.hubo=true
- **Fuente:** RC Art. 75 (instalación, mantenimiento y renovación de las válvulas); RGR Anexo 3 (B.1.1, informe de operatividad); criterio del especialista (13/11/2026)
- **Pendiente:** igual que VPA-01: ¿y si el servicio es continuo?

**Por qué importa:** una válvula inoperativa no evacúa el aire; para el registro
del medidor equivale a no tenerla. La obligación de la empresa no es solo
instalarla, sino mantenerla operativa.

**Favorece al usuario cuando:** el informe indica que la VPA de la zona está
inoperativa y hubo discontinuidad o interrupciones en el periodo reclamado.

**Pesa poco cuando:** el servicio es continuo y sin interrupciones (ver VPA-01).

**Si choca con otro hallazgo:** como en VPA-01.

**Datos que lo evidencian:** "Estado de la VPA: Inoperativa" en el formulario, o
la frase equivalente del informe narrativo.

### INT-01 · Interrupciones o desabastecimiento en el periodo reclamado
- **Estado:** por_confirmar
- **Fuerza:** decisivo
- **Requiere:** interrupcionesPeriodo.hubo=true
- **Fuente:** RC Art. 75; RGR Anexo 3 (B.1.1, reporte de continuidad e interrupciones); criterio del especialista (13/11/2026)
- **Pendiente:** ¿el desabastecimiento hace fundado el reclamo por sí solo, o solo cuando no hay una VPA operativa? ¿Exige una duración mínima?

**Por qué importa:** una interrupción vacía la red; al restablecerse el servicio
puede registrarse aire como consumo. Además, un periodo con desabastecimiento
hace menos verosímil un consumo más alto de lo habitual.

**Favorece al usuario cuando:** el informe reporta interrupciones o
desabastecimiento en el periodo reclamado y el consumo facturado de ese periodo
es mayor al habitual del usuario.

**Pesa poco cuando:** la interrupción fue breve, el sector cuenta con VPA
operativa y el consumo del periodo es similar al habitual.

**Si choca con otro hallazgo:** si otro medio explica el consumo por una causa
del usuario (p.ej. una fuga visible), expón ambos factores y marca el caso para
revisión.

**Datos que lo evidencian:** "En el periodo reclamado hubo interrupciones en el
abastecimiento: SI" en el formulario, o la descripción de interrupciones del
informe narrativo; la inspección interna puede indicar "Sin abastecimiento".

### OPE-01 · El informe no permite acreditar las condiciones operacionales
- **Estado:** activo
- **Fuerza:** decisivo
- **Requiere:** vpaZona.existe=null | horarioAbastecimiento.continuo=null | interrupcionesPeriodo.hubo=null
- **Fuente:** RGR Art. 12.1 y Anexo 3 (B.1.1)

**Por qué importa:** el informe operacional es la prueba con la que la empresa
acredita que el medidor registró solo agua. Si hubo discontinuidad y el informe
no dice si existe VPA ni si está operativa, esa acreditación no existe.

**Favorece al usuario cuando:** hubo discontinuidad o interrupciones y el
informe omite la información de las VPA, o sus casillas no se pudieron
determinar.

**Pesa poco cuando:** el servicio fue continuo y sin interrupciones: en ese caso
la información de las VPA no es necesaria.

**Si choca con otro hallazgo:** trátalo como una prueba faltante (PRU-01).

**Datos que lo evidencian:** casillas "No determinada" o ausencia de la
información de VPA en el texto extraído.

## Preguntas abiertas

- Juan indicó que "no hay válvula de aire" y "hay válvula pero está inoperativa"
  son fundados. ¿Siempre, o solo en zonas con servicio discontinuo o
  interrupciones? (La norma vincula la válvula a la discontinuidad.)
- ¿Qué pasa si no se cargó el informe técnico operacional en un reclamo de
  consumo medido?
