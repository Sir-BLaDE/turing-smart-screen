# GameHUD custom data sources for turing-smart-screen-python
# Se copia a library/sensors/sensors_gamehud.py (lo hace install_gamehud.py)
#
#  - HudFps / HudFpsGame / HudFrameTime : FPS del juego activo leyendo la memoria compartida de RTSS
#                          (RivaTuner Statistics Server, incluido con MSI Afterburner)
#  - HudVolt1..4         : voltajes de la placa (LibreHardwareMonitor, requiere admin)
#  - HudCpuClock/HudGpuClock : reloj de CPU (media de núcleos) y GPU siempre en MHz
#  - HudGpuMemClock/HudVram : reloj de memoria y VRAM usada/total de la GPU (LibreHardwareMonitor)
#  - HudRamSpeed         : velocidad y voltaje de la RAM (WMI); HudRamTimings: texto de gamehud_ram.txt
#  - HudDisk1..5         : espacio libre de los discos fijos
#  - HudCpuFan/HudGpuFan : RPM de los ventiladores (LibreHardwareMonitor; elección en gamehud_fans.txt)
#  - HudDisk1Io..4Io     : lectura/escritura en tiempo real de cada disco (psutil)
#  - HudNetDown/HudNetUp : velocidad de red (suma de todas las interfaces)
#  - HudRamPercent/Detail, HudClock, HudDate

import ctypes
import json
import logging
import math
import os
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from typing import List

import collections
import psutil
from PIL import Image, ImageDraw, ImageFont

from library.sensors.sensors_custom import CustomDataSource

logger = logging.getLogger(__name__)

__all__ = [
    "HudClock", "HudDate", "HudWeather", "HudDisplayMode", "HudCoreRow0", "HudCoreRow1", "HudCoreRow2", "HudRamPercent", "HudRamDetail",
    "HudNetDown", "HudNetUp", "HudFps", "HudFpsGame", "HudFpsApi", "HudFrameTime",
    "HudVolt1", "HudVolt2", "HudVolt3", "HudVolt4", "HudVolt5", "HudVolt6",
    "HudCpuClock", "HudGpuClock", "HudGpuMemClock", "HudVram", "HudRamSpeed", "HudRamTimings",
    "HudDisk1", "HudDisk2", "HudDisk3", "HudDisk4", "HudDisk5",
    "HudDisk1Io", "HudDisk2Io", "HudDisk3Io", "HudDisk4Io", "HudNetTotal",
    "HudCpuFan", "HudGpuFan", "HudCpuVolt", "HudGpuVolt",
    "HudFpsTitle", "HudFpsLabel1", "HudFpsLabel2", "HudHeroClear", "HudUptime", "HudIdleCpu", "HudIdleGpu",
    "HudTopH0", "HudTopH1", "HudTopH2", "HudRouterIp", "HudFpsStats", "HudStatus",
]

_DIAG = {"n": 0, "t0": None, "frames": 0, "last_log": -1e9, "reported": False, "last_call": None}
HISTORY = 60          # debe coincidir con HISTORY_SIZE del theme.yaml
FAST_JPEG = True      # envía los fotogramas a la pantalla TURZX como JPEG en vez de PNG (ver _install_fast_frames)
POWER_ROWS = 5       # filas del panel POWER (4 a 6); debe coincidir con POWER_ROWS del instalador
CORE_RISE = 0.3       # medidores de núcleo: cuánto sube hacia el valor nuevo en cada ciclo (1 = salto directo)
CORE_FALL = 0.12      # ...y cuánto baja (menor = caída más suave); pon ambos a 1.0 para desactivar el suavizado
ALERT_FLASH = True    # borde rojo parpadeante cuando la temperatura de CPU/GPU llega a crítico (False = desactivado)
COALESCE_MS = 40      # junta los cambios de pantalla y manda UN fotograma cada ~40 ms (0 = desactivado)
_LEVELS = {}          # ALERT_FMT -> (nivel 0/1/2, texto, instante): lo que alimenta el indicador de estado de la cabecera
WX_CHARS = 18         # caracteres del tiempo que caben antes del indicador de estado (igual que en el instalador)
_ALERT = {"t": -1e9}  # última vez que un elemento con ALERT_FLASH estuvo en estado crítico
_STATE = {}           # estado por clase (por si el proyecto recrea las instancias)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# --------------------------------------------------------------------------- prioridad del proceso
# Las tareas programadas de Windows arrancan por defecto con prioridad "por debajo de lo normal" (7): con la CPU
# muy cargada (jugando) el HUD podía quedarse atrás. Se sube a prioridad normal al arrancar.
def _raise_priority():
    try:
        if sys.platform == "win32":
            p = psutil.Process()
            if p.nice() in (psutil.BELOW_NORMAL_PRIORITY_CLASS, psutil.IDLE_PRIORITY_CLASS):
                p.nice(psutil.NORMAL_PRIORITY_CLASS)
                logger.info("GameHUD: prioridad del proceso subida a normal")
    except Exception as e:  # noqa
        logger.debug("GameHUD: no se pudo cambiar la prioridad: %s", e)


_raise_priority()


# --------------------------------------------------------------------------- envío rápido a la pantalla
# En las pantallas TURZX USB el proyecto manda la pantalla ENTERA cada vez que cambia cualquier valor, y
# prueba primero a codificarla como PNG (con un fondo detallado tarda ~230 ms por fotograma frente a ~5 ms
# en JPEG). Con ~40 actualizaciones por ciclo la cola se satura y todo (hora incluida) va a tirones.
# Aquí se sustituye ese envío por JPEG 4:4:4 calidad 92 (el mismo comando de subida que el programa ya usa
# cuando el PNG no cabe). Pon FAST_JPEG = False para volver al comportamiento original.
def _install_fast_frames():
    if not FAST_JPEG:
        return
    try:
        import library.lcd.lcd_comm_turing_usb as t

        def fast(dev, image, *, max_bytes=t.MAX_IMAGE_PAYLOAD_DEFAULT):
            jpg = t._encode_jpeg_under_limit(image, max_bytes=max_bytes, quality=92, subsampling=0)
            t.send_jpeg(dev, jpg)

        if not getattr(t.send_pil_image_auto, "_gamehud", False):
            fast._gamehud = True
            t.send_pil_image_auto = fast
            logger.info("GameHUD: envío de fotogramas en JPEG activado")
    except Exception as e:  # noqa
        logger.debug("GameHUD: no se activó el envío JPEG: %s", e)


_install_fast_frames()


# En el modelo TURZX USB cada texto/barra/gráfica que se actualiza manda la pantalla ENTERA y espera la
# confirmación del dispositivo; además varios hilos escriben a la vez sin ningún bloqueo. Con ~40 elementos
# por ciclo eso es imposible de servir y aparece el retraso. Aquí cada actualización solo se pega en la
# imagen en memoria y un único hilo manda el resultado como mucho cada COALESCE_MS (el programa oficial
# de TURZX hace algo parecido: dibuja él mismo y manda fotogramas a ritmo fijo).
def _install_coalescing():
    if not COALESCE_MS:
        return
    try:
        import library.lcd.lcd_comm_turing_usb as t
        from library.lcd.lcd_comm import Orientation
        cls = t.LcdCommTuringUSB
        if getattr(cls.DisplayPILImage, "_gamehud", False):
            return

        io_lock = threading.RLock()
        orig_write = t.write_to_device

        def locked_write(dev, data, timeout=2000):          # nunca dos escrituras USB a la vez
            with io_lock:
                return orig_write(dev, data, timeout)

        t.write_to_device = locked_write

        dirty = threading.Event()
        state_lock = threading.Lock()
        holder = {"lcd": None, "thread": None}

        fail = {"n": 0, "last": -1e9, "rec": -1e9, "had_alert": False}

        def alert_on():
            return ALERT_FLASH and time.monotonic() - _ALERT["t"] < 2.5

        def reconnect(lcd):
            """Si la pantalla se desconectó (USB, suspensión profunda...), vuelve a buscarla y a inicializarla."""
            try:
                dev, _pid = t.find_usb_device()               # lanza ValueError si todavía no está
                lcd.dev = dev
                t.send_sync_command(dev)
                if _BR["requested"] is not None:
                    lcd.SetBrightness(_BR["requested"])
                logger.info("GameHUD: pantalla USB reconectada")
                return True
            except Exception as e:  # noqa
                logger.debug("GameHUD: reconexión USB: %s", e)
                return False

        def sender():
            while True:
                signaled = dirty.wait(0.5)
                alert = alert_on()
                if not signaled and not alert and not fail["had_alert"]:
                    continue                                    # nada que mandar
                if signaled:
                    time.sleep(COALESCE_MS / 1000.0)           # deja que se junten varios cambios
                lcd = holder["lcd"]
                with state_lock:
                    dirty.clear()
                    snap = lcd.current_state.copy()
                if alert and int(time.monotonic() * 2) % 2 == 0:     # parpadeo a 1 Hz
                    ImageDraw.Draw(snap).rectangle([0, 0, snap.width - 1, snap.height - 1],
                                                   outline=(255, 70, 100, 255), width=8)
                fail["had_alert"] = alert                       # al terminar la alerta, un último fotograma sin borde
                try:
                    if lcd.orientation == Orientation.LANDSCAPE:
                        base = snap.transpose(t.Image.Transpose.ROTATE_270)
                    elif lcd.orientation == Orientation.REVERSE_LANDSCAPE:
                        base = snap.transpose(t.Image.Transpose.ROTATE_90)
                    elif lcd.orientation == Orientation.PORTRAIT:
                        base = snap.transpose(t.Image.Transpose.ROTATE_180)
                    else:
                        base = snap
                    t.send_pil_image_auto(lcd.dev, base, max_bytes=t.MAX_IMAGE_PAYLOAD_DEFAULT)
                    _DIAG["frames"] += 1
                    fail["n"] = 0
                except Exception as e:  # noqa
                    fail["n"] += 1
                    dirty.set()                            # el fotograma se reintenta aunque no haya cambios nuevos
                    now = time.monotonic()
                    if now - fail["last"] > 30:            # un aviso cada 30 s como máximo
                        logger.warning("GameHUD: error enviando el fotograma (%d seguidos): %s", fail["n"], e)
                        fail["last"] = now
                    if fail["n"] >= 3 and now - fail["rec"] > 5:     # tras 3 fallos seguidos, intenta reconectar
                        fail["rec"] = now
                        if reconnect(lcd):
                            fail["n"] = 0
                            dirty.set()
                    time.sleep(1.0)                        # y sin insistir a toda velocidad

        def patched(self, image, x=0, y=0, image_width=0, image_height=0):
            if image.size[0] <= 0 or image.size[1] <= 0:      # texto en blanco sin región fija: nada que pintar
                return
            if not image_height:
                image_height = image.size[1]
            if not image_width:
                image_width = image.size[0]
            if image.size[1] > self.get_height():
                image_height = self.get_height()
            if image.size[0] > self.get_width():
                image_width = self.get_width()
            if image_width != image.size[0] or image_height != image.size[1]:
                image = image.crop((0, 0, image_width, image_height))
            with state_lock:
                self.current_state.paste(image, (x, y))
            holder["lcd"] = self
            if holder["thread"] is None:
                holder["thread"] = threading.Thread(target=sender, name="GameHUD_sender", daemon=True)
                holder["thread"].start()
            dirty.set()

        patched._gamehud = True
        cls.DisplayPILImage = patched
        logger.info("GameHUD: envío agrupado de fotogramas activado (%d ms)", COALESCE_MS)
    except Exception as e:  # noqa
        logger.debug("GameHUD: no se activó el envío agrupado: %s", e)


_install_coalescing()


# --------------------------------------------------------------------------- colores por umbral
# El programa da un color fijo a cada elemento. Aquí se intercepta display_themed_value/_progress_bar: si el
# elemento del tema trae WARN_AT/CRIT_AT (o WARN_BELOW/CRIT_BELOW) y COLOR_WARN/COLOR_CRIT, se dibuja con ese
# color cuando el valor cruza el umbral. Los sensores propios envían el número delante del texto con un marcador.
MARK = "\x1f"
_PATCH = {"colors": False}


def _tag(v, text):
    """Antepone el valor numérico (solo si el parche está activo; si no, saldría como carácter raro)."""
    return f"{MARK}{v:.2f}{MARK}{text}" if _PATCH["colors"] else text


def _install_threshold_colors():
    def worker():
        m = None
        for _ in range(600):                                   # espera (hasta 60 s) a que library.stats esté cargado
            m = sys.modules.get("library.stats")
            if m is not None and hasattr(m, "display_themed_value") and hasattr(m, "display_themed_progress_bar"):
                break
            time.sleep(0.1)
        else:
            return
        if getattr(m.display_themed_value, "_gamehud", False):
            return
        orig_v, orig_b = m.display_themed_value, m.display_themed_progress_bar

        def num(td, k):
            try:
                return None if td.get(k) is None else float(td.get(k))
            except (TypeError, ValueError):
                return None

        def level(td, v):
            crit, warn, cb, wb = num(td, "CRIT_AT"), num(td, "WARN_AT"), num(td, "CRIT_BELOW"), num(td, "WARN_BELOW")
            if (crit is not None and v >= crit) or (cb is not None and v <= cb):
                return 2
            if (warn is not None and v >= warn) or (wb is not None and v <= wb):
                return 1
            return 0

        def recolor(td, v, key):
            if v is None:
                return td
            lvl = level(td, v)
            col = td.get("COLOR_CRIT") if lvl == 2 else td.get("COLOR_WARN") if lvl == 1 else None
            if lvl and col is not None:
                td = dict(td)
                td[key] = col
            return td

        def themed_value(theme_data, value, min_size=0, unit=""):
            v = None
            if isinstance(value, str) and value.startswith(MARK):
                _, n, value = value.split(MARK, 2)
                v = float(n)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                v = float(value)
            fmt = theme_data.get("ALERT_FMT")
            if v is not None and fmt:                          # alimenta el indicador de estado de la cabecera
                try:
                    _LEVELS[fmt] = (level(theme_data, v), fmt.format(v=v), time.monotonic())
                except Exception:  # noqa
                    pass
            if v is not None and theme_data.get("ALERT_FLASH") and level(theme_data, v) == 2:
                _ALERT["t"] = time.monotonic()
            return orig_v(recolor(theme_data, v, "FONT_COLOR"), value, min_size, unit)

        def themed_bar(theme_data, value):
            try:
                v = float(value)
            except (TypeError, ValueError):
                v = None
            return orig_b(recolor(theme_data, v, "BAR_COLOR"), value)

        themed_value._gamehud = themed_bar._gamehud = True
        m.display_themed_value, m.display_themed_progress_bar = themed_value, themed_bar
        _PATCH["colors"] = True
        logger.info("GameHUD: colores por umbral activados")

    threading.Thread(target=worker, name="GameHUD_colors", daemon=True).start()


_install_threshold_colors()


# --------------------------------------------------------------------------- brillo nocturno
# gamehud_brightness.txt:  night = 15 (tope de brillo en %, "off" lo desactiva),  from = 23:00,  to = 08:00.
# Se aplica como TOPE: si tu brillo de día ya es menor, no cambia nada. Con la pantalla apagada (bloqueo/suspensión)
# no se toca.
_BR = {"cfg": None, "t": -1e9, "requested": None, "applied": None, "lcd": None}


def _br_cfg():
    now = time.monotonic()
    if _BR["cfg"] is not None and now - _BR["t"] < 20:
        return _BR["cfg"]
    cfg = {"night": 15, "from": (23, 0), "to": (8, 0)}
    try:
        with open(os.path.join(ROOT, "gamehud_brightness.txt"), encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = [x.strip().lower() for x in line.split("=", 1)]
                if k == "night":
                    cfg["night"] = None if v in ("off", "no", "false", "") else max(0, min(100, int(float(v))))
                elif k in ("from", "to"):
                    h, m = v.split(":")
                    cfg[k] = (int(h), int(m))
    except (OSError, ValueError) as e:
        if not isinstance(e, FileNotFoundError):
            logger.debug("GameHUD: gamehud_brightness.txt: %s", e)
    _BR["cfg"], _BR["t"] = cfg, now
    return cfg


def _is_night(dt, cfg):
    if cfg["night"] is None:
        return False
    a, b = cfg["from"][0] * 60 + cfg["from"][1], cfg["to"][0] * 60 + cfg["to"][1]
    n = dt.hour * 60 + dt.minute
    return (a <= n < b) if a < b else (n >= a or n < b)


def _effective_brightness(level, dt=None):
    if level <= 0:
        return level
    cfg = _br_cfg()
    return min(level, cfg["night"]) if _is_night(dt or datetime.now(), cfg) else level


def _install_night_brightness():
    try:
        import library.lcd.lcd_comm_turing_usb as t
        cls = t.LcdCommTuringUSB
        if getattr(cls.SetBrightness, "_gamehud", False):
            return
        orig = cls.SetBrightness

        def patched(self, level=25):
            eff = _effective_brightness(level)
            _BR.update(requested=level, applied=eff, lcd=self)
            return orig(self, eff)

        patched._gamehud = True
        cls.SetBrightness = patched

        def watcher():
            while True:
                time.sleep(20)
                try:
                    lcd, req = _BR["lcd"], _BR["requested"]
                    if lcd is not None and req and _effective_brightness(req) != _BR["applied"]:
                        lcd.SetBrightness(req)                   # pasa por el parche y aplica el tope (o lo quita)
                        logger.info("GameHUD: brillo ajustado a %s %%", _BR["applied"])
                except Exception as e:  # noqa
                    logger.debug("GameHUD: brillo nocturno: %s", e)

        threading.Thread(target=watcher, name="GameHUD_brightness", daemon=True).start()
    except Exception as e:  # noqa
        logger.debug("GameHUD: no se activó el brillo nocturno: %s", e)


_install_night_brightness()


# --------------------------------------------------------------------------- dibujo propio (indicador y medidores)
def _alert_now():
    """(nivel, texto) de la alerta más grave vigente (0 = todo bien)."""
    now, best = time.monotonic(), (0, "")
    for lvl, txt, t in list(_LEVELS.values()):
        if now - t < 10 and lvl > best[0]:
            best = (lvl, txt)
    return best


_DRAW = {"bg": {}, "fonts": {}, "badge": None, "badge_t": -1e9}


def _rgb(s):
    return tuple(int(c) for c in str(s).split(","))[:3]


def _bg_crop(m, name, box):
    path = m.get_theme_file_path(name)
    im = _DRAW["bg"].get(path)
    if im is None:
        im = _DRAW["bg"][path] = Image.open(path).convert("RGB")
    return im.crop(box)          # RGB: así ImageDraw(…, "RGBA") mezcla las transparencias al dibujar


def _font(rel, size):
    f = _DRAW["fonts"].get((rel, size))
    if f is None:
        f = _DRAW["fonts"][(rel, size)] = ImageFont.truetype(os.path.join(ROOT, "res", "fonts", rel), size)
    return f


def _paint_badge(m, td):
    """Indicador de la cabecera: "SYS OK" en verde, o la alerta vigente en amarillo/rojo. Si el texto del tiempo es
    largo y no hay alerta, el indicador desaparece y en su sitio va el final del texto del tiempo."""
    lvl, txt = _alert_now()
    wx, n = _WX["text"], int(td.get("WX_CHARS", WX_CHARS))
    tail = wx[n:n + 8] if lvl == 0 and len(wx) > n and wx[n:].strip() else ""
    key, now = (lvl, txt, tail), time.monotonic()
    if key == _DRAW["badge"] and now - _DRAW["badge_t"] < 30:
        return
    x, y, w, h = td["X"], td["Y"], td["WIDTH"], td["HEIGHT"]
    img = _bg_crop(m, td.get("BACKGROUND_IMAGE", "background.png"), (x, y, x + w, y + h))
    d = ImageDraw.Draw(img, "RGBA")
    if tail:
        d.text((0, td["BASE"]), tail, font=_font(td["FONT"], td["TAIL_SIZE"]), fill=_rgb(td["TAIL_COLOR"]), anchor="ls")
    else:
        col = _rgb(td["COLOR_CRIT"] if lvl == 2 else td["COLOR_WARN"] if lvl == 1 else td["COLOR_OK"])
        d.rounded_rectangle([12, 12, w - 2, 48], radius=4, fill=(13, 17, 32, 255), outline=col + (255,), width=2)
        if lvl:
            d.polygon([(22, 39), (32, 21), (42, 39)], fill=col + (255,))
            d.text((50, 30), txt[:9], font=_font(td["FONT"], 17), fill=col, anchor="lm")
        else:
            d.ellipse([26, 23, 40, 37], fill=col + (255,))
            d.text((54, 30), "SYS OK", font=_font(td["FONT"], 20), fill=col, anchor="lm")
    m.display.lcd.DisplayPILImage(img.convert("RGB"), x, y)
    _DRAW["badge"], _DRAW["badge_t"] = key, now


def _paint_tol(m, td, f):
    """Medidor de tolerancia (voltajes): zona buena en el centro (20-80 %) y un marcador en la posición del valor."""
    x, y, w, h = td["X"], td["Y"], td["WIDTH"], td["HEIGHT"]
    img = _bg_crop(m, td.get("BACKGROUND_IMAGE", "background.png"), (x - 3, y - 3, x + w + 4, y + h + 4))
    d = ImageDraw.Draw(img, "RGBA")
    base = _rgb(td["BAR_COLOR"])
    col = (_rgb(td.get("COLOR_CRIT", td["BAR_COLOR"])) if f < 20 or f > 80 else
           _rgb(td.get("COLOR_WARN", td["BAR_COLOR"])) if f < 26 or f > 74 else base)
    d.rectangle([3, 3, 3 + w, 3 + h], fill=(4, 6, 14, 255))
    d.rectangle([3 + w * .2, 4, 3 + w * .8, 2 + h], fill=base + (55,))
    d.line([(3 + w * .5, 1), (3 + w * .5, 5 + h)], fill=base + (120,), width=1)
    mx = 3 + max(2.0, min(w - 2.0, w * f / 100.0))
    d.rectangle([mx - 2, 1, mx + 2, 5 + h], fill=col + (255,))
    m.display.lcd.DisplayPILImage(img.convert("RGB"), x - 3, y - 3)


# --------------------------------------------------------------------------- FPS rápidos + cierre seguro
# 1) El proyecto dibuja TODOS los elementos CUSTOM en un solo ciclo (1 vez por segundo + lo que tarde el ciclo).
#    Los cuatro elementos de FPS (cifra, juego, API, frametime y sus gráficas) se redibujan además en su propio
#    hilo cada FAST_MS ms, pero solo si su contenido ha cambiado (si no, no se manda nada a la pantalla).
# 2) Salir/Configurar desde el icono de la bandeja fallaba si el USB daba "Access denied" al apagar la pantalla
#    (el programa no se cerraba nunca): ahora ese error se reintenta y, si persiste, se ignora y se cierra igual.
def _install_fast_fps_and_safe_exit():
    def worker():
        m = None
        for _ in range(600):
            m = sys.modules.get("library.stats")
            if m is not None and hasattr(m, "Custom") and hasattr(m, "display_themed_value"):
                break
            time.sleep(0.1)
        else:
            return
        if getattr(m.Custom.stats, "_gamehud", False):
            return
        cfg_mod = m.config
        sig, err = {}, {"last": -1e9}
        panel_lock = threading.Lock()
        state = {"mode": None, "fast": False}

        def read_one(name):
            obj = getattr(m.sensors_custom, name)()
            num, string, last = obj.as_numeric(), obj.as_string(), obj.last_values()
            if string is None:
                string = str(num)
            sg = (num if num == num else None, string, tuple(last) if last is not None else None)
            return num, string, last, sg

        def paint(theme, num, string, last, name=""):
            td = theme.get("BADGE")
            if td is not None:
                _paint_badge(m, td)
            td = theme.get("TEXT")
            if td is not None and string is not None:
                m.display_themed_value(theme_data=td, value=string)
            td = theme.get("GRAPH")
            if td is not None and num is not None and not math.isnan(num):
                if name.startswith("HudVolt") and _volt_kind(name) == "tol":
                    _paint_tol(m, td, num)                     # voltajes: zona de tolerancia con marcador
                else:
                    m.display_themed_progress_bar(theme_data=td, value=num)
            td = theme.get("RADIAL")
            if td is not None and num is not None and not math.isnan(num) and string is not None:
                m.display_themed_radial_bar(theme_data=td, value=num, custom_text=string)
            td = theme.get("LINE_GRAPH")
            if td is not None and last is not None:
                m.display_themed_line_graph(theme_data=td, values=last)

        def draw_one(name):
            theme = cfg_mod.THEME_DATA["STATS"]["CUSTOM"].get(name)
            if not theme:
                return None
            num, string, last, sg = read_one(name)
            paint(theme, num, string, last, name)
            return sg

        def report(name, e):
            now = time.monotonic()
            if now - err["last"] > 30:
                err["last"] = now
                logger.error("GameHUD: error en el elemento %s: %s", name, e)

        def draw_panel(force):
            """Panel central: en juego muestra FPS y frametime; sin juego, procesos, uptime y cargas CPU/GPU.
            Solo redibuja lo que ha cambiado (force = todo, como hace el ciclo normal cada segundo)."""
            custom = cfg_mod.THEME_DATA["STATS"]["CUSTOM"]
            _rtss_poll()                                           # asegura que el hilo de RTSS está en marcha
            with panel_lock:
                mode = "game" if _RTSS["status"] == "ok" else "idle"
                _TOP["active"] = mode == "idle"
                if mode != state["mode"]:
                    first = state["mode"] is None
                    state["mode"] = mode
                    force = True
                    sig.clear()
                    if mode == "game":                             # la gráfica de FPS empieza limpia en cada juego
                        _STATE.pop("HudFps", None)
                        _STATE.pop("HudFrameTime", None)
                    if not first and "HudHeroClear" in custom:    # borra la zona principal una vez al cambiar de modo
                        try:
                            draw_one("HudHeroClear")
                        except Exception as e:  # noqa
                            report("HudHeroClear", e)
                names = PANEL_ALWAYS + (PANEL_GAME if mode == "game" else PANEL_IDLE)
                for name in names:
                    if name not in custom:
                        continue
                    try:
                        num, string, last, sg = read_one(name)
                        if force or sig.get(name) != sg:
                            paint(custom[name], num, string, last, name)
                            sig[name] = sg
                    except Exception as e:  # noqa
                        report(name, e)

        def slow_stats():
            """Ciclo normal: todos los elementos (si uno falla, se sigue con el siguiente en vez de abortar)."""
            _ensure_fast()
            draw_panel(True)
            for name in list(cfg_mod.THEME_DATA["STATS"]["CUSTOM"]):
                if name == "INTERVAL" or name in PANEL_ALL:
                    continue
                try:
                    draw_one(name)
                except Exception as e:  # noqa
                    report(name, e)

        def fast_loop():
            while True:
                time.sleep(FAST_MS / 1000.0)
                try:
                    draw_panel(False)
                except Exception as e:  # noqa
                    report("panel", e)

        def _ensure_fast():
            if FAST_MS and not state["fast"]:
                state["fast"] = True
                threading.Thread(target=fast_loop, name="GameHUD_fast", daemon=True).start()

        slow_stats._gamehud = True
        m.Custom.stats = staticmethod(slow_stats)
        logger.info("GameHUD: panel central en hilo rápido (%d ms) y ciclo CUSTOM tolerante a errores", FAST_MS)

    threading.Thread(target=worker, name="GameHUD_fast_setup", daemon=True).start()

    try:
        import library.lcd.lcd_comm_turing_usb as t
        cls = t.LcdCommTuringUSB
        if not getattr(cls.ScreenOff, "_gamehud", False):
            orig_off = cls.ScreenOff

            def safe_off(self):
                for i in range(3):
                    try:
                        return orig_off(self)
                    except Exception as e:  # noqa
                        logger.warning("GameHUD: no se pudo apagar la pantalla (intento %d/3): %s", i + 1, e)
                        time.sleep(0.3)
                return None                                  # que el cierre continúe igualmente

            safe_off._gamehud = True
            cls.ScreenOff = safe_off
    except Exception as e:  # noqa
        logger.debug("GameHUD: no se activó el cierre seguro: %s", e)


_install_fast_fps_and_safe_exit()


# --------------------------------------------------------------------------- redibujado selectivo
# Las barras (GRAPH) solo se vuelven a dibujar si su valor cambia de verdad: devolver NaN desde as_numeric()
# hace que el programa se salte ese dibujo. Así las barras de RAM y discos no cuestan nada cuando no se mueven.
_GATE = {}


def _gate(key, v, eps=0.5, max_age=60.0):
    now = time.monotonic()
    last = _GATE.get(key)
    if last and abs(v - last[0]) < eps and now - last[1] < max_age:
        return float("nan")
    _GATE[key] = (v, now)
    return v


# --------------------------------------------------------------------------- base
class _Hud(CustomDataSource):
    TTL = 0.8  # segundos entre lecturas reales (as_numeric/as_string/last_values comparten lectura)
    HIST_DT = 0.0  # si >0: el historial de la gráfica solo avanza un punto cada HIST_DT s aunque se lea más a menudo

    def _read(self) -> float:
        return 0.0

    def _text(self, value: float, ok: bool) -> str:
        return ""

    def _st(self) -> dict:
        s = _STATE.setdefault(type(self).__name__,
                              {"t": -1e9, "v": 0.0, "ok": False, "h": [0.0] * HISTORY})
        now = time.monotonic()
        if now - s["t"] >= self.TTL:
            try:
                v = float(self._read())
                ok = not math.isnan(v)
            except Exception as e:  # noqa
                logger.debug("%s: %s", type(self).__name__, e)
                v, ok = 0.0, False
            if not ok:
                v = 0.0
            s["t"], s["v"], s["ok"] = now, v, ok
            if not self.HIST_DT or now - s.get("th", -1e9) >= self.HIST_DT:
                s["th"] = now
                s["h"].append(v)
                s["h"].pop(0)
        return s

    def as_numeric(self) -> float:
        return self._st()["v"]

    def as_string(self) -> str:
        s = self._st()
        return self._text(s["v"], s["ok"])

    def last_values(self) -> List[float]:
        return list(self._st()["h"])


# --------------------------------------------------------------------------- reloj
_DIAS = ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM"]
_MESES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]


class HudClock(_Hud):
    def as_string(self) -> str:
        return datetime.now().strftime("%H:%M:%S")



def _diag():
    """Vigila el trabajo CUSTOM. Cada 15 ciclos mide cuánto tarda cada uno y la cola hacia la pantalla.
    Solo escribe en el log si algo va mal (ciclos lentos o cola creciente), y como mucho cada 5 minutos;
    más una línea inicial confirmando que todo funciona."""
    now = time.monotonic()
    last, _DIAG["last_call"] = _DIAG["last_call"], now
    # Si entre dos llamadas pasó mucho tiempo (el PC estuvo suspendido), la medida no vale: se empieza de cero
    # (antes salían avisos falsos de "ciclos lentos: 1500 s" al despertar el equipo).
    if _DIAG["t0"] is None or (last is not None and now - last > 20):
        _DIAG.update(t0=now, n=0, frames=0)
        return
    _DIAG["n"] += 1
    if _DIAG["n"] < 15:
        return
    try:
        from library import config
        q = config.update_queue.qsize()
    except Exception:  # noqa
        q = -1
    el = now - _DIAG["t0"]
    cyc, fps = el / _DIAG["n"], _DIAG["frames"] / el
    if (cyc > 1.5 or q > 10) and now - _DIAG["last_log"] > 300:
        logger.warning("GameHUD: ciclos lentos: %.2f s de media, %.1f fotogramas/s, cola = %s", cyc, fps, q)
        _DIAG["last_log"] = now
    elif not _DIAG["reported"]:
        logger.info("GameHUD: funcionamiento normal (ciclo %.2f s, %.1f fotogramas/s)", cyc, fps)
        _DIAG["reported"] = True
    _DIAG["n"], _DIAG["t0"], _DIAG["frames"] = 0, now, 0


class HudDate(_Hud):
    def as_string(self) -> str:
        n = datetime.now()
        return f"{_DIAS[n.weekday()]} {n.day:02d} {_MESES[n.month - 1]} {n.year}"


# --------------------------------------------------------------------------- tiempo exterior (Open-Meteo)
_WX = {"started": False, "text": "CARGANDO..."}


def _wmo(code) -> str:
    c = int(code)
    if c == 0:
        return "DESPEJADO"
    if c <= 3:
        return "NUBES"
    if c in (45, 48):
        return "NIEBLA"
    if 51 <= c <= 57:
        return "LLOVIZNA"
    if 61 <= c <= 67 or 80 <= c <= 82:
        return "LLUVIA"
    if 71 <= c <= 77 or c in (85, 86):
        return "NIEVE"
    if c >= 95:
        return "TORMENTA"
    return ""


def _wx_cfg():
    name, lat, lon = "Madrid", 40.4168, -3.7038         # por defecto; edítalo en gamehud_weather.txt
    try:
        with open(os.path.join(ROOT, "gamehud_weather.txt"), encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = [x.strip() for x in line.split(",")]
                    if len(parts) >= 3:
                        name, lat, lon = parts[0], float(parts[1]), float(parts[2])
                    break
    except (OSError, ValueError):
        pass
    return name, lat, lon


def _wx_loop():
    while True:
        name, lat, lon = _wx_cfg()
        try:
            url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
                   "&current=temperature_2m,weather_code&timezone=auto" % (lat, lon))
            with urllib.request.urlopen(url, timeout=15) as r:
                cur = json.loads(r.read().decode("utf-8"))["current"]
            _WX["text"] = (f"{name[:7].upper()} {cur['temperature_2m']:.0f}°C "
                           f"{_wmo(cur['weather_code'])}").strip()
            wait = 600
        except Exception as e:  # noqa
            logger.warning("GameHUD: no se pudo obtener el tiempo: %s", e)
            if _WX["text"].startswith("CARGANDO"):
                _WX["text"] = f"{name[:7].upper()} --°C"
            wait = 120
        time.sleep(wait)


class HudWeather(_Hud):
    def as_string(self) -> str:
        _diag()
        if not _WX["started"]:
            _WX["started"] = True
            threading.Thread(target=_wx_loop, daemon=True).start()
        wx = _WX["text"]
        if len(wx) > WX_CHARS:                    # no cabe junto al indicador de estado
            cut = wx[:WX_CHARS]                   # sin alerta: el resto lo dibuja el propio indicador (que desaparece)
            if _alert_now()[0] and " " in cut:    # con alerta: manda la alerta y el tiempo se corta por palabra
                cut = cut.rsplit(" ", 1)[0]
            return cut
        return wx


# --------------------------------------------------------------------------- resolución y Hz del monitor
class _DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", ctypes.c_ushort),
        ("dmDriverVersion", ctypes.c_ushort), ("dmSize", ctypes.c_ushort), ("dmDriverExtra", ctypes.c_ushort),
        ("dmFields", ctypes.c_uint32), ("dmPositionX", ctypes.c_int32), ("dmPositionY", ctypes.c_int32),
        ("dmDisplayOrientation", ctypes.c_uint32), ("dmDisplayFixedOutput", ctypes.c_uint32),
        ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
        ("dmLogPixels", ctypes.c_ushort), ("dmBitsPerPel", ctypes.c_uint32), ("dmPelsWidth", ctypes.c_uint32),
        ("dmPelsHeight", ctypes.c_uint32), ("dmDisplayFlags", ctypes.c_uint32),
        ("dmDisplayFrequency", ctypes.c_uint32), ("dmICMMethod", ctypes.c_uint32),
        ("dmICMIntent", ctypes.c_uint32), ("dmMediaType", ctypes.c_uint32), ("dmDitherType", ctypes.c_uint32),
        ("dmReserved1", ctypes.c_uint32), ("dmReserved2", ctypes.c_uint32),
        ("dmPanningWidth", ctypes.c_uint32), ("dmPanningHeight", ctypes.c_uint32),
    ]


_DM = {"t": -1e9, "text": "N/D"}


class HudDisplayMode(_Hud):
    def as_string(self) -> str:
        now = time.monotonic()
        if now - _DM["t"] >= 5.0 and sys.platform == "win32":
            _DM["t"] = now
            try:
                fn = ctypes.windll.user32.EnumDisplaySettingsW
                fn.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(_DEVMODEW)]
                dm = _DEVMODEW()
                dm.dmSize = ctypes.sizeof(_DEVMODEW)
                if fn(None, 0xFFFFFFFF, ctypes.byref(dm)):          # ENUM_CURRENT_SETTINGS
                    _DM["text"] = f"{dm.dmPelsWidth}x{dm.dmPelsHeight} @ {dm.dmDisplayFrequency}Hz"
            except Exception as e:  # noqa
                logger.debug("GameHUD: resolución/Hz: %s", e)
        return _DM["text"]


# --------------------------------------------------------------------------- núcleos
NBARS = 16                       # una barra por hilo (9800X3D: 8 núcleos x 2); debe coincidir con NBARS del instalador
CORE_ROWS = 3                    # y con ROWS del instalador (filas de bloques: 8 niveles cada una)
_BLK = " ▁▂▃▄▅▆▇█"
_CORES = {"t": -1e9, "v": [0.0] * NBARS, "avg": 0.0}


def _core_loads():
    now = time.monotonic()
    if now - _CORES["t"] >= 0.8:
        p = (list(psutil.cpu_percent(percpu=True)) + [0.0] * NBARS)[:NBARS]     # un valor por hilo lógico
        shown = _CORES["v"]
        # estilo ecualizador: sube rápido, baja despacio (con muestras de ~1 s las barras saltarían mucho)
        _CORES["v"] = [o + (n - o) * (CORE_RISE if n > o else CORE_FALL) for o, n in zip(shown, p)]
        _CORES["avg"] = sum(p) / len(p)                  # carga media real (sin suavizar), para la gráfica de reposo
        _CORES["t"] = now
    return _CORES["v"]


class _CoreRow(_Hud):
    ROW = 0  # 0 = fila de abajo (niveles 1-8), 1 = media (9-16), 2 = arriba (17-24)

    def as_numeric(self) -> float:
        return 0.0

    def as_string(self) -> str:
        cells = []
        for p in _core_loads():
            h = max(1, round(p / 100 * 8 * CORE_ROWS))
            cells.append(_BLK[max(0, min(8, h - 8 * self.ROW))])
        return " ".join(cells)


class HudCoreRow0(_CoreRow): ROW = 0
class HudCoreRow1(_CoreRow): ROW = 1
class HudCoreRow2(_CoreRow): ROW = 2


# --------------------------------------------------------------------------- RAM
class HudRamPercent(_Hud):
    def _read(self):
        return psutil.virtual_memory().percent

    def as_numeric(self) -> float:
        return _gate("ram", self._st()["v"])

    def _text(self, v, ok):
        return _tag(v, f"{v:>3.0f}%")


class HudRamDetail(_Hud):
    def _read(self):
        return psutil.virtual_memory().percent

    def as_string(self) -> str:
        m = psutil.virtual_memory()
        return f"{m.used / 2**30:4.1f} / {m.total / 2**30:4.1f} GB"


# --------------------------------------------------------------------------- red
_NET = {"t": 0.0, "rx": 0, "tx": 0, "down": 0.0, "up": 0.0}


def _net_rates():
    now = time.monotonic()
    if now - _NET["t"] >= 0.5:
        c = psutil.net_io_counters()
        if _NET["t"] > 0:
            dt = max(now - _NET["t"], 1e-3)
            _NET["down"] = max(c.bytes_recv - _NET["rx"], 0) / dt
            _NET["up"] = max(c.bytes_sent - _NET["tx"], 0) / dt
        _NET["t"], _NET["rx"], _NET["tx"] = now, c.bytes_recv, c.bytes_sent
    return _NET["down"], _NET["up"]


def _fmt_rate(bps: float) -> str:
    if bps >= 1e6:
        return f"{bps / 1e6:6.1f} MB/s"
    return f"{bps / 1e3:6.1f} KB/s"


class HudNetDown(_Hud):
    def _read(self):
        return _net_rates()[0] / 1e6  # MB/s (para la gráfica)

    def _text(self, v, ok):
        return "DL " + _fmt_rate(_net_rates()[0])


class HudNetUp(_Hud):
    def _read(self):
        return _net_rates()[1] / 1e6

    def _text(self, v, ok):
        return "UL " + _fmt_rate(_net_rates()[1])


# --------------------------------------------------------------------------- RTSS (FPS)
_RTSS = {"t": -1e9, "status": "off", "fps": 0.0, "name": "", "ft": 0.0, "api": "", "seen": {}, "started": False}
RTSS_POLL_MS = 100     # cada cuánto se lee la memoria compartida de RTSS (en su propio hilo)
RTSS_STALE = 2.0       # segundos sin que RTSS actualice a una aplicación para darla por parada (antes 3 s)
FAST_MS = 250          # los elementos de FPS se redibujan en su propio hilo cada FAST_MS ms si han cambiado (0 = off)
HIST_SPAN = "60 SEC"   # lo que abarcan las gráficas (60 puntos a ~1 por segundo); debe coincidir con el instalador
# Panel central (FPS): qué elementos se dibujan en cada modo. Los de "reposo" solo existen si el tema los trae.
PANEL_ALWAYS = ["HudFpsTitle", "HudFpsApi", "HudFpsGame", "HudFpsLabel1", "HudFpsLabel2", "HudFpsStats"]
PANEL_GAME = ["HudFps", "HudFrameTime"]
PANEL_IDLE = (["HudUptime", "HudIdleCpu", "HudIdleGpu", "HudTopH0", "HudTopH1", "HudTopH2"] +
              [f"HudTop{k}{i}" for i in range(1, 5) for k in "NCM"])
PANEL_ALL = set(PANEL_ALWAYS) | set(PANEL_GAME) | set(PANEL_IDLE) | {"HudHeroClear"}

# Valores (no bits) del campo API de dwFlags: se obtienen con  dwFlags & 0x0000FFFF  (APPFLAG_API_USAGE_MASK)
_RTSS_API = {1: "OPENGL", 2: "DDRAW", 3: "D3D8", 4: "D3D9", 5: "D3D9EX", 6: "D3D10", 7: "D3D11", 8: "D3D12",
             9: "D3D12 AFR", 10: "VULKAN"}

# Procesos que RTSS suele enganchar pero que no son el juego (navegadores, lanzadores, overlays...)
_FPS_IGNORE = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "discord.exe",
               "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "epicwebhelper.exe", "galaxyclient.exe",
               "upc.exe", "ubisoftconnect.exe", "battle.net.exe", "ealauncher.exe", "wallpaper32.exe",
               "wallpaper64.exe", "explorer.exe", "dwm.exe", "applicationframehost.exe", "searchhost.exe",
               "startmenuexperiencehost.exe", "msiafterburner.exe", "rtss.exe", "obs64.exe", "spotify.exe",
               "teams.exe", "ms-teams.exe", "slack.exe", "code.exe", "whatsapp.exe", "telegram.exe"}
_FPSCFG = {"t": -1e9, "ignore": set(_FPS_IGNORE), "only_fg": False}


def _fps_cfg():
    """gamehud_fps.txt:  ignore = a.exe, b.exe   (se suman a la lista por defecto)   |   only_foreground = yes"""
    now = time.monotonic()
    if now - _FPSCFG["t"] < 20:
        return _FPSCFG
    ignore, only_fg = set(_FPS_IGNORE), False
    try:
        with open(os.path.join(ROOT, "gamehud_fps.txt"), encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = [x.strip().lower() for x in line.split("=", 1)]
                if k == "ignore":
                    ignore |= {x.strip() for x in v.split(",") if x.strip()}
                elif k == "only_foreground":
                    only_fg = v in ("yes", "si", "sí", "true", "1", "on")
    except OSError:
        pass
    _FPSCFG.update(t=now, ignore=ignore, only_fg=only_fg)
    return _FPSCFG


def _foreground_pid():
    """PID de la ventana en primer plano (el método que usa el propio RTSS/Afterburner para 'el juego en pantalla')."""
    if sys.platform != "win32":
        return 0
    try:
        u32 = ctypes.windll.user32
        hwnd = u32.GetForegroundWindow()
        pid = ctypes.c_uint32(0)
        if hwnd:
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value
    except Exception:  # noqa
        return 0


def _rtss_scan(read, now, fg_pid=0):
    """Interpreta la memoria compartida de RTSS. read(offset, n) -> bytes.
    Devuelve (estado, fps, nombre, frametime_ms, api); estado: 'off', 'idle' o 'ok'.
    Elige la aplicación en primer plano; si no es una de las enganchadas (o está en la lista de ignoradas) usa la
    más reciente de las demás que no estén ignoradas (a no ser que only_foreground = yes)."""
    sig, ver, esz, eoff, ecnt = struct.unpack("<5I", read(0, 20))
    if sig != 0x52545353 or ver < 0x00020000 or esz < 284:
        return "off", 0.0, "", 0.0, ""
    cfg = _fps_cfg()
    cands = []
    for i in range(min(ecnt, 256)):
        e = read(eoff + i * esz, 284)
        pid = struct.unpack_from("<I", e, 0)[0]
        if pid == 0:
            continue
        nm = e[4:264].split(b"\0", 1)[0].decode("mbcs" if sys.platform == "win32" else "utf-8", "ignore")
        flags = struct.unpack_from("<I", e, 264)[0]
        t0, t1, frames, ftime = struct.unpack_from("<4I", e, 268)   # dwTime0, dwTime1, dwFrames, dwFrameTime(us)
        if not nm or t1 <= t0 or frames == 0:
            continue
        # "activo" = su contador t1 ha cambiado en los últimos 3 s
        prev = _RTSS["seen"].get(pid)
        if prev is None or prev[0] != t1:
            _RTSS["seen"][pid] = (t1, now)
            changed = now
        else:
            changed = prev[1]
        if now - changed > RTSS_STALE or not psutil.pid_exists(pid):    # parada, o el juego ya se cerró
            continue
        f = 1000.0 * frames / (t1 - t0)
        ft = ftime / 1000.0 if 0 < ftime < 1_000_000 else (1000.0 / f if f > 0 else 0.0)
        base = os.path.basename(nm)
        cands.append((pid, base, f, ft, _RTSS_API.get(flags & 0x0000FFFF, ""), changed))
    usable = [c for c in cands if c[1].lower() not in cfg["ignore"]]
    best = next((c for c in usable if c[0] == fg_pid), None)             # 1) la ventana en primer plano
    if best is None and not cfg["only_fg"] and usable:                    # 2) si no, la más reciente no ignorada
        best = max(usable, key=lambda c: c[5])
    if best:
        return "ok", best[2], best[1], best[3], best[4]
    return "idle", 0.0, "", 0.0, ""


def _rtss_read_once():
    now = time.monotonic()
    status, fps, name, ft, api = "off", 0.0, "", 0.0, ""
    if sys.platform == "win32":
        k32 = ctypes.windll.kernel32
        k32.OpenFileMappingW.restype = ctypes.c_void_p
        k32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
        k32.MapViewOfFile.restype = ctypes.c_void_p
        k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.c_uint32, ctypes.c_size_t]
        k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.OpenFileMappingW(0x0004, 0, "RTSSSharedMemoryV2")  # FILE_MAP_READ
        if h:
            p = k32.MapViewOfFile(h, 0x0004, 0, 0, 0)
            if p:
                try:
                    status, fps, name, ft, api = _rtss_scan(lambda off, n: ctypes.string_at(p + off, n), now,
                                                            _foreground_pid())
                finally:
                    k32.UnmapViewOfFile(p)
            k32.CloseHandle(h)
    _RTSS.update(status=status, fps=fps, name=name, ft=ft, api=api, t=now)


_FSAMP = collections.deque()      # (instante, fps) de los últimos 60 s del juego actual


def _fps_sample():
    now = time.monotonic()
    if _RTSS["status"] == "ok" and _RTSS["fps"] > 0:
        _FSAMP.append((now, _RTSS["fps"]))
        while _FSAMP and now - _FSAMP[0][0] > 60:
            _FSAMP.popleft()
    elif _FSAMP:
        _FSAMP.clear()


def _rtss_loop():
    """Hilo propio: lee RTSS cada RTSS_POLL_MS ms sin depender del ciclo de dibujo (que puede ir lento con el
    juego a tope). Así entrar o salir de un juego se nota en décimas de segundo."""
    while True:
        try:
            _rtss_read_once()
            _fps_sample()
            if len(_RTSS["seen"]) > 64:                       # limpia procesos viejos
                _RTSS["seen"] = {k: v for k, v in _RTSS["seen"].items() if psutil.pid_exists(k)}
        except Exception as e:  # noqa
            logger.debug("GameHUD: lectura RTSS: %s", e)
        time.sleep(RTSS_POLL_MS / 1000.0)


def _rtss_poll():
    """Devuelve (estado, fps, nombre) de la última lectura. El frametime queda en _RTSS['ft']."""
    if not _RTSS["started"]:
        _RTSS["started"] = True
        threading.Thread(target=_rtss_loop, name="GameHUD_rtss", daemon=True).start()
    return _RTSS["status"], _RTSS["fps"], _RTSS["name"]


class HudFps(_Hud):
    TTL = 0.05          # lee la caché del hilo RTSS (gratis)
    HIST_DT = 0.95      # la gráfica de 60 s avanza un punto por segundo aunque se dibuje más a menudo

    def _read(self):
        status, fps, _ = _rtss_poll()
        return fps if status == "ok" else 0.0

    def _text(self, v, ok):
        return _tag(v, f"{v:>3.0f}") if v > 0 else "---"


class HudFrameTime(_Hud):
    TTL = 0.05
    HIST_DT = 0.95

    def _read(self):
        status, _, _ = _rtss_poll()
        return _RTSS["ft"] if status == "ok" else 0.0

    def _text(self, v, ok):
        return _tag(v, f"FT {v:5.1f} ms") if v > 0 else "FT   --- ms"


class HudFpsApi(_Hud):
    """API gráfica del juego (D3D11, D3D12, VULKAN...) tal y como la indica RTSS."""
    def as_string(self) -> str:
        status, _, _ = _rtss_poll()
        return _RTSS["api"] if status == "ok" and _RTSS["api"] else " "


class HudFpsGame(_Hud):
    def as_string(self) -> str:
        status, _, name = _rtss_poll()
        if status == "off":
            return "RTSS NO ACTIVO"
        if status == "idle":
            return "SIN JUEGO"
        return name[:16].upper()


def _in_game() -> bool:
    return _RTSS["status"] == "ok"


class HudFpsTitle(_Hud):
    def as_string(self) -> str:
        return "FPS // FRAME RATE" if _in_game() else "SYS // STANDBY"


class HudFpsLabel1(_Hud):
    def as_string(self) -> str:
        return f"FPS · {HIST_SPAN}" if _in_game() else f"CPU · {HIST_SPAN}"


class HudFpsLabel2(_Hud):
    def as_string(self) -> str:
        return "FRAMETIME · MS" if _in_game() else f"GPU · {HIST_SPAN}"


class _TextOnly(_Hud):
    """Elemento solo de texto: sin historial (no hace falta guardar nada)."""
    def as_numeric(self) -> float:
        return 0.0

    def last_values(self):
        return None


class HudFpsStats(_TextOnly):
    """Media y mínimo de FPS de los últimos 60 s (lecturas de RTSS cada 0,1 s: el mínimo es aproximado)."""
    def as_string(self) -> str:
        vals = [v for _, v in list(_FSAMP)]
        if not _in_game() or len(vals) < 10:
            return " "
        return f"AVG {sum(vals) / len(vals):.0f} · MIN {min(vals):.0f}"


class HudStatus(_TextOnly):
    """Indicador de estado de la cabecera: lo dibuja _paint_badge (clave BADGE del tema)."""
    def as_string(self) -> str:
        return " "


class HudHeroClear(_TextOnly):
    """Texto en blanco del tamaño de la zona principal: se dibuja una vez al cambiar entre juego y reposo."""
    def as_string(self) -> str:
        return " "


def _uptime_text() -> str:
    try:
        sec = max(0, int(time.time() - psutil.boot_time()))
    except Exception:  # noqa
        return "UP --:--"
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    return f"UP {d}d {h:02d}:{rem // 60:02d}" if d else f"UP {h:02d}:{rem // 60:02d}"


class HudUptime(_TextOnly):
    def as_string(self) -> str:
        return _uptime_text()


class _LoadHist(_Hud):
    TTL = 0.9
    HIST_DT = 0.9


class HudIdleCpu(_LoadHist):
    def _read(self):
        _core_loads()
        return _CORES["avg"]


class HudIdleGpu(_LoadHist):
    def _read(self):
        for h, t, n, v in _lhm_walk():
            if h.startswith("Gpu") and t == "Load" and n == "GPU Core":
                return v
        return 0.0


# ---- procesos que más consumen (solo se calcula mientras no hay juego: en juego no cuesta nada)
_TOP = {"active": False, "rows": [], "started": False, "primed": False}
_TOP_SKIP = {"system idle process", "system", "registry", "memory compression", "secure system", "idle"}


def _top_loop():
    ncpu = max(1, psutil.cpu_count() or 1)
    was_active = False
    while True:
        if not _TOP["active"]:
            was_active = False
            time.sleep(0.5)
            continue
        try:
            agg = {}
            for p in psutil.process_iter(["name", "memory_info"]):
                try:
                    nm = p.info.get("name") or ""
                    if not nm or nm.lower() in _TOP_SKIP:
                        continue
                    cpu = p.cpu_percent(None) / ncpu
                    mi = p.info.get("memory_info")
                    row = agg.setdefault(nm.upper(), [0.0, 0])
                    row[0] += cpu
                    row[1] += mi.rss if mi else 0
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            if was_active:                                   # la 1.ª pasada solo "arma" cpu_percent: no se publica
                top = sorted(agg.items(), key=lambda kv: (round(kv[1][0]), kv[1][1]), reverse=True)[:4]
                _TOP["rows"] = [(n[:14], c, mem) for n, (c, mem) in top]
            was_active = True
        except Exception as e:  # noqa
            logger.debug("GameHUD: procesos: %s", e)
        time.sleep(2.0)


def _top_rows():
    if not _TOP["started"]:
        _TOP["started"] = True
        threading.Thread(target=_top_loop, name="GameHUD_top", daemon=True).start()
    return _TOP["rows"]


def _fmt_mem(b: float) -> str:
    mb = b / (1024 * 1024)
    return f"{mb / 1024:.1f} GB" if mb >= 1000 else f"{mb:.0f} MB"


class _TopCell(_TextOnly):
    I = 0     # fila (0-3)
    K = "N"   # N nombre, C cpu, M memoria

    def as_string(self) -> str:
        rows = _top_rows()
        if self.I >= len(rows):
            return " "
        n, c, mem = rows[self.I]
        return n if self.K == "N" else f"{c:.0f}%" if self.K == "C" else _fmt_mem(mem)


class _TopHdr(_TextOnly):
    TXT = " "

    def as_string(self) -> str:
        _top_rows()                                           # arranca el hilo la primera vez
        return self.TXT


class HudTopH0(_TopHdr): TXT = "TOP PROCESOS"
class HudTopH1(_TopHdr): TXT = "CPU"
class HudTopH2(_TopHdr): TXT = "MEM"


for _i in range(4):
    for _k in "NCM":
        _nm = f"HudTop{_k}{_i + 1}"
        globals()[_nm] = type(_nm, (_TopCell,), {"I": _i, "K": _k})
        __all__.append(_nm)


# ---- IP pública de la conexión (o IP local del router), según gamehud_ip.txt
_IP = {"started": False, "gw": None, "pub": None, "mode": "public", "cfg_t": -1e9, "pub_t": -1e9}


def _ip_cfg():
    now = time.monotonic()
    if now - _IP["cfg_t"] < 30:
        return
    _IP["cfg_t"] = now
    try:
        with open(os.path.join(ROOT, "gamehud_ip.txt"), encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = [x.strip().lower() for x in line.split("=", 1)]
                    if k == "mode" and v in ("gateway", "public"):
                        _IP["mode"] = v
    except OSError:
        pass


def _default_gateway():
    """IP de la puerta de enlace por defecto (la del router). Con varias rutas (VPN...) gana la de menor métrica."""
    import subprocess
    if sys.platform == "win32":
        out = subprocess.run(["route", "print", "-4", "0.0.0.0"], capture_output=True, text=True, timeout=8,
                             creationflags=0x08000000).stdout          # CREATE_NO_WINDOW: sin parpadeo de consola
        best = None
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                try:
                    metric = int(parts[4])
                except ValueError:
                    continue
                if parts[2] != "On-link" and (best is None or metric < best[0]):
                    best = (metric, parts[2])
        return best[1] if best else None
    out = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=8).stdout
    toks = out.split()
    return toks[toks.index("via") + 1] if "via" in toks else None


def _public_ip():
    import urllib.request
    with urllib.request.urlopen("https://api.ipify.org", timeout=6) as r:
        return r.read().decode().strip()[:15]


def _ip_loop():
    while True:
        _ip_cfg()
        if _IP["mode"] == "gateway":
            try:
                _IP["gw"] = _default_gateway()
            except Exception as e:  # noqa
                logger.debug("GameHUD: puerta de enlace: %s", e)
                _IP["gw"] = None
        if _IP["mode"] == "public" and time.monotonic() - _IP["pub_t"] > 600:   # la IP pública se pide cada 10 min
            _IP["pub_t"] = time.monotonic()
            try:
                _IP["pub"] = _public_ip()
            except Exception as e:  # noqa
                logger.debug("GameHUD: IP pública: %s", e)
                _IP["pub_t"] = time.monotonic() - 540                           # y si falla, reintenta en 1 min
        time.sleep(20)


class HudRouterIp(_TextOnly):
    def as_string(self) -> str:
        if not _IP["started"]:
            _IP["started"] = True
            threading.Thread(target=_ip_loop, name="GameHUD_ip", daemon=True).start()
        if _IP["mode"] == "public":
            return f"WAN {_IP['pub'] or '---'}"
        return f"GW  {_IP['gw'] or '---'}"


# --------------------------------------------------------------------------- voltajes (LHM)
_LHM = {"tried": False, "pc": None, "err": ""}
_VOLT = {"t": -1e9, "v": [], "pos": []}


def _lhm_computer():
    if _LHM["tried"]:
        return _LHM["pc"]
    _LHM["tried"] = True
    try:
        import clr  # pythonnet
        try:
            from LibreHardwareMonitor import Hardware
        except Exception:
            base = os.path.join(ROOT, "external", "LibreHardwareMonitor", "LibreHardwareMonitorLib")
            try:
                clr.AddReference(base)
            except Exception:
                clr.AddReference(base + ".dll")
            from LibreHardwareMonitor import Hardware
        pc = Hardware.Computer()
        pc.IsMotherboardEnabled = True
        pc.IsGpuEnabled = True
        pc.IsCpuEnabled = True
        pc.Open()
        _LHM["pc"] = pc
    except Exception as e:  # noqa
        _LHM["err"] = repr(e)
        logger.warning("GameHUD: no se pueden leer voltajes (LibreHardwareMonitor): %s", e)
    return _LHM["pc"]


_WALK = {"v": [], "started": False}


def _lhm_collect():
    out = []
    pc = _lhm_computer()
    if pc is not None:
        def walk(hw, root):
            hw.Update()
            for sn in hw.Sensors:
                if sn.Value is not None:
                    out.append((root, str(sn.SensorType), str(sn.Name), float(sn.Value)))
            for sub in hw.SubHardware:
                walk(sub, root)
        for hw in pc.Hardware:
            walk(hw, str(hw.HardwareType))
    return out


def _lhm_loop():
    """Hilo propio: LibreHardwareMonitor tarda (cientos de ms) y más aún con el juego cargando la CPU; antes eso
    bloqueaba el ciclo de dibujo entero. Ahora el dibujo solo lee la última foto de los sensores."""
    while True:
        try:
            _WALK["v"] = _lhm_collect()
        except Exception as e:  # noqa
            logger.debug("GameHUD: lectura LHM: %s", e)
        time.sleep(1.0)


def _lhm_walk():
    """[(tipo_hardware, tipo_sensor, nombre, valor)] de la placa y la GPU (última lectura, ~1 s)."""
    if not _WALK["started"]:
        _WALK["started"] = True
        threading.Thread(target=_lhm_loop, name="GameHUD_lhm", daemon=True).start()
    return _WALK["v"]


def all_voltages():
    """Lista de (nombre, voltios) de los sensores de voltaje de la placa que ve LHM."""
    return [(n, v) for h, t, n, v in _lhm_walk() if t == "Voltage" and h == "Motherboard"]


def gpu_info():
    """(reloj_memoria_MHz, vram_usada_MB, vram_total_MB); None si LHM no lo expone."""
    rows = [(t, n.lower(), v) for h, t, n, v in _lhm_walk() if h.startswith("Gpu")]
    clk = next((v for t, n, v in rows if t == "Clock" and "memory" in n), None)

    def mem(word):
        return next((v for t, n, v in rows
                     if t == "SmallData" and "memory" in n and word in n and "shared" not in n), None)

    used, total, free = mem("used"), mem("total"), mem("free")
    if total is None and used is not None and free is not None:
        total = used + free
    return clk, used, total


_UNIT = {"Voltage": "V", "Power": "W", "Current": "A"}


def all_metrics():
    """[(hardware, nombre, valor, unidad)] de voltajes, potencias y corrientes de la placa y la GPU (placa primero)."""
    out = [(h, n, v, _UNIT[t]) for h, t, n, v in _lhm_walk()
           if t in _UNIT and (h in ("Motherboard", "Cpu") or h.startswith("Gpu"))]
    out.sort(key=lambda r: {"Motherboard": 0, "Cpu": 1}.get(r[0], 2))
    return out


_HWPREFIX = {"cpu": "Cpu", "gpu": "Gpu", "mb": "Motherboard"}


def _find_metric(ms, spec, hw=None):
    """Primer sensor cuyo nombre contenga alguna de las alternativas de 'spec' (separadas por comas, por orden).
    Cada alternativa puede llevar un prefijo cpu: / gpu: / mb: para limitarla a ese hardware."""
    for alt in [x.strip() for x in spec.split(",") if x.strip()]:
        h2 = hw
        pre, sep, rest = alt.partition(":")
        if sep and pre.strip().lower() in _HWPREFIX:
            h2, alt = _HWPREFIX[pre.strip().lower()], rest.strip()
        for h, n, v, u in ms:
            if (h2 is None or h.startswith(h2)) and alt.lower() in n.lower():
                return n, v, u
    return None


# Orden de preferencia cuando no hay gamehud_voltages.txt (Vcore y el voltaje de la GPU salen en sus paneles; el DIMM en el de RAM)
_VOLT_DEFAULT = [("+12v", None, "Motherboard"), ("+5v", None, "Motherboard"), ("soc", "VSoC", "Motherboard"),
                 ("package", "CPU PWR", "Cpu"),             # potencia del procesador (si LHM la expone)
                 ("package", "GPU PWR", "Gpu"),             # potencia total de la GPU que da el controlador
                 ("+3.3v", None, "Motherboard")]


_HIDDEN = set()
# Medidor a la derecha de cada fila del panel POWER (3.ª columna opcional de gamehud_voltages.txt):
#   nominal=12 tol=5   -> ventana de tolerancia (±5 %): la barra indica en qué punto de la ventana está el valor
#   max=160            -> la barra se llena hasta ese máximo
#   off                -> sin medidor
# Si la línea no lo indica se usa uno por defecto según el sensor.
_GAUGE_DEFAULT = [("+12v", ("tol", 12.0, 5.0)), ("+5v", ("tol", 5.0, 5.0)), ("+3.3v", ("tol", 3.3, 5.0)),
                  ("soc", ("max", 1.30)), ("northbridge", ("max", 1.30)),
                  ("cpu:package", ("max", 160.0)), ("gpu:package", ("max", 300.0))]


def _parse_gauge(spec, opts):
    toks = {}
    for t in (opts or "").replace(",", " ").split():
        k, _, v = t.partition("=")
        toks[k.lower()] = v
    if "off" in toks:
        return None
    try:
        if "max" in toks:
            return ("max", float(toks["max"]))
        if "nominal" in toks:
            return ("tol", float(toks["nominal"]), float(toks.get("tol", 5)))
    except ValueError:
        return None
    low = spec.lower()
    return next((g for k, g in _GAUGE_DEFAULT if k in low), None)


def _gauge_pos(value, g):
    """Posición 0-100 del valor en su medidor (None si no hay medidor o no hay valor)."""
    if g is None or value is None or value != value:
        return None
    if g[0] == "max":
        pos = value / g[1] * 100.0 if g[1] else 0.0
    else:                                                    # tolerancia: el límite inferior cae en 20 y el superior en 80
        lo, hi = g[1] * (1 - g[2] / 100.0), g[1] * (1 + g[2] / 100.0)
        pos = 20.0 + 60.0 * (value - lo) / (hi - lo) if hi > lo else 0.0
    return max(0.0, min(100.0, pos))


def _picked_voltages():
    """[(etiqueta, valor, unidad)] de las filas del panel POWER (la posición de cada medidor queda en _VOLT['pos'])."""
    now = time.monotonic()
    if now - _VOLT["t"] < 1.0:
        return _VOLT["v"]
    _VOLT["t"] = now
    ms = all_metrics()
    wanted = []
    cfg = os.path.join(ROOT, "gamehud_voltages.txt")  # opcional: "alternativa1, alternativa2 | etiqueta | medidor"
    if os.path.isfile(cfg):
        with open(cfg, encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = [x.strip() for x in line.split("|")]
                    wanted.append((parts[0], (parts[1] if len(parts) > 1 else "") or None,
                                   parts[2] if len(parts) > 2 else ""))
    picked, pos, kind = [], [], []
    if wanted:
        for spec, lab, opts in wanted[:POWER_ROWS]:
            hit = _find_metric(ms, spec)
            if hit is None and ms:                           # LHM ya responde pero no tiene ese sensor: se oculta la fila
                if spec not in _HIDDEN:
                    _HIDDEN.add(spec)
                    logger.info("GameHUD: fila POWER oculta (sin sensor): %s", spec)
                continue
            picked.append((lab or (hit[0] if hit else spec.split(",")[0].strip()),
                           hit[1] if hit else float("nan"), hit[2] if hit else "V"))
            g = _parse_gauge(spec, opts)
            pos.append(_gauge_pos(hit[1] if hit else None, g))
            kind.append(g[0] if g else None)
    else:
        for spec, lab, hw in _VOLT_DEFAULT:
            hit = _find_metric(ms, spec, hw)
            if hit and len(picked) < POWER_ROWS:
                picked.append((lab or hit[0], hit[1], hit[2]))
                g = _parse_gauge({"package": "cpu:package" if hw == "Cpu" else "gpu:package"}.get(spec, spec), "")
                pos.append(_gauge_pos(hit[1], g))
                kind.append(g[0] if g else None)
        for h, n, v, u in ms:                              # si faltan, se completa con voltajes de la placa
            if len(picked) < POWER_ROWS and u == "V" and v > 0.2 and h == "Motherboard" and n not in [p[0] for p in picked]:
                picked.append((n, v, u))
                g = _parse_gauge(n, "")
                pos.append(_gauge_pos(v, g))
                kind.append(g[0] if g else None)
    _VOLT["v"], _VOLT["pos"], _VOLT["kind"] = picked, pos, kind
    return picked


def _volt_kind(name):
    try:
        return _VOLT.get("kind", [])[int(name[7:]) - 1]
    except (ValueError, IndexError):
        return None


class _Volt(_Hud):
    IDX = 0
    TTL = 1.0

    def _row(self):
        vs = _picked_voltages()
        return vs[self.IDX] if self.IDX < len(vs) else None

    def _read(self):
        r = self._row()
        return r[1] if r else 0.0

    def as_numeric(self) -> float:
        """Posición 0-100 en el medidor de la fila (NaN = nada que dibujar)."""
        self._row()
        pos = _VOLT.get("pos", [])
        p = pos[self.IDX] if self.IDX < len(pos) else None
        return float("nan") if p is None else _gate(f"volt{self.IDX}", p, 0.8, 10.0)

    def as_string(self) -> str:
        r = self._row()
        if r is None:
            return "SIN DATOS LHM" if self.IDX == 0 else " "
        n, v, u = r
        if math.isnan(v):
            return f"{n[:11]:<11}   N/A"
        return f"{n[:11]:<11}" + {"V": f"{v:6.3f} V", "W": f"{v:6.1f} W", "A": f"{v:6.2f} A"}[u]


class HudVolt1(_Volt): IDX = 0
class HudVolt2(_Volt): IDX = 1
class HudVolt3(_Volt): IDX = 2
class HudVolt4(_Volt): IDX = 3
class HudVolt5(_Volt): IDX = 4
class HudVolt6(_Volt): IDX = 5


# --------------------------------------------------------------------------- relojes en MHz
def cpu_clock_mhz():
    vals = [v for h, t, n, v in _lhm_walk()
            if h == "Cpu" and t == "Clock" and n.startswith("Core #") and "effective" not in n.lower() and v > 0]
    if vals:
        return sum(vals) / len(vals)
    f = psutil.cpu_freq()
    return float(f.current) if f else 0.0


def gpu_clock_mhz():
    rows = [(n.lower(), v) for h, t, n, v in _lhm_walk() if h.startswith("Gpu") and t == "Clock"]
    return next((v for n, v in rows if "core" in n), 0.0)


class HudCpuClock(_Hud):
    TTL = 1.0

    def _read(self):
        return cpu_clock_mhz()

    def _text(self, v, ok):
        return f"{v:>4.0f} MHz" if v > 0 else "N/D"


class HudGpuClock(_Hud):
    TTL = 1.0

    def _read(self):
        return gpu_clock_mhz()

    def _text(self, v, ok):
        return f"{v:>4.0f} MHz" if v > 0 else "N/D"


# --------------------------------------------------------------------------- GPU: reloj de memoria y VRAM
class HudGpuMemClock(_Hud):
    TTL = 1.0

    def _read(self):
        return gpu_info()[0] or 0.0

    def _text(self, v, ok):
        return f"{v:>5.0f} MHz" if v > 0 else "  N/D"


class HudVram(_Hud):
    TTL = 1.0

    def _read(self):
        _, used, total = gpu_info()
        return 100.0 * used / total if used is not None and total else 0.0

    def _text(self, v, ok):
        _, used, total = gpu_info()
        if used is None or not total:
            return "N/D"
        return _tag(v, f"{used / 1024:4.1f}/{total / 1024:4.1f} GB {v:3.0f}%")


# --------------------------------------------------------------------------- RAM: velocidad y timings
_RAMINFO = {"started": False, "mts": None, "volt": 0.0, "text": "..."}


def _ram_query():
    if sys.platform != "win32":
        _RAMINFO["text"] = "N/D"
        return
    ps = ("Get-CimInstance Win32_PhysicalMemory | Select-Object -First 1 "
          "ConfiguredClockSpeed,Speed,ConfiguredVoltage,SMBIOSMemoryType | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=30, creationflags=0x08000000)
        d = json.loads(r.stdout)
        mts = d.get("ConfiguredClockSpeed") or d.get("Speed") or 0
        if d.get("SMBIOSMemoryType") == 34 and 0 < mts <= 3600:   # DDR5 puede dar el reloj real
            mts *= 2
        volt = (d.get("ConfiguredVoltage") or 0) / 1000.0
        _RAMINFO.update(mts=mts, volt=volt, text="ok")
    except Exception as e:  # noqa
        logger.warning("GameHUD: no se pudo leer la velocidad de la RAM: %s", e)
        _RAMINFO["text"] = "N/D"


class HudRamSpeed(_Hud):
    def as_string(self) -> str:
        if not _RAMINFO["started"]:
            _RAMINFO["started"] = True
            threading.Thread(target=_ram_query, daemon=True).start()
        if _RAMINFO["mts"] is None:
            return _RAMINFO["text"]                       # "..." mientras carga, "N/D" si falla
        # La tensión de WMI suele ser la del perfil JEDEC (1,10 V) aunque uses EXPO; el sensor DIMM de LHM es la real
        dimm = next((v for n, v in all_voltages() if "dimm" in n.lower()), None)
        volt = dimm if dimm else _RAMINFO["volt"]
        return f"{_RAMINFO['mts']} MT/s" + (f"  {volt:.2f} V" if volt else "")


class HudRamTimings(_Hud):
    # Windows no expone los timings; se muestran tal cual los escribas en gamehud_ram.txt
    def as_string(self) -> str:
        try:
            with open(os.path.join(ROOT, "gamehud_ram.txt"), encoding="utf-8-sig", errors="replace") as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
            return lines[0][:24] if lines else "N/D"
        except OSError:
            return "N/D"


# --------------------------------------------------------------------------- discos
_DISK = {"t": -1e9, "v": []}


def _disks():
    now = time.monotonic()
    if now - _DISK["t"] < 5.0:
        return _DISK["v"]
    _DISK["t"] = now
    res = []
    for p in psutil.disk_partitions(all=False):
        opts = (p.opts or "").lower()
        if "cdrom" in opts or (sys.platform == "win32" and "fixed" not in opts):
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except Exception:
            continue
        label = (p.mountpoint.rstrip("\\/") or p.mountpoint)[:3]
        res.append((label, u.total, u.free, u.percent))
    res.sort(key=lambda t: t[0])
    _DISK["v"] = res
    return res


def _sz(b: float) -> str:
    g = b / 2**30
    return f"{g / 1024:.1f}T" if g >= 1000 else f"{g:.0f}G"


class _Disk(_Hud):
    IDX = 0
    TTL = 5.0

    def _row(self):
        d = _disks()
        return d[self.IDX] if self.IDX < len(d) else None

    def _read(self):
        r = self._row()
        return r[3] if r else 0.0

    def as_numeric(self) -> float:
        if self._row() is None:
            return float("nan")                      # sin disco en este hueco: no dibujar la barra
        return _gate(type(self).__name__, self._st()["v"])

    def as_string(self) -> str:
        r = self._row()
        if r is None:
            return " "          # DisplayText no admite cadenas vacías
        lab, tot, free, used_pct = r
        return _tag(used_pct, f"{lab:<3}{_sz(free):>6} libres /{_sz(tot):>6}")


class HudDisk1(_Disk): IDX = 0
class HudDisk2(_Disk): IDX = 1
class HudDisk3(_Disk): IDX = 2
class HudDisk4(_Disk): IDX = 3
class HudDisk5(_Disk): IDX = 4


# --------------------------------------------------------------------------- actividad de los discos
_DIO = {"started": False, "map": {}, "t": 0.0, "prev": {}, "rates": {}}


def _dio_map_query():
    """Letra de unidad -> disco físico (PhysicalDriveN), una sola vez."""
    if sys.platform != "win32":
        return
    ps = ("Get-Partition | Where-Object { $_.DriveLetter } | "
          "Select-Object @{n='L';e={[string]$_.DriveLetter}},DiskNumber | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=30, creationflags=0x08000000)
        data = json.loads(r.stdout)
        if isinstance(data, dict):
            data = [data]
        _DIO["map"] = {d["L"].upper(): f"PhysicalDrive{d['DiskNumber']}" for d in data}
    except Exception as e:  # noqa
        logger.warning("GameHUD: no se pudo asociar unidades y discos físicos: %s", e)


def _disk_rates():
    """{disco: (lectura_B/s, escritura_B/s)} calculado entre dos lecturas de los contadores."""
    if not _DIO["started"]:
        _DIO["started"] = True
        threading.Thread(target=_dio_map_query, daemon=True).start()
    now = time.monotonic()
    if now - _DIO["t"] >= 0.8:
        try:
            cur = psutil.disk_io_counters(perdisk=True) or {}
        except Exception as e:  # noqa
            logger.debug("GameHUD: contadores de disco: %s", e)
            cur = {}
        if _DIO["t"] > 0:
            dt = max(now - _DIO["t"], 1e-3)
            rates = {}
            for k, c in cur.items():
                p = _DIO["prev"].get(k)
                if p:
                    rates[k] = (max(c.read_bytes - p[0], 0) / dt, max(c.write_bytes - p[1], 0) / dt)
            _DIO["rates"] = rates
        _DIO["prev"] = {k: (c.read_bytes, c.write_bytes) for k, c in cur.items()}
        _DIO["t"] = now
    return _DIO["rates"]


class _DiskIo(_Hud):
    IDX = 0

    def as_numeric(self) -> float:
        return 0.0

    def as_string(self) -> str:
        disks = _disks()
        if self.IDX >= len(disks):
            return " "                                   # DisplayText no admite cadenas vacías
        letter = disks[self.IDX][0].rstrip(":\\/").upper()
        rate = _disk_rates().get(_DIO["map"].get(letter, ""))
        if rate is None:
            return "R       N/D  W       N/D"
        return f"R{_fmt_rate(rate[0])}  W{_fmt_rate(rate[1])}"


class HudDisk1Io(_DiskIo): IDX = 0
class HudDisk2Io(_DiskIo): IDX = 1
class HudDisk3Io(_DiskIo): IDX = 2
class HudDisk4Io(_DiskIo): IDX = 3


class HudNetTotal(_Hud):
    """Bytes recibidos y enviados desde que arrancó Windows."""
    def as_string(self) -> str:
        c = psutil.net_io_counters()
        return f"DL {c.bytes_recv / 2**30:6.1f} GB  UL {c.bytes_sent / 2**30:6.1f} GB"


# --------------------------------------------------------------------------- ventiladores (RPM)
def all_fans():
    """[(nombre, rpm)] de los ventiladores de la placa que ve LHM."""
    return [(n, v) for h, t, n, v in _lhm_walk() if t == "Fan" and h == "Motherboard"]


def _fan_cfg(key):
    """Lee 'cpu = Fan #2' / 'gpu = ...' de gamehud_fans.txt (parte del nombre del sensor)."""
    try:
        with open(os.path.join(ROOT, "gamehud_fans.txt"), encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip().lower() == key and v.strip():
                        return v.strip().lower()
    except OSError:
        pass
    return ""


def cpu_fan():
    """(nombre, rpm) del ventilador de CPU elegido, o None."""
    fans = all_fans()
    want = _fan_cfg("cpu")
    if want:
        return next(((n, v) for n, v in fans if want in n.lower()), None)
    # sin configurar: el que lleve "cpu" en el nombre; si no, la suposición del propio programa (nº 2)
    return (next(((n, v) for n, v in fans if "cpu" in n.lower()), None)
            or next(((n, v) for n, v in fans if "#2" in n), None))


def gpu_fan():
    want = _fan_cfg("gpu")
    rows = [(n, v) for h, t, n, v in _lhm_walk() if h.startswith("Gpu") and t == "Fan"]
    return next(((n, v) for n, v in rows if want in n.lower()), None) if want else (rows[0] if rows else None)


def cpu_fan_rpm():
    r = cpu_fan()
    return None if r is None else r[1]


def gpu_fan_rpm():
    r = gpu_fan()
    return None if r is None else r[1]


class _Fan(_Hud):
    TTL = 1.0
    FN = staticmethod(lambda: None)

    def as_numeric(self) -> float:
        return 0.0

    def as_string(self) -> str:
        try:
            v = type(self).FN()
        except Exception as e:  # noqa
            logger.debug("GameHUD: ventilador: %s", e)
            v = None
        return "N/D" if v is None else f"{v:>4.0f} RPM"


class HudCpuFan(_Fan):
    FN = staticmethod(cpu_fan_rpm)


class HudGpuFan(_Fan):
    FN = staticmethod(gpu_fan_rpm)


# --------------------------------------------------------------------------- voltaje del núcleo de CPU y GPU
class _CoreVolt(_Hud):
    TTL = 1.0

    @staticmethod
    def FN():
        return None

    def as_numeric(self) -> float:
        return 0.0

    def as_string(self) -> str:
        try:
            v = type(self).FN()
        except Exception as e:  # noqa
            logger.debug("GameHUD: voltaje de núcleo: %s", e)
            v = None
        return "N/D" if v is None else f"{v:5.3f} V"


def cpu_vcore():
    hit = _find_metric(all_metrics(), "vcore", "Motherboard")
    return hit[1] if hit else None


def gpu_vcore():
    hit = next(((n, v) for h, n, v, u in all_metrics() if h.startswith("Gpu") and u == "V" and "core" in n.lower()), None)
    return hit[1] if hit else None


class HudCpuVolt(_CoreVolt):
    FN = staticmethod(cpu_vcore)


class HudGpuVolt(_CoreVolt):
    FN = staticmethod(gpu_vcore)
