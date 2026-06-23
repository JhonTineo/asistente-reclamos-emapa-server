import time
import logging
from langchain_core.messages import SystemMessage
from core.llm import get_llm

logger = logging.getLogger("agent.resolucion")


class ResolucionAgent:
    def __init__(self, model: str | None = None):
        self.model = model
        self.llm = get_llm(model=model)

    def generar_resolucion(
        self,
        codreclamo: str,
        informe_atencion: str,
        propuesta_conciliacion: str,
        observaciones: str | None = None,
    ) -> dict:
        t_inicio = time.perf_counter()

        logger.info("=" * 60)
        logger.info("[RESOLUCION] INICIO - Generando resolución")
        logger.info("[RESOLUCION] codreclamo=%s", codreclamo)

        prompt = self._construir_prompt(
            codreclamo,
            informe_atencion,
            propuesta_conciliacion,
            observaciones,
        )

        logger.info("[RESOLUCION] Invocando LLM...")
        t_llm_inicio = time.perf_counter()

        response = self.llm.invoke([SystemMessage(content=prompt)])
        contenido = response.content if response.content else ""

        t_llm = time.perf_counter() - t_llm_inicio
        t_duracion = time.perf_counter() - t_inicio

        # Verificar si es fundada o infundada
        es_fundada = "FUNDADO" in contenido.upper() and "INFUNDADO" not in contenido.upper()
        tipo = "FUNDADO" if es_fundada else "INFUNDADO"

        logger.info("[RESOLUCION] LLM completado | tipo=%s (%.2fs)", tipo, t_llm)
        logger.info("[RESOLUCION] Resolución generada (%d caracteres)", len(contenido))
        logger.info("[RESOLUCION] COMPLETADO | tiempo=%.2fs", t_duracion)
        logger.info("=" * 60)

        return {
            "resolucion": contenido,
            "tipo": tipo,
            "tiempo": t_duracion,
        }

    def _construir_prompt(
        self,
        codreclamo: str,
        informe_atencion: str,
        propuesta: str,
        observaciones: str | None,
    ) -> str:
        return f"""Eres un agente especialista en resolución de reclamos de EMAPA.

Tu tarea es analizar el informe de atención y la propuesta de conciliación para determinar si el reclamo es FUNDADO o INFUNDADO, y generar la resolución oficial.

REGLAS PARA DECLARAR FUNDADO:
- Si el informe de atención identifica errores, omisiones o negligencia de la empresa
- Si se encontraron inconsistencias en la facturación a favor del usuario
- Si existen anomalías en el medidor atribuibles a la empresa
- Si la propuesta de conciliación propone acciones correctivas para la empresa
- Si existe报销不一致 (discrepancia en facturación)

REGLAS PARA DECLARAR INFUNDADO:
- Si el informe de atención demuestra que la facturación es correcta
- Si el consumo facturado coincide con las lecturas del medidor
- Si el usuario no做梦istió a la conciliación (cuando aplique)
- Si el reclamo es extemporáneo (fuera de plazo según normativa)
- Si existe negligencia del usuario (manipulación de medidor, conexiones irregulares, fugas no reportadas)
- Si no se encontró evidencia de error en la facturación

DATOS DEL RECLAMO:
- Código de Reclamo: {codreclamo}
{f'- Observaciones: {observaciones}' if observaciones else ''}

=== INFORME DE ATENCIÓN ===
{informe_atencion}

=== PROPUESTA DE CONCILIACIÓN ===
{propuesta}

=== FORMATO DE RESOLUCIÓN ===

Para RECLAMO FUNDADO:
---
SE DECLARA FUNDADO EL RECLAMO PRESENTADO POR EL USUARIO; Y ORDENA [acción específica].
POR LO TANTO, SE PROCEDERÁ DE LA SIGUIENTE MANERA:
1. [Detalle de la acción 1 con valores específicos si aplica]
2. [Detalle de la acción 2 si aplica]
[Incluir cuadro con lecturas, consumos y montos si es relevante]
FUNDADO. - [Breve explicación del fundamento técnico]
---

Para RECLAMO INFUNDADO:
---
[Situación que motiva el infundado, ej: "EL CONSUMO FACTURADO ES CORRECTO SEGÚN VERIFICACIÓN TÉCNICA" o "EL USUARIO NO ASISTIÓ A LA SESIÓN DE CONCILIACIÓN"]
POR LO QUE EN APLICACIÓN DE LAS RESOLUCIONES N.º 066-2006-SUNASS-CD, N.º 015-2023-SUNASS-CD Y N.º 058-2023-SUNASS-CD, Y EL PRINCIPIO DE RAZONABILIDAD, SE RESUELVE:
[Explicación técnica de por qué es infundado basada en el informe de atención]
POR LO TANTO, SE DECLARA INFUNDADO EL RECLAMO Y SE MANTIENE EL MONTO FACTURADO.
{f'SE DEJA CONSTANCIA DE LA FRUSTRACIÓN DE LA ETAPA DE CONCILIACIÓN.' if observaciones and 'no asistente' in observaciones.lower() else ''}
EL PROCEDIMIENTO CONTINUA CONFORME A LEY.
---

INSTRUCCIONES:
1. Lee cuidadosamente el informe de atención y la propuesta de conciliación
2. Determina si el reclamo es FUNDADO o INFUNDADO basándote en las reglas y en los hallazgos del informe
3. Usa la información del informe para fundamentar tu decisión
4. Incluye valores específicos cuando el informe los proporcione (montos, consumos, lecturas)
5. Usamayúsculas para títulos y secciones importantes
6. Sé técnico y objetivo en la fundamentación
7. La primera palabra de la resolución debe ser "FUNDADO" o "INFUNDADO" según corresponda

Responde ÚNICAMENTE con la resolución en el formato especificado."""
