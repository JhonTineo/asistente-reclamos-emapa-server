"""Middleware ASGI que sincroniza la memoria del caso al terminar cada petición.

Varios agentes modifican el InformeAtencion directamente (objetivos,
veredicto, conclusión, artículos de un problema...) sin pasar por un método
del store. En vez de instrumentar cada uno de esos puntos, al terminar cada
petición se guardan los informes cuya huella cambió.

Es ASGI puro (no ``BaseHTTPMiddleware``) para enterarse del fin REAL de la
respuesta: en los endpoints de streaming el trabajo ocurre mientras se envía el
cuerpo, así que se espera al último fragmento (``more_body=False``) o a que la
petición termine con error.
"""

import logging

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.src.application.services.informe.informe_store import informe_store

logger = logging.getLogger("api.persistencia")


class PersistenciaCasosMiddleware:

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Los GET también cuentan: la búsqueda del reclamo (GET) crea el informe
        # y le asigna datos después de crearlo. Comparar huellas es barato.
        if scope["type"] != "http" or scope.get("method") in ("HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        persistido = False

        async def persistir() -> None:
            nonlocal persistido
            if persistido:
                return
            persistido = True
            try:
                await run_in_threadpool(informe_store.persistir_cambios)
            except Exception:  # noqa: BLE001
                logger.exception("[PERSISTENCIA] Falló la sincronización de casos")

        async def send_con_persistencia(message: Message) -> None:
            # Se guarda ANTES de enviar el último fragmento: así, cuando el
            # cliente recibe la respuesta completa, el estado ya está en disco.
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                await persistir()
            await send(message)

        try:
            await self.app(scope, receive, send_con_persistencia)
        finally:
            await persistir()
