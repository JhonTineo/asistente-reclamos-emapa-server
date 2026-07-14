from app.src.application.usecase.agents.analizador import (AnalizadorAgent)
from app.src.application.usecase.agents.normativo import (NormativoAgent)
from app.src.application.usecase.agents.dictaminador import (DictaminadorAgent)
from concurrent.futures import ThreadPoolExecutor

class ReclamoWorkflow:

    def __init__(self):
        self.analizador = (AnalizadorAgent())
        self.normativo = (NormativoAgent()       )
        self.resumen_tecnico = (ResumenTecnicoAgent())
        self.dictaminador = (DictaminadorAgent())
        self.clasificador = (ClasificadorAgent())

    def run(self, detalle, contexto_emapa):
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_analisis = executor.submit(
                self.analizador.run,
                detalle
            )
            future_clasificacion = executor.submit(
                self.clasificador.run,
                detalle
            )
            future_resumen = executor.submit(
                self.resumen_tecnico.run,
                contexto_emapa
            )
            analisis = future_analisis.result()
            clasificacion = future_clasificacion.result()
            resumen_tecnico = future_resumen.result()
        articulos = self.normativo.run(detalle, analisis)

        dictamen = self.dictaminador.run(
            detalle,
            clasificacion,
            analisis,
            articulos,
            resumen_tecnico
        )

        return {
            "analisis": analisis,
            "clasificacion": clasificacion,
            "articulos": articulos,
            "resumen_tecnico": resumen_tecnico,
            "dictamen": dictamen
        }