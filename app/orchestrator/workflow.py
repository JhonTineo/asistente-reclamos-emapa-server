from app.agents.analizador import (
    AnalizadorAgent
)

from app.agents.normativo import (
    NormativoAgent
)

from app.agents.dictaminador import (
    DictaminadorAgent
)

from app.agents.resumen_tecnico import (
    ResumenTecnicoAgent
)


class ReclamoWorkflow:

    def __init__(self):

        self.analizador = (
            AnalizadorAgent()
        )

        self.normativo = (
            NormativoAgent()
        )

        self.resumen_tecnico = (
            ResumenTecnicoAgent()
        )

        self.dictaminador = (
            DictaminadorAgent()
        )

    def run(
        self,
        detalle,
        contexto_emapa
    ):

        analisis = (
            self.analizador.run(
                detalle
            )
        )

        resumen_tecnico = (
            self.resumen_tecnico.run(
                contexto_emapa
            )
        )

        articulos = (
            self.normativo.run(
                detalle,
                analisis
            )
        )

        dictamen = (
            self.dictaminador.run(
                detalle,
                contexto_emapa,
                articulos,
                resumen_tecnico
            )
        )

        return {
            "analisis": analisis,
            "articulos": articulos,
            "resumen_tecnico": resumen_tecnico,
            "dictamen": dictamen
        }