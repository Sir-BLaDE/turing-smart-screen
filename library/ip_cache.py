# GameHUD - caché de la IP pública con expiración configurable.
# Se guarda en library/config/gamehud_ip.txt para persistencia entre reinicios del programa.

import os
import time
from pathlib import Path

CACHED_IPS = {}
CACHE_EXPIRES = {}


def cache_key(service):
    """Devuelve una clave única para el servicio (p.ej., 'ip')"""
    return f"ip::{service}"


def set_cache(service, value, ttl=600):
    """Guarda un valor en caché con tiempo de vida (en segundos)."""
    key = cache_key(service)
    CACHE_EXPIRES[key] = time.time() + ttl
    CACHED_IPS[key] = value


def is_expired(key):
    """Comprueba si la entrada ha expirado."""
    if key not in CACHE_EXPIRES:
        return True
    return time.time() > CACHE_EXPIRES[key]


def clear_cache():
    """Limpia todas las entradas de caché."""
    CACHED_IPS.clear()
    CACHE_EXPIRES.clear()


def get(service, fallback=None):
    """Obtiene la IP o dato guardado. Si ha expirado y hay una función 'fetch' para el servicio:
       - llama a fetch()
       - guarda con TTL por defecto (10 min = 600 s)
       - devuelve el resultado
    
    Si no hay funcion 'fetch', devuelve None (fallback si se pasa).
    
    Para persistencia, también se escribe en library/config/gamehud_ip.txt
    """
    key = cache_key(service)
    
    # Chequear expiración
    if is_expired(key):
        CACHED_IPS.pop(key, None)
        CACHE_EXPIRES.pop(key, None)
    
    # ¿Tiene valor en caché?
    if key in CACHED_IPS:
        return CACHED_IPS[key]
    
    # Intento de lectura del archivo de configuración
    config_file = Path("library/config/gamehud_ip.txt")
    try:
        content = config_file.read_text(encoding="utf8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Formato: [servicio] valor
            if line.startswith("[") and "]" in line:
                svc_name, value = line.split("]", 1)
                svc_name = svc_name.strip()[1:-1].strip()  # quitar [ y ]
                if svc_name == service:
                    set_cache(service, value.strip(), ttl=600)  # 10 min
                    return value.strip()
    except Exception as e:
        print(f"GameHUD: error leyendo {config_file}: {e}", flush=True)
    
    return None


def init():
    """Inicializa el módulo, verificando si ya hay datos cacheados."""
    config_file = Path("library/config/gamehud_ip.txt")
    if not config_file.exists():
        return
    
    try:
        content = config_file.read_text(encoding="utf8")
        # Buscar todas las líneas tipo [servicio] valor y cachearlas
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and "]" in line:
                svc_name, value = line.split("]", 1)
                svc_name = svc_name.strip()[1:-1].strip()
                value = value.strip()
                # Solo cachear servicios conocidos
                if svc_name in ("ip", "gateway"):
                    set_cache(svc_name, value, ttl=600)
    except Exception as e:
        print(f"GameHUD: inicialización de IP cache fallida: {e}", flush=True)


# Llamada automática al importar (pero solo si no estamos en un entorno que ya tiene caché)
if __name__ == "__main__":
    print("IP Cache - Inicialización y pruebas")
    init()
    print(f"IP publico cacheado: {get('ip', None)}")
    print(f"Gateway cacheado: {get('gateway', None)}")
