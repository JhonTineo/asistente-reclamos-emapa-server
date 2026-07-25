"""Agentes del caso de uso.

Sin reexportaciones a propósito: cada agente se importa por su ruta completa
(`...usecase.agents.objetivos import ObjetivosAgent`), que es como lo hacen
todos los llamadores. Reexportar acá obligaba a importar todos los agentes
para usar uno solo, y mantenía vivas clases que ya nadie usaba.
"""
