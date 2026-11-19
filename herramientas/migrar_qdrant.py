"""Copia colecciones de un Qdrant a otro punto a punto (vectores + payload).

Alternativa a los snapshots: estos pesan cientos de MB (WAL y segmentos
preasignados) aunque la colección tenga unos cientos de puntos.

El Qdrant del VPS no publica puertos; se llega con un túnel SSH a la IP interna
del contenedor (ver la ayuda de --destino). Uso, desde la raíz del repo:

    .venv\\Scripts\\python.exe herramientas\\migrar_qdrant.py --destino http://127.0.0.1:16333

Por defecto copia sunass_reglamento y sunass_reclamos. En el destino BORRA y
recrea cada colección con la configuración de vectores del origen.
"""

import argparse
import sys

from qdrant_client import QdrantClient, models


def migrar(origen: QdrantClient, destino: QdrantClient, nombre: str, lote: int = 64) -> None:
    info = origen.get_collection(nombre)
    vectores = info.config.params.vectors
    if destino.collection_exists(nombre):
        destino.delete_collection(nombre)
    destino.create_collection(nombre, vectors_config=vectores)

    copiados, offset = 0, None
    while True:
        puntos, offset = origen.scroll(nombre, limit=lote, offset=offset,
                                       with_payload=True, with_vectors=True)
        if puntos:
            destino.upsert(nombre, wait=True, points=[
                models.PointStruct(id=p.id, vector=p.vector, payload=p.payload) for p in puntos
            ])
            copiados += len(puntos)
        if offset is None:
            break

    total = destino.count(nombre, exact=True).count
    esperado = origen.count(nombre, exact=True).count
    estado = "OK" if total == esperado else "DIFERENCIA"
    print(f"{nombre}: {copiados} copiados | destino={total} origen={esperado} [{estado}]")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origen", default="http://127.0.0.1:6333")
    ap.add_argument("--destino", required=True,
                    help="URL del Qdrant destino. Para el VPS: abrir antes el túnel "
                         "ssh -N -L 16333:<IP del contenedor qdrant>:6333 root@<VPS> "
                         "y pasar http://127.0.0.1:16333")
    ap.add_argument("--colecciones", nargs="+", default=["sunass_reglamento", "sunass_reclamos"])
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    origen = QdrantClient(args.origen, timeout=60)
    destino = QdrantClient(args.destino, timeout=60)
    for nombre in args.colecciones:
        migrar(origen, destino, nombre)


if __name__ == "__main__":
    main()
