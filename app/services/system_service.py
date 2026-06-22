"""
System resource monitoring service — CPU, RAM, disk, GPU.
"""

from typing import Any, Dict, List

import psutil

try:
    import pynvml
    pynvml.nvmlInit()
    _NVML_AVAILABLE = True
except Exception:
    _NVML_AVAILABLE = False


def _gpu_metrics() -> List[Dict[str, Any]]:
    if not _NVML_AVAILABLE:
        return []
    try:
        device_count = pynvml.nvmlDeviceGetCount()
        gpus = []
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            try:
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            except Exception:
                temp = None
            gpus.append({
                "index": i,
                "name": name if isinstance(name, str) else name.decode(),
                "memory_used_mb": round(mem.used / 1024 / 1024, 1),
                "memory_total_mb": round(mem.total / 1024 / 1024, 1),
                "memory_usage_percent": round(mem.used / mem.total * 100, 1),
                "utilization_percent": util.gpu,
                "temperature_c": temp,
            })
        return gpus
    except Exception:
        return []


def get_system_stats() -> Dict[str, Any]:
    """Return a snapshot of current CPU, RAM, disk, and GPU usage."""
    cpu_freq = psutil.cpu_freq()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return {
        "cpu": {
            "usage_percent": psutil.cpu_percent(interval=0.2),
            "count_logical": psutil.cpu_count(logical=True),
            "count_physical": psutil.cpu_count(logical=False),
            "freq_mhz": round(cpu_freq.current, 0) if cpu_freq else None,
        },
        "memory": {
            "total_gb": round(mem.total / 1024 ** 3, 2),
            "used_gb": round(mem.used / 1024 ** 3, 2),
            "available_gb": round(mem.available / 1024 ** 3, 2),
            "usage_percent": mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / 1024 ** 3, 1),
            "used_gb": round(disk.used / 1024 ** 3, 1),
            "free_gb": round(disk.free / 1024 ** 3, 1),
            "usage_percent": disk.percent,
        },
        "gpus": _gpu_metrics(),
        "gpu_available": _NVML_AVAILABLE and len(_gpu_metrics()) > 0,
    }
