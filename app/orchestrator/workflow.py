from app.agents.analizador import (
    AnalizadorAgent
)

from app.agents.normativo import (
    NormativoAgent
)

from app.agents.dictaminador import (
    DictaminadorAgent
)


class ReclamoWorkflow:

    def __init__(self):

        self.analizador = (
            AnalizadorAgent()
        )

        self.normativo = (
            NormativoAgent()
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
                articulos
            )
        )

        return {
            "analisis": analisis,
            "articulos": articulos,
            "dictamen": dictamen
        }