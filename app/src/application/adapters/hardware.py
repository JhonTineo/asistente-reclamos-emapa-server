"""Detección de hardware para decidir si el servidor puede ofrecer inferencia
local (Ollama) de forma viable. Sin dependencias externas (no requiere
psutil): usa /proc/meminfo en Linux y la API de Windows por ctypes.

Corriendo LLMs de generación en CPU sin GPU es lento y satura el servidor (ver
incidente documentado: un VPS de 2 vCPU sin GPU se saturaba con qwen2.5:3b).
Este chequeo evita que se elija inferencia local en un servidor sin recursos
para ello, sin bloquear el uso de Ollama solo para embeddings (mucho más
livianos) en `EmbeddingService`.
"""

import ctypes
import logging
import platform
import shutil
import subprocess

logger = logging.getLogger("core.hardware")


def tiene_gpu() -> bool:
    """True si hay una GPU NVIDIA detectable (nvidia-smi disponible y responde).
    No detecta GPUs AMD/Intel: para inferencia local de LLM lo relevante en la
    práctica es CUDA."""
    if not shutil.which("nvidia-smi"):
        return False
    try:
        resultado = subprocess.run(
            ["nvidia-smi", "-L"], capture_output=True, timeout=5, text=True,
        )
        return resultado.returncode == 0 and "GPU" in resultado.stdout
    except Exception as exc:
        logger.warning("No se pudo consultar nvidia-smi: %s", exc)
        return False


def memoria_total_gb() -> float | None:
    """Memoria RAM total del sistema en GB, o None si no se pudo determinar."""
    sistema = platform.system()
    try:
        if sistema == "Linux":
            with open("/proc/meminfo") as f:
                for linea in f:
                    if linea.startswith("MemTotal:"):
                        kb = int(linea.split()[1])
                        return kb / (1024 * 1024)
            return None
        if sistema == "Windows":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
            return stat.ullTotalPhys / (1024 ** 3)
    except Exception as exc:
        logger.warning("No se pudo determinar la memoria total (%s): %s", sistema, exc)
    return None


def hardware_apto_para_local(min_ram_gb: float, requiere_gpu: bool) -> tuple[bool, str | None]:
    """Evalúa si este servidor tiene hardware adecuado para inferencia local de
    LLM. Devuelve (apto, motivo_si_no_apto)."""
    if requiere_gpu and not tiene_gpu():
        return False, "No se detectó GPU NVIDIA (nvidia-smi no disponible)."

    ram = memoria_total_gb()
    if ram is None:
        return False, "No se pudo determinar la memoria RAM del servidor."
    if ram < min_ram_gb:
        return False, f"Memoria insuficiente: {ram:.1f} GB disponibles, se requieren {min_ram_gb:.0f} GB."

    return True, None
