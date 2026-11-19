#!/usr/bin/env python3
"""
GameHUD para turing-smart-screen-python (pantalla TURZX 8" 1280x800).

Ejecútalo desde la RAÍZ del repositorio (donde está main.py):

    python install_gamehud.py             instala el tema y los sensores
    python install_gamehud.py --probe     lista voltajes y estado de RTSS (consola de administrador)
    python install_gamehud.py --uninstall lo quita todo
    python install_gamehud.py --vendor    paquete (fondo + medidas) para el programa oficial de TURZX
    python install_gamehud.py --alertas   vista previa con los colores de aviso (temperaturas altas, RAM llena...)

Mantén este archivo junto a sensors_gamehud.py.
"""
import argparse
import copy
import csv
import math
import os
import random
import shutil
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

THEME = "GameHUD"
W, H = 1280, 800
FONT = "jetbrains-mono/JetBrainsMono-Bold.ttf"
CUSTOM_INTERVAL = 1             # segundos entre refrescos de los datos propios (si la pantalla va justa, prueba 2)
POWER_ROWS = 5                  # filas del panel POWER (4 a 6); debe coincidir con POWER_ROWS de sensors_gamehud.py
ROWS = 3                        # filas de bloques de los medidores de núcleo (24 niveles: cian, amarillo, rojo)
LABEL = 18                      # tamaño de las etiquetas pequeñas
NBARS = 16                      # una barra por hilo (9800X3D: 8 núcleos x 2 hilos); debe coincidir con NBARS de sensors_gamehud.py
BLK = " ▁▂▃▄▅▆▇█"
TAG = "# GAMEHUD"
IMPORT_LINE = "from library.sensors.sensors_gamehud import *  " + TAG

# ------------------------------------------------------------------ paleta
BG, PANEL, GRIDC = (7, 9, 18), (13, 17, 32), (30, 38, 70)
CY, MG, AM, LM = (0, 229, 255), (255, 60, 160), (255, 190, 0), (120, 255, 80)
YL, VI, OR = (255, 235, 90), (170, 130, 255), (255, 125, 60)
WHITE, DIM = (235, 240, 255), (125, 135, 170)

# Umbrales de color (aviso, crítico). Con valores bajos = malos (FPS) se indican como "hasta". El programa pinta el
# elemento con COLOR_WARN / COLOR_CRIT cuando el valor cruza el umbral (lo hace sensors_gamehud.py).
WX_CHARS = 18   # caracteres del tiempo antes del indicador de estado (igual que en sensors_gamehud.py)
EXT_KEYS = {"WARN_AT", "CRIT_AT", "WARN_BELOW", "CRIT_BELOW", "COLOR_WARN", "COLOR_CRIT", "ALERT_FLASH", "ALERT_FMT", "BADGE"}
COLOR_WARN, COLOR_CRIT = YL, (255, 70, 100)
THRESH = {"cpu_temp": (80, 90), "gpu_temp": (75, 83), "ram": (85, 95), "disk": (85, 95),
          "vram": (90, 97), "ft": (20, 33), "fps_below": (60, 30)}

PANELS = [  # clave, x, y, w, h, título, color
    ("cpu", 24, 80, 400, 230, "CPU // VITALITY", CY),
    ("gpu", 24, 326, 400, 230, "GPU // ENERGY", MG),
    ("ram", 24, 572, 400, 204, "RAM // STAMINA", AM),
    ("fps", 440, 80, 400, 476, "FPS // FRAME RATE", LM),
    ("net", 440, 572, 400, 204, "NET // COMMS", VI),
    ("pwr", 856, 80, 400, 230, "POWER // CELLS", YL),
    ("dsk", 856, 326, 400, 450, "INVENTORY // DISKS", OR),
]


def rgb(c):
    return f"{c[0]}, {c[1]}, {c[2]}"


# ------------------------------------------------------------------ diseño (posiciones compartidas)
def design(fontfile, core_font_rel, date_ex=None, text_fontfile=None):
    """Devuelve (STATS, barras, gráficas, etiquetas, medidores, iconos) con las mismas coordenadas
    para el fondo y para el theme.yaml. Los textos se colocan por LÍNEA BASE (Tb) para que etiquetas
    y valores de una misma fila queden alineados."""
    bars, lines, labels, meters, icons = [], [], [], [], []
    tff = text_fontfile or fontfile

    def cap(size, ff=None):                      # altura de los dígitos (línea base -> parte alta)
        return -ImageFont.truetype(ff or tff, size).getbbox("0", anchor="ls")[1]

    def T(x, y, size, color, font=FONT, w=None, h=None, anchor="lt", ref="0", ffile=None):
        # Ancla vertical 'a' (línea de ascendentes) en lugar de 't': con 't' Pillow alinea la TINTA del texto,
        # así que un texto con glifos bajos (p. ej. "▁" o "---") se dibuja más arriba que uno con glifos altos.
        # dy compensa para que la parte alta de los dígitos quede donde estaba diseñada.
        dy = ImageFont.truetype(ffile or tff, size).getbbox(ref, anchor="la")[1]
        align = {"m": "center", "r": "right"}.get(anchor[0], "left")
        t = {"SHOW": True, "SHOW_UNIT": True, "X": x, "Y": y - dy, "FONT": font, "FONT_SIZE": size,
             "FONT_COLOR": rgb(color), "BACKGROUND_IMAGE": "background.png",
             "ALIGN": align, "ANCHOR": anchor[0] + "a"}
        if w:
            # En los textos de región fija el programa toma X como el borde IZQUIERDO de la caja (no como el punto de
            # anclaje): para anclas centradas o a la derecha se desplaza X para que x siga siendo el centro / el borde dcho.
            t["X"] = x - (w if anchor[0] == "r" else w // 2 if anchor[0] == "m" else 0)
            t["WIDTH"], t["HEIGHT"] = w, h + dy
        return t

    def Tb(x, base, size, color, **kw):          # igual que T, pero indicando la línea base del texto
        return T(x, base - cap(size, kw.get("ffile")), size, color, **kw)

    def G(x, y, w, h, color):
        bars.append((x, y, w, h, color))
        return {"SHOW": True, "X": x, "Y": y, "WIDTH": w, "HEIGHT": h, "MIN_VALUE": 0, "MAX_VALUE": 100,
                "BAR_COLOR": rgb(color), "BAR_OUTLINE": False, "BACKGROUND_IMAGE": "background.png",
                "REVERSE_DIRECTION": False}

    def LG(x, y, w, h, color, vmin=0, vmax=100, auto=False, frame=True):
        if frame:
            lines.append((x, y, w, h, color))
        return {"SHOW": True, "X": x, "Y": y, "WIDTH": w, "HEIGHT": h, "MIN_VALUE": vmin, "MAX_VALUE": vmax,
                "HISTORY_SIZE": 60, "AUTOSCALE": auto, "LINE_COLOR": rgb(color), "LINE_WIDTH": 2,
                "AXIS": False, "AXIS_COLOR": rgb(color), "AXIS_FONT": "roboto/Roboto-Black.ttf",
                "AXIS_FONT_SIZE": 10, "BACKGROUND_IMAGE": "background.png"}

    def lab(x, y, s, size=LABEL, color=DIM, anchor="la"):
        labels.append((x, y, s, size, color, anchor))

    def labb(x, base, s, size=LABEL, color=DIM):  # etiqueta por línea base
        lab(x, base, s, size, color, "ls")

    def at(key):
        p = next(p for p in PANELS if p[0] == key)
        return p[1], p[2]

    LIGHT = (200, 210, 235)

    # CPU: % total, reloj, temperatura y medidores verticales por núcleo ------
    px, py = at("cpu")
    base = py + 84
    lab(px + 156, py + 28, "CLOCK")
    lab(px + 292, py + 28, "HEAT")
    cpu = {
        "PERCENTAGE": {"INTERVAL": 1, "TEXT": Tb(px + 16, base, 54, WHITE)},
        "TEMPERATURE": {"INTERVAL": 2, "TEXT": Tb(px + 268, base, 40, WHITE)},
    }
    icons.append(("fan", px + 276, py + 97, CY))                       # ventilador de CPU bajo HEAT
    cpu_fan = {"TEXT": Tb(px + 292, py + 104, 18, (200, 210, 235))}
    cells = 2 * NBARS - 1                         # 1 celda por barra + 1 de hueco
    adv = ImageFont.truetype(fontfile, 100).getlength("█") / 100
    fs_ = int(368 / cells / adv)
    fnt = ImageFont.truetype(fontfile, fs_)
    asc, desc = fnt.getmetrics()
    pitch = asc + desc                             # altura de una fila de bloques
    cw = fnt.getlength("█")
    mw = int(cw * cells) + 1
    mx, my = px + 16 + (368 - mw) // 2, py + 112
    # separadores finos entre núcleos (cada par de hilos SMT): en el hueco entre la barra 2i+1 y la 2i+2
    divs = [mx + (4 * i + 3.5) * cw for i in range(NBARS // 2 - 1)]
    meters.append((mx - 3, my - 3, mw + 6, pitch * ROWS + 6, CY, ROWS, divs))
    row_cols = [CY, YL, COLOR_CRIT]                # abajo (0-33 %) cian; medio amarillo; tope (67-100 %) rojo
    C_cores = {}
    for r in range(ROWS):
        C_cores[f"HudCoreRow{r}"] = {"TEXT": T(mx, my + (ROWS - 1 - r) * pitch, fs_, row_cols[r],
                                                font=core_font_rel, w=mw, h=pitch, ref="█", ffile=fontfile)}
    for i in range(NBARS // 2):                    # número de núcleo bajo cada par de hilos
        lab(mx + (4 * i + 1.5) * cw, my + pitch * ROWS + 8, str(i), LABEL, DIM, "mt")

    # GPU: %, reloj, temperatura, memoria y VRAM -------------------------------
    px_g, py_g = at("gpu")
    px, py = px_g, py_g
    base = py + 84
    lab(px + 156, py + 28, "CLOCK")
    lab(px + 292, py + 28, "HEAT")
    labb(px + 16, py + 128, "MEM")
    labb(px + 16, py + 158, "VRAM")
    gpu = {
        "INTERVAL": 1,
        "PERCENTAGE": {"TEXT": Tb(px + 16, base, 54, WHITE),
                       "GRAPH": G(px + 16, py + 184, 368, 26, MG)},
        "TEMPERATURE": {"TEXT": Tb(px + 268, base, 40, WHITE)},
    }
    icons.append(("fan", px + 276, py + 97, MG))                       # ventilador de GPU bajo HEAT
    gpu_custom = {
        "HudGpuClock": {"TEXT": Tb(px + 156, base, 24, WHITE)},
        "HudGpuFan": {"TEXT": Tb(px + 292, py + 104, 18, (200, 210, 235))},
        "HudGpuVolt": {"TEXT": Tb(px + 156, py + 104, 18, (200, 210, 235))},
        "HudGpuMemClock": {"TEXT": Tb(px + 76, py + 128, 22, WHITE)},
        "HudVram": {"TEXT": Tb(px + 76, py + 158, 22, WHITE)},
    }
    px, py = at("cpu")
    C = {"INTERVAL": CUSTOM_INTERVAL}  # custom
    C.update(C_cores)
    C["HudCpuClock"] = {"TEXT": Tb(px + 156, py + 84, 24, WHITE)}
    C["HudCpuFan"] = cpu_fan
    C["HudCpuVolt"] = {"TEXT": Tb(px + 156, py + 104, 18, (200, 210, 235))}
    C.update(gpu_custom)

    # Cabecera: [título] fecha | HORA centrada | tiempo exterior pegado a la hora (misma línea base) ----
    hb = 8 + cap(54)                                # línea base de la hora (tamaño 54, parte alta en Y=8)
    C["HudDate"] = {"TEXT": Tb(495, hb, 20, (190, 200, 230), anchor="rt")}
    # El tiempo ocupa WX_CHARS caracteres; a continuación va el indicador de estado ("SYS OK" / alerta). Si el texto
    # del tiempo es más largo y no hay alerta, el indicador desaparece y ahí sigue el texto (lo hace sensors_gamehud).
    bx = 786 + round(WX_CHARS * ImageFont.truetype(tff, 30).getlength("0"))
    C["HudWeather"] = {"TEXT": Tb(786, hb, 30, AM, anchor="lt", w=bx - 786, h=36)}
    C["HudStatus"] = {"BADGE": {"X": bx, "Y": 6, "WIDTH": 1258 - bx, "HEIGHT": 54, "BASE": hb - 6, "FONT": FONT,
                                "TAIL_SIZE": 30, "TAIL_COLOR": rgb(AM), "COLOR_OK": rgb(LM), "COLOR_WARN": rgb(COLOR_WARN),
                                "COLOR_CRIT": rgb(COLOR_CRIT), "BACKGROUND_IMAGE": "background.png", "WX_CHARS": WX_CHARS}}
    date_block = None
    hour = (date_ex or {}).get("HOUR", {}) if isinstance(date_ex, dict) else {}
    if isinstance(hour.get("TEXT"), dict) and isinstance((date_ex or {}).get("DAY", {}).get("TEXT"), dict):
        # reloj del propio programa: va en su propio hilo, con refresco cada segundo
        date_block = copy.deepcopy(date_ex)
        date_block["INTERVAL"] = 1
        t = date_block["HOUR"]["TEXT"]
        t.update(T(640, 8, 54, WHITE, anchor="mt"))
        t["FORMAT"] = "HH:mm:ss"                                     # 24 h con segundos, sea cual sea el idioma
        date_block["DAY"]["TEXT"]["SHOW"] = False
    else:
        C["HudClock"] = {"TEXT": T(640, 8, 54, WHITE, anchor="mt")}

    # RAM -----------------------------------------------------------------
    px, py = at("ram")
    base = py + 80
    lab(px + 176, py + 28, "USED / TOTAL")
    labb(px + 16, py + 156, "SPEED")
    labb(px + 16, py + 186, "TIMING")
    C["HudRamPercent"] = {"TEXT": Tb(px + 16, base, 54, WHITE),
                          "GRAPH": G(px + 16, py + 98, 368, 24, AM)}
    C["HudRamDetail"] = {"TEXT": Tb(px + 176, base, 24, WHITE)}
    C["HudRamSpeed"] = {"TEXT": Tb(px + 96, py + 156, 20, WHITE)}
    C["HudRamTimings"] = {"TEXT": Tb(px + 96, py + 186, 20, WHITE)}

    # FPS ----------------------------------------------------------------
    px, py = at("fps")
    # (las etiquetas "FPS · 60 SEC" / "FRAMETIME · MS" y el título del panel son dinámicas: en reposo cambian)
    tbase = py + 7 + ImageFont.truetype(tff, 18).getmetrics()[0]          # línea base del título del panel
    C["HudFpsTitle"] = {"TEXT": Tb(px + 34, tbase, 18, LM, w=190, h=24)}
    C["HudFpsLabel1"] = {"TEXT": Tb(px + 16, py + 232, LABEL, DIM, w=150, h=22)}
    C["HudFpsLabel2"] = {"TEXT": Tb(px + 16, py + 360, LABEL, DIM, w=160, h=22)}
    C["HudFpsStats"] = {"TEXT": Tb(px + 384, py + 360, 18, LIGHT, anchor="rt", w=200, h=22)}   # AVG / MIN de 60 s
    C["HudFps"] = {"TEXT": T(px + 60, py + 50, 150, LM),
                   "LINE_GRAPH": LG(px + 16, py + 244, 368, 88, LM, 0, 144, True)}
    C["HudFpsGame"] = {"TEXT": Tb(px + 16, py + 200, 22, DIM, w=240, h=26)}
    C["HudFrameTime"] = {"TEXT": Tb(px + 384, py + 200, 22, WHITE, anchor="rt", w=170, h=26),
                         "LINE_GRAPH": LG(px + 16, py + 372, 368, 88, AM, 0, 33, True)}
    C["HudDisplayMode"] = {"TEXT": Tb(px + 384, py + 232, 20, LIGHT, anchor="rt")}
    C["HudFpsApi"] = {"TEXT": Tb(px + 378, tbase, 18, LM, anchor="rt", w=108, h=24)}   # región fija: puede estar vacía
    # Modo reposo (sin juego): procesos que más consumen, uptime y cargas de CPU/GPU en las mismas zonas
    C["HudHeroClear"] = {"TEXT": T(px + 16, py + 38, 20, LM, w=368, h=142)}
    C["HudTopH0"] = {"TEXT": T(px + 16, py + 38, 14, DIM, w=200, h=22)}
    C["HudTopH1"] = {"TEXT": T(px + 284, py + 38, 14, DIM, w=68, h=22, anchor="rt")}
    C["HudTopH2"] = {"TEXT": T(px + 384, py + 38, 14, DIM, w=100, h=22, anchor="rt")}
    for i in range(4):
        ry = py + 60 + 30 * i
        C[f"HudTopN{i + 1}"] = {"TEXT": T(px + 16, ry, 22, WHITE, w=200, h=30)}
        C[f"HudTopC{i + 1}"] = {"TEXT": T(px + 284, ry, 22, CY, w=68, h=30, anchor="rt")}
        C[f"HudTopM{i + 1}"] = {"TEXT": T(px + 384, ry, 22, LIGHT, w=100, h=30, anchor="rt")}
    C["HudUptime"] = {"TEXT": Tb(px + 384, py + 200, 22, WHITE, anchor="rt", w=170, h=26)}
    C["HudIdleCpu"] = {"LINE_GRAPH": LG(px + 16, py + 244, 368, 88, CY, 0, 100, False, frame=False)}
    C["HudIdleGpu"] = {"LINE_GRAPH": LG(px + 16, py + 372, 368, 88, MG, 0, 100, False, frame=False)}

    # NET ----------------------------------------------------------------
    px, py = at("net")
    icons.append(("down", px + 16, py + 40, LM))
    icons.append(("up", px + 16, py + 88, OR))
    labb(px + 16, py + 190, "TOTAL")
    icons.append(("router", px + 16, py + 130, VI))
    C["HudNetDown"] = {"TEXT": Tb(px + 52, py + 66, 26, WHITE),
                       "LINE_GRAPH": LG(px + 292, py + 42, 92, 32, LM, 0, 10, True)}
    C["HudNetUp"] = {"TEXT": Tb(px + 52, py + 114, 26, DIM),
                     "LINE_GRAPH": LG(px + 292, py + 90, 92, 32, OR, 0, 10, True)}
    C["HudNetTotal"] = {"TEXT": Tb(px + 82, py + 190, 18, LIGHT)}
    C["HudRouterIp"] = {"TEXT": Tb(px + 60, py + 152, 26, WHITE, w=324, h=30)}

    # POWER --------------------------------------------------------------
    px, py = at("pwr")
    size, pitch, top = {4: (24, 44, 52), 5: (22, 36, 48), 6: (20, 30, 46)}[POWER_ROWS]
    for i in range(POWER_ROWS):
        C[f"HudVolt{i + 1}"] = {"TEXT": T(px + 16, py + top + i * pitch, size, YL, w=256, h=int(size * 1.3)),
                                "GRAPH": G(px + 284, py + top + i * pitch + int(size * 1.3) // 2 - 5, 96, 10, YL)}

    # DISKS --------------------------------------------------------------
    px, py = at("dsk")
    for i in range(4):
        C[f"HudDisk{i + 1}"] = {"TEXT": T(px + 16, py + 50 + i * 100, 24, WHITE, w=368, h=30),
                                "GRAPH": G(px + 16, py + 88 + i * 100, 368, 16, OR)}
        C[f"HudDisk{i + 1}Io"] = {"TEXT": T(px + 16, py + 112 + i * 100, 20, LIGHT, w=368, h=26)}

    def thr(d, warn, crit, below=False):
        d.update({"WARN_BELOW" if below else "WARN_AT": warn, "CRIT_BELOW" if below else "CRIT_AT": crit,
                  "COLOR_WARN": rgb(COLOR_WARN), "COLOR_CRIT": rgb(COLOR_CRIT)})

    thr(cpu["TEMPERATURE"]["TEXT"], *THRESH["cpu_temp"])
    thr(gpu["TEMPERATURE"]["TEXT"], *THRESH["gpu_temp"])
    cpu["TEMPERATURE"]["TEXT"]["ALERT_FMT"] = "CPU {v:.0f}°C"        # texto del indicador de estado de la cabecera
    gpu["TEMPERATURE"]["TEXT"]["ALERT_FMT"] = "GPU {v:.0f}°C"
    C["HudRamPercent"]["TEXT"]["ALERT_FMT"] = "RAM {v:.0f}%"
    C["HudVram"]["TEXT"]["ALERT_FMT"] = "VRAM {v:.0f}%"
    cpu["TEMPERATURE"]["TEXT"]["ALERT_FLASH"] = True      # al llegar a crítico, borde rojo parpadeante en toda la pantalla
    gpu["TEMPERATURE"]["TEXT"]["ALERT_FLASH"] = True
    thr(C["HudRamPercent"]["TEXT"], *THRESH["ram"])
    thr(C["HudRamPercent"]["GRAPH"], *THRESH["ram"])
    thr(C["HudVram"]["TEXT"], *THRESH["vram"])
    thr(C["HudFrameTime"]["TEXT"], *THRESH["ft"])
    thr(C["HudFps"]["TEXT"], *THRESH["fps_below"], below=True)
    for i in range(POWER_ROWS):                      # medidores de POWER: rojo al salirse de la tolerancia / pasar el máximo
        thr(C[f"HudVolt{i + 1}"]["GRAPH"], 85, 100)      # (los de tolerancia los colorea sensors_gamehud por su cuenta)
    for i in range(4):
        thr(C[f"HudDisk{i + 1}"]["TEXT"], *THRESH["disk"])
        thr(C[f"HudDisk{i + 1}"]["GRAPH"], *THRESH["disk"])

    stats = {"CPU": cpu, "GPU": gpu}
    if date_block:
        stats["DATE"] = date_block
    stats["CUSTOM"] = C
    return stats, bars, lines, labels, meters, icons


# ------------------------------------------------------------------ YAML mínimo
def _fmt(v):
    return ("True" if v else "False") if isinstance(v, bool) else str(v)


def emit(o, ind=0):
    pad, out = "  " * ind, []
    for k, v in o.items():
        if isinstance(v, dict):
            out.append(f"{pad}{k}:")
            out += emit(v, ind + 1)
        else:
            out.append(f"{pad}{k}: {_fmt(v)}")
    return out


def read_yaml(p):
    try:
        import yaml
        with open(p, encoding="utf8") as f:
            return yaml.safe_load(f)
    except ImportError:
        from ruamel.yaml import YAML
        with open(p, encoding="utf8") as f:
            return YAML(typ="safe").load(f)


def check_against_example(stats, example, path=""):
    """Avisa de claves de CPU/GPU que no existan en theme_example.yaml de tu versión."""
    bad = []
    for k, v in stats.items():
        if k in EXT_KEYS:                       # claves propias de GameHUD (colores por umbral), no de theme_example
            continue
        if k not in example:
            bad.append(path + k)
        elif isinstance(v, dict) and isinstance(example[k], dict):
            bad += check_against_example(v, example[k], path + k + ".")
    return bad


# ------------------------------------------------------------------ fondo
def build_background(fontfile, core_fontfile, core_font_rel):
    def F(size):
        return ImageFont.truetype(fontfile, size)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img, "RGBA")
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(12 - 6 * t), int(15 - 8 * t), int(32 - 16 * t)))
    for x in range(0, W, 40):
        d.line([(x, 0), (x, H)], fill=GRIDC + (45,))
    for y in range(0, H, 40):
        d.line([(0, y), (W, y)], fill=GRIDC + (45,))
    for y in range(0, H, 3):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, 34))

    # cabecera
    for i, c in enumerate((CY, MG, AM)):
        x = 34 + i * 22
        d.polygon([(x, 16), (x + 14, 16), (x + 4, 54), (x - 10, 54)], fill=c + (255,))
    d.text((112, 15), "GAME//HUD", font=F(34), fill=WHITE)
    d.line([(24, 66), (W - 24, 66)], fill=CY + (170,), width=2)
    d.polygon([(24, 62), (180, 62), (190, 70), (24, 70)], fill=CY + (255,))

    c = 16
    for key, x, y, w, h, title, col in PANELS:
        pts = [(x + c, y), (x + w, y), (x + w, y + h - c), (x + w - c, y + h), (x, y + h), (x, y + c)]
        d.polygon(pts, fill=PANEL + (238,))
        d.line(pts + [pts[0]], fill=col + (255,), width=2)
        d.line([(x + 6, y + c + 4), (x + 6, y + h - 8)], fill=col + (70,), width=1)
        d.rectangle([x + 16, y + 14, x + 25, y + 23], fill=col + (255,))
        if key != "fps":                                       # el título del panel de FPS es dinámico (HudFpsTitle)
            d.text((x + 34, y + 7), title, font=F(18), fill=col)
        tw = d.textlength(title, font=F(18))
        lend = x + w - 22 - (110 if key == "fps" else 0)      # en FPS la línea acaba antes: ahí va la API gráfica
        d.line([(x + 34 + tw + 10, y + 19), (lend, y + 19)], fill=col + (90,), width=1)
        d.line([(x + w - 22, y + 19), (x + w - 14, y + 27)], fill=col + (90,), width=1) if key != "fps" else None

    _, bars, lines, labels, meters, icons = design(core_fontfile, core_font_rel, text_fontfile=fontfile)
    for x, y, w, h, col in bars:  # barras de vida segmentadas
        d.rectangle([x - 3, y - 3, x + w + 3, y + h + 3], fill=(3, 5, 12, 255), outline=col + (210,), width=2)
        d.rectangle([x, y, x + w, y + h], fill=(10, 14, 28, 255))
        for i in range(1, 20):
            xx = x + w * i / 20
            d.line([(xx, y), (xx, y + h)], fill=(0, 0, 0, 120) if i % 2 else col + (50,), width=1)
    for x, y, w, h, col in lines:  # pantallas de gráfica
        d.rectangle([x - 2, y - 2, x + w + 2, y + h + 2], fill=(4, 6, 14, 255), outline=col + (150,), width=1)
        for i in range(1, 4):
            d.line([(x, y + h * i / 4), (x + w, y + h * i / 4)], fill=col + (38,), width=1)
    for x, y, w, h, col, rows, divs in meters:  # pantalla de los medidores de núcleo
        d.rectangle([x, y, x + w, y + h], fill=(4, 6, 14, 255), outline=col + (150, ), width=1)
        for dx in divs:                              # separación entre núcleos
            d.line([(dx, y + 3), (dx, y + h - 3)], fill=col + (70,), width=1)
        for i in range(1, rows):
            yy = y + 3 + (h - 6) * i / rows
            d.line([(x + 3, yy), (x + w - 3, yy)], fill=col + (45,), width=1)
    for kind, x, y, col in icons:  # flechas de red e iconos de ventilador
        if kind == "router":                                     # router con dos antenas
            d.rounded_rectangle([x + 1, y + 13, x + 35, y + 26], radius=3, outline=col + (255,), width=3)
            d.line([(x + 8, y + 13), (x + 4, y + 2)], fill=col + (255,), width=3)
            d.line([(x + 28, y + 13), (x + 32, y + 2)], fill=col + (255,), width=3)
            for dx in (10, 18):
                d.ellipse([x + dx - 2, y + 17, x + dx + 2, y + 21], fill=col + (255,))
            continue
        if kind == "fan":
            r = 8
            d.ellipse([x - r, y - r, x + r, y + r], outline=col + (255,), width=2)
            for k in range(3):                                   # 3 aspas
                a0 = math.radians(k * 120 - 90)
                pts = [(x, y)]
                for da, rr in ((0, 0.92), (28, 0.95), (58, 0.80), (78, 0.45)):
                    a = a0 + math.radians(da)
                    pts.append((x + r * rr * math.cos(a), y + r * rr * math.sin(a)))
                d.polygon(pts, fill=col + (255,))
            d.ellipse([x - 2.5, y - 2.5, x + 2.5, y + 2.5], fill=PANEL + (255,))
            continue
        cx = x + 13
        head = [(x, y + 14), (x + 26, y + 14), (cx, y + 29)] if kind == "down" else [(x, y + 15), (x + 26, y + 15), (cx, y)]
        shaft = [cx - 5, y, cx + 5, y + 14] if kind == "down" else [cx - 5, y + 15, cx + 5, y + 29]
        d.polygon(head, fill=col + (255,))
        d.rectangle(shaft, fill=col + (255,))
    for x, y, s, size, col, anc in labels:
        d.text((x, y), s, font=F(size), fill=col, anchor=anc)
    return img


# ------------------------------------------------------------------ preview con datos de ejemplo
SAMPLE = {
    "HudCpuClock": "5200 MHz", "HudGpuClock": "2850 MHz", "HudGpuMemClock": "14000 MHz",
    "HudVram": " 8.2/16.0 GB  51%", "HudRamSpeed": "6000 MT/s  1.36 V", "HudRamTimings": "CL30-36-36-96",
    "DATE.HOUR": "21:47:05", "HudClock": "21:47:05", "HudWeather": "MADRID 18°C NUBES",
    "HudDisplayMode": "2560x1440 @ 165Hz", "HudCpuFan": "1450 RPM", "HudGpuFan": "1850 RPM", "HudCpuVolt": "1.166 V", "HudGpuVolt": "0.815 V", "HudNetTotal": "DL  412.3 GB  UL   58.0 GB",
    "CPU.PERCENTAGE": " 37%", "CPU.TEMPERATURE": " 61°C", "GPU.PERCENTAGE": " 72%",
    "GPU.TEMPERATURE": " 66°C", "HudClock": "21:47:05",
    "HudDate": "DOM 11 OCT 2026", "HudRamPercent": " 47%", "HudRamDetail": "14.8 / 31.8 GB",
    "HudFps": "144", "HudFpsApi": "D3D12", "HudFrameTime": "FT   6.9 ms", "HudFpsGame": "ELDENRING.EXE", "HudNetDown": "DL   12.4 MB/s",
    "HudNetUp": "UL  350.2 KB/s", "HudVolt1": "+12V       12.096 V", "HudVolt2": "+5V         5.010 V",
    "HudVolt3": "VSoC        1.214 V", "HudVolt4": "CPU PWR     88.4 W",
    "HudVolt5": "GPU PWR    212.5 W", "HudVolt6": "+3.3V       3.304 V",
    "HudDisk1": "C:    412G libres /  931G", "HudDisk2": "D:    1.2T libres /  1.8T",
    "HudDisk3": "E:    208G libres /  465G", "HudDisk4": "F:     36G libres /  223G",
    "HudDisk1Io": "R 412.3 MB/s  W  58.0 MB/s", "HudDisk2Io": "R   0.0 KB/s  W   0.0 KB/s",
    "HudDisk3Io": "R   1.2 MB/s  W 310.5 KB/s", "HudDisk4Io": "R   0.0 KB/s  W   0.0 KB/s",
    "HudRouterIp": "WAN 83.45.120.7", "HudFpsStats": "AVG 141 · MIN 118", "HudFpsTitle": "FPS // FRAME RATE", "HudFpsLabel1": "FPS · 60 SEC", "HudFpsLabel2": "FRAMETIME · MS",
}
SAMPLE_IDLE = {  # modo reposo (sin juego): el panel central cambia
    "HudFpsTitle": "SYS // STANDBY", "HudFpsGame": "SIN JUEGO", "HudFpsApi": "", "HudFpsStats": "", "HudUptime": "UP 3d 04:12",
    "HudFpsLabel1": "CPU · 60 SEC", "HudFpsLabel2": "GPU · 60 SEC",
    "HudTopH0": "TOP PROCESOS", "HudTopH1": "CPU", "HudTopH2": "MEM",
    "HudTopN1": "CHROME.EXE", "HudTopC1": "14%", "HudTopM1": "1.9 GB",
    "HudTopN2": "DISCORD.EXE", "HudTopC2": "3%", "HudTopM2": "612 MB",
    "HudTopN3": "WALLPAPER64.EXE", "HudTopC3": "2%", "HudTopM3": "480 MB",
    "HudTopN4": "STEAM.EXE", "HudTopC4": "1%", "HudTopM4": "390 MB",
}
GAME_ONLY = {"HudFps", "HudFrameTime"}
IDLE_ONLY = {"HudHeroClear", "HudUptime", "HudIdleCpu", "HudIdleGpu", "HudTopH0", "HudTopH1", "HudTopH2",
             *(f"HudTop{k}{i}" for k in "NCM" for i in range(1, 5))}
LOADS = [12, 35, 61, 88, 24, 47, 73, 9, 5, 95, 40, 20, 66, 81, 30, 15]


def core_row(loads, r):
    cells = []
    for p in loads[:NBARS]:
        h = max(1, round(p / 100 * 8 * ROWS))
        cells.append(BLK[max(0, min(8, h - 8 * r))])
    return " ".join(cells)


SAMPLE.update({f"HudCoreRow{r}": core_row(LOADS, r) for r in range(ROWS)})
FRAC = {"HudVolt1": .58, "HudVolt2": .52, "HudVolt3": .93, "HudVolt4": .55, "HudVolt5": .71, "CPU.PERCENTAGE": .37, "GPU.PERCENTAGE": .72, "HudRamPercent": .47, "HudDisk1": .56,
        "HudDisk2": .33, "HudDisk3": .55, "HudDisk4": .84}


NUM = {"CPU.TEMPERATURE": 61, "GPU.TEMPERATURE": 66, "HudRamPercent": 47, "HudVram": 51, "HudFrameTime": 6.9,
       "HudFps": 144, "HudDisk1": 56, "HudDisk2": 33, "HudDisk3": 55, "HudDisk4": 84}
ALERT = {  # valor, texto de ejemplo (situación de aviso/crítica para ver los colores)
    "CPU.TEMPERATURE": (91, " 91°C"), "GPU.TEMPERATURE": (84, " 84°C"), "HudRamPercent": (96, " 96%"),
    "HudVram": (98, "15.9/16.0 GB  98%"), "HudFrameTime": (38.2, "FT  38.2 ms"), "HudFps": (45, " 45"),
    "HudDisk1": (97, "C:     12G libres /  931G"), "HudDisk4": (87, "F:     29G libres /  223G")}


def th_color(d, v, key):
    """Color del elemento según sus umbrales (misma lógica que aplica sensors_gamehud.py)."""
    def n(k):
        return None if d.get(k) is None else float(d[k])
    crit, warn, cb, wb = n("CRIT_AT"), n("WARN_AT"), n("CRIT_BELOW"), n("WARN_BELOW")
    if v is not None and ((crit is not None and v >= crit) or (cb is not None and v <= cb)):
        return tuple(int(c) for c in d["COLOR_CRIT"].split(","))
    if v is not None and ((warn is not None and v >= warn) or (wb is not None and v <= wb)):
        return tuple(int(c) for c in d["COLOR_WARN"].split(","))
    return tuple(int(c) for c in d[key].split(","))


def build_preview(bg, stats, fontdir, alert=False, idle=False):
    sample, num, frac = dict(SAMPLE), dict(NUM), dict(FRAC)
    if idle:
        sample.update(SAMPLE_IDLE)
    if alert:
        for k, (v, txt) in ALERT.items():
            num[k], sample[k] = v, txt
        frac.update({"HudRamPercent": .96, "HudDisk1": .97, "HudDisk4": .87})
    img = bg.copy()
    d = ImageDraw.Draw(img, "RGBA")
    rnd = random.Random(7)
    groups = {}
    for blk in ("CPU", "GPU"):
        for k, v in stats[blk].items():
            if isinstance(v, dict):
                groups[f"{blk}.{k}"] = v
    for k, v in stats.get("DATE", {}).items():
        if isinstance(v, dict) and "TEXT" in v:
            groups[f"DATE.{k}"] = v
    groups.update({k: v for k, v in stats["CUSTOM"].items() if isinstance(v, dict)})
    for name, g in groups.items():
        if name in (GAME_ONLY if idle else IDLE_ONLY):       # cada modo muestra solo lo suyo
            continue
        if "BADGE" in g:                                      # indicador de estado (igual que _paint_badge)
            b = g["BADGE"]
            lvl, txt = max(((2 if v >= t.get("CRIT_AT", 1e9) else 1 if v >= t.get("WARN_AT", 1e9) else 0,
                             t["ALERT_FMT"].format(v=v)) for t, v in (
                (gr["TEXT"], num.get(nm)) for nm, gr in groups.items()
                if isinstance(gr.get("TEXT"), dict) and gr["TEXT"].get("ALERT_FMT") and num.get(nm) is not None)),
                default=(0, ""))
            col = tuple(int(c) for c in b["COLOR_CRIT" if lvl == 2 else "COLOR_WARN" if lvl == 1 else "COLOR_OK"].split(","))
            bx, by = b["X"], b["Y"]
            d.rounded_rectangle([bx + 12, by + 12, bx + b["WIDTH"] - 2, by + 48], radius=4, fill=(13, 17, 32, 255),
                                outline=col + (255,), width=2)
            if lvl:
                d.polygon([(bx + 22, by + 39), (bx + 32, by + 21), (bx + 42, by + 39)], fill=col + (255,))
                d.text((bx + 50, by + 30), txt[:9], font=ImageFont.truetype(str(fontdir / FONT), 17), fill=col, anchor="lm")
            else:
                d.ellipse([bx + 26, by + 23, bx + 40, by + 37], fill=col + (255,))
                d.text((bx + 54, by + 30), "SYS OK", font=ImageFont.truetype(str(fontdir / FONT), 20), fill=col, anchor="lm")
        if "GRAPH" in g and name in ("HudVolt1", "HudVolt2"):    # +12V / +5V: zona de tolerancia con marcador
            b = g["GRAPH"]
            x, y, w, h = b["X"], b["Y"], b["WIDTH"], b["HEIGHT"]
            base = tuple(int(c) for c in b["BAR_COLOR"].split(","))
            d.rectangle([x, y, x + w, y + h], fill=(4, 6, 14, 255))
            d.rectangle([x + w * .2, y + 1, x + w * .8, y + h - 1], fill=base + (55,))
            d.line([(x + w * .5, y - 2), (x + w * .5, y + h + 2)], fill=base + (120,), width=1)
            mx = x + w * frac.get(name, .5)
            d.rectangle([mx - 2, y - 2, mx + 2, y + h + 2], fill=base + (255,))
        elif "GRAPH" in g:
            b = g["GRAPH"]
            fr = frac.get(name, .5)
            col = th_color(b, fr * 100, "BAR_COLOR")
            d.rectangle([b["X"], b["Y"], b["X"] + b["WIDTH"] * fr, b["Y"] + b["HEIGHT"]], fill=col + (255,))
        if "LINE_GRAPH" in g:
            b = g["LINE_GRAPH"]
            col = tuple(int(c) for c in b["LINE_COLOR"].split(","))
            v, pts = .5, []
            for i in range(60):
                v = min(.95, max(.05, v + rnd.uniform(-.12, .12)))
                pts.append((b["X"] + b["WIDTH"] * i / 59, b["Y"] + b["HEIGHT"] * (1 - v)))
            d.line(pts, fill=col + (255,), width=2)
        if "TEXT" in g and g["TEXT"].get("SHOW") and sample.get(name):
            t = g["TEXT"]
            col = th_color(t, num.get(name), "FONT_COLOR")
            ax, ay, anc = t["X"], t["Y"], t.get("ANCHOR", "lt")
            if t.get("WIDTH"):                      # región fija: así coloca el programa el texto dentro de la caja
                ax += t["WIDTH"] / 2 if anc[0] == "m" else t["WIDTH"] if anc[0] == "r" else 0
                ay += t["HEIGHT"] / 2 if anc[1] == "m" else t["HEIGHT"] if anc[1] == "b" else 0
            d.text((ax, ay), sample[name], font=ImageFont.truetype(str(fontdir / t["FONT"]), t["FONT_SIZE"]),
                   fill=col, anchor=anc)
    return img


# ------------------------------------------------------------------ instalar / quitar
def _glyph(font, ch):
    im = Image.new("L", (90, 90), 0)
    ImageDraw.Draw(im).text((8, 8), ch, font=font, fill=255)
    return im.tobytes()


def has_blocks(path):
    f = ImageFont.truetype(str(path), 48)
    notdef = _glyph(f, "\U0010FFFF")  # carácter inexistente -> glifo "vacío" de la fuente
    return all(_glyph(f, c) != notdef for c in BLK[1:])


def pick_core_font(root):
    for rel in (FONT, "roboto-mono/RobotoMono-Bold.ttf", "jetbrains-mono/JetBrainsMono-Regular.ttf"):
        p = root / "res" / "fonts" / rel
        if p.exists() and has_blocks(p):
            return rel, p
    sys.exit("Ninguna fuente de res/fonts tiene los caracteres de bloque (▁▂▃▄▅▆▇█).")


def find_root():
    root = Path.cwd()
    need = [root / "library" / "sensors" / "sensors_custom.py", root / "res" / "themes", root / "main.py"]
    miss = [str(p.relative_to(root)) for p in need if not p.exists()]
    if miss:
        sys.exit("Ejecuta esto desde la raíz del repositorio (donde está main.py). Falta: " + ", ".join(miss))
    return root


def detect_size(root):
    best = None
    for t in sorted((root / "res" / "themes").iterdir()):
        y = t / "theme.yaml"
        if t.is_dir() and "8inch" in t.name.lower() and y.exists():
            disp = (read_yaml(y) or {}).get("display", {})
            if disp.get("DISPLAY_SIZE"):
                if best is None or t.name == "Landscape15Grid_8inch":
                    best = (t.name, str(disp["DISPLAY_SIZE"]), disp.get("DISPLAY_ORIENTATION"))
    return best


def install(root):
    src = Path(__file__).with_name("sensors_gamehud.py")
    if not src.exists():
        sys.exit("Falta sensors_gamehud.py junto a este script.")
    fontfile = root / "res" / "fonts" / FONT
    if not fontfile.exists():
        sys.exit(f"No encuentro la fuente {fontfile}")

    base = detect_size(root)
    if base:
        print(f"Tamaño de pantalla tomado de res/themes/{base[0]}: DISPLAY_SIZE={base[1]}, "
              f"orientación base={base[2]}")
        size = base[1]
    else:
        size = '8"'
        print('AVISO: no encontré ningún tema de 8"; uso DISPLAY_SIZE: 8" (si no aparece en el '
              "configurador, copia el valor de DISPLAY_SIZE de un tema 8inch).")

    core_rel, core_file = pick_core_font(root)
    print(f"Fuente de los medidores de núcleo: {core_rel}")
    ex = root / "res" / "themes" / "theme_example.yaml"
    ex_stats = (read_yaml(ex) or {}).get("STATS", {}) if ex.exists() else {}
    stats, *_ = design(str(core_file), core_rel, ex_stats.get("DATE"), text_fontfile=str(fontfile))
    print("Reloj: " + ("DATE.HOUR del programa (hilo propio, 1 s)" if "DATE" in stats
                       else "sensor propio HudClock (no encontré DATE en theme_example.yaml)"))
    if ex.exists():
        bad = check_against_example({k: stats[k] for k in ("CPU", "GPU")}, ex_stats)
        if bad:
            print("AVISO: estas claves no existen en tu theme_example.yaml (revisa el nombre):", bad)

    tdir = root / "res" / "themes" / THEME
    tdir.mkdir(exist_ok=True)
    bg = build_background(str(fontfile), str(core_file), core_rel)
    bg.save(tdir / "background.png")
    build_preview(bg, stats, root / "res" / "fonts").save(tdir / "preview.png")

    head = ['author: "GameHUD (generado con Claude)"', "", "display:", f"  DISPLAY_SIZE: {size}",
            "  DISPLAY_ORIENTATION: landscape", f"  DISPLAY_RGB_LED: {rgb(CY)}", "", "static_images:",
            "  BACKGROUND:", "    PATH: background.png", "    X: 0", "    Y: 0", f"    WIDTH: {W}",
            f"    HEIGHT: {H}", "", "STATS:"]
    body = emit(stats, 1)
    (tdir / "theme.yaml").write_text("\n".join(head + body) + "\n", encoding="utf8")

    fpsf = root / "gamehud_fps.txt"
    if not fpsf.exists():
        fpsf.write_text(FPS_TXT, encoding="utf8")
    bri = root / "gamehud_brightness.txt"
    if not bri.exists():
        bri.write_text(BRIGHT_TXT, encoding="utf8")
    volts = root / "gamehud_voltages.txt"
    if not volts.exists():
        volts.write_text(VOLT_TXT, encoding="utf8")
    fans = root / "gamehud_fans.txt"
    if not fans.exists():
        fans.write_text("# Ventiladores. Una línea por ventilador con parte del nombre del sensor que quieres usar.\n"
                        "# `python install_gamehud.py --probe` (consola de administrador) lista los que ve tu equipo.\n"
                        "# Sin configurar, el de CPU es el 'Fan #2' de la placa (como supone el programa) y el de GPU el de la tarjeta.\n"
                        "# Ejemplos (quita la # para activarlos):\n"
                        "# cpu = Fan #1\n# gpu = GPU Fan\n", encoding="utf8")
    wx = root / "gamehud_weather.txt"
    if not wx.exists():
        wx.write_text("# Ciudad, latitud, longitud (tiempo exterior de Open-Meteo, sin clave). Ejemplo:\n"
                      "Madrid, 40.4168, -3.7038\n", encoding="utf8")
    ram = root / "gamehud_ram.txt"
    if not ram.exists():
        ram.write_text("# Escribe aquí tus timings de RAM (una línea, se muestra tal cual). Ejemplo: CL30-36-36-96\n"
                       "# Windows no los expone; cópialos de CPU-Z (pestaña Memory) o de ZenTimings.\n"
                       "N/D\n", encoding="utf8")
    ipf = root / "gamehud_ip.txt"
    if not ipf.exists() or "gateway   IP del router" in ipf.read_text(encoding="utf8", errors="replace"):
        ipf.write_text(IP_TXT, encoding="utf8")           # (también reemplaza la plantilla anterior, que era "gateway")
    shutil.copy(src, root / "library" / "sensors" / "sensors_gamehud.py")
    sc = root / "library" / "sensors" / "sensors_custom.py"
    txt = sc.read_text(encoding="utf8")
    if TAG not in txt:
        bak = sc.with_name("sensors_custom.py.gamehud.bak")
        if not bak.exists():
            shutil.copy(sc, bak)
        sc.write_text(txt.rstrip("\n") + "\n\n" + IMPORT_LINE + "\n", encoding="utf8")
    print(f"\nListo. Tema creado en res/themes/{THEME}/")
    print("Siguiente: abre el configurador, elige el tema GameHUD y 'Save & run'.")
    print("Voltajes: ejecuta `python install_gamehud.py --probe` en una consola de administrador.")


FPS_TXT = """# GameHUD - qué aplicación cuenta para los FPS.
# Por defecto se usa la ventana en PRIMER PLANO (lo mismo que hace RTSS/Afterburner con "el juego en pantalla"); si la
# ventana activa no es un juego enganchado por RTSS, se usa la más reciente que no esté en la lista de ignoradas
# (navegadores, lanzadores, Wallpaper Engine, Discord... ya vienen ignorados).
# ignore = nombre1.exe, nombre2.exe       (se SUMAN a la lista por defecto)
# only_foreground = yes                   (solo cuenta la ventana en primer plano; si no es un juego, no muestra nada)
# Se lee solo, sin reiniciar.
"""

BRIGHT_TXT = """# GameHUD - brillo nocturno de la pantalla.
# night = tope de brillo (0-100 %) entre "from" y "to". Es un TOPE: si tu brillo de día ya es menor, no cambia nada.
# night = off  lo desactiva. Con la pantalla apagada (bloqueo/suspensión) no se toca. Se lee solo, sin reiniciar.
night = 15
from = 23:00
to = 08:00
"""

IP_TXT = """# GameHUD - qué IP se ve en el panel NET.
# mode = public    IP pública de tu conexión, la que ve internet (se consulta a api.ipify.org cada 10 minutos)   <- por defecto
# mode = gateway   IP local del router (puerta de enlace, p. ej. 192.168.1.1)
# Se lee solo, sin reiniciar.
mode = public
"""

VOLT_TXT = """# GameHUD - filas del panel POWER (máximo 5 líneas activas, de arriba abajo; 6 si subes POWER_ROWS).
# Formato:  alternativa1, alternativa2 | etiqueta corta | medidor (opcional)
# Medidor (barra a la derecha de la fila):  nominal=12 tol=5  (ventana de tolerancia ±5 %)  |  max=160  (se llena hasta ese
# máximo)  |  off (sin barra). Si no lo indicas se usa uno por defecto: +12V/+5V/+3.3V ±5 %, VSoC 1.30 V, CPU 160 W, GPU 300 W.
# Ejemplo:  cpu:Package | CPU PWR | max=140
# Se usa la primera alternativa cuyo nombre aparezca en el sensor (mayúsculas da igual).
# Una alternativa puede llevar el prefijo  cpu:  gpu:  o  mb:  para limitarla a ese hardware (p. ej. cpu:Package).
# `python install_gamehud.py --probe` lista todos los sensores que ve tu equipo y los guarda en gamehud_probe.txt.
# (Vcore y el voltaje de la GPU salen en sus paneles; el DIMM, en el de RAM.)
+12V
+5V
Northbridge | VSoC
cpu:Package | CPU PWR
gpu:Package | GPU PWR
# Otras opciones: +3.3V   |   GPU Core Voltage | VGPU
"""

VENDOR_README = """GameHUD - paquete para el programa estándar de TURZX
=====================================================

El programa oficial de TURZX usa un formato de tema propio que no se puede generar desde fuera
(ni este proyecto ni yo conocemos su especificación), así que NO hay un tema nativo para importar.
Esto es lo más parecido que se puede hacer: la misma imagen de fondo y los datos para recrear
los widgets a mano en el editor del programa oficial.

Contenido
  background_1280x800.png            fondo apaisado (el HUD sin valores: paneles, marcos, etiquetas, flechas)
  background_800x1280_vertical.png   el mismo fondo girado 90° por si el programa oficial trabaja en vertical
  preview_con_datos.png              cómo se ve con valores de ejemplo (objetivo a imitar)
  layout.csv                         cada elemento: posición X/Y, tamaño, tamaño de letra, color y texto de ejemplo

Cómo usarlo
  1. En el programa de TURZX elige "imagen/vídeo de fondo personalizado" (nombre aproximado) y carga el fondo.
  2. Añade los widgets disponibles (CPU, GPU, RAM, red, hora...) y colócalos según layout.csv.

Límites (importante para comparar)
  - El programa oficial solo ofrece los widgets que trae: no tiene FPS de RTSS, medidores por núcleo,
    discos múltiples con barra, VRAM/relojes en MHz, timings de RAM, resolución/Hz ni tiempo exterior.
    Esos elementos no se pueden reproducir allí; la comparación será de aspecto y de fluidez, no de contenido.
  - Las fuentes y los tamaños pueden no coincidir exactamente.
"""


def export_vendor(root):
    core_rel, core_file = pick_core_font(root)
    ex = root / "res" / "themes" / "theme_example.yaml"
    ex_stats = (read_yaml(ex) or {}).get("STATS", {}) if ex.exists() else {}
    stats, *_ = design(str(core_file), core_rel, ex_stats.get("DATE"), text_fontfile=str(root / "res" / "fonts" / FONT))
    out = Path.cwd() / "GameHUD_vendor"
    out.mkdir(exist_ok=True)
    bg = build_background(str(root / "res" / "fonts" / FONT), str(core_file), core_rel)
    bg.save(out / "background_1280x800.png")
    bg.rotate(-90, expand=True).save(out / "background_800x1280_vertical.png")
    build_preview(bg, stats, root / "res" / "fonts").save(out / "preview_con_datos.png")

    rows = []

    def walk(prefix, node):
        for k, v in node.items():
            if not isinstance(v, dict):
                continue
            comps = [c for c in ("TEXT", "GRAPH", "LINE_GRAPH") if isinstance(v.get(c), dict)]
            if comps:
                for c in comps:
                    d = v[c]
                    if d.get("SHOW"):
                        rows.append([f"{prefix}{k}", c, d.get("X"), d.get("Y"), d.get("WIDTH", ""), d.get("HEIGHT", ""),
                                     d.get("FONT_SIZE", ""), d.get("FONT_COLOR", d.get("BAR_COLOR", d.get("LINE_COLOR", ""))),
                                     SAMPLE.get(f"{prefix}{k}", "") if c == "TEXT" else ""])
            else:
                walk(prefix + k + ".", v)

    for grp, node in stats.items():
        walk("" if grp == "CUSTOM" else grp + ".", node)
    with open(out / "layout.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["elemento", "tipo", "x", "y", "ancho", "alto", "tam_letra", "color", "texto_ejemplo"])
        w.writerows(rows)
    (out / "LEEME.txt").write_text(VENDOR_README, encoding="utf8")
    print(f"Paquete para el programa oficial creado en {out}")


def preview_alertas(root):
    core_rel, core_file = pick_core_font(root)
    fontfile = root / "res" / "fonts" / FONT
    ex = root / "res" / "themes" / "theme_example.yaml"
    ex_stats = (read_yaml(ex) or {}).get("STATS", {}) if ex.exists() else {}
    stats, *_ = design(str(core_file), core_rel, ex_stats.get("DATE"), text_fontfile=str(fontfile))
    bg = build_background(str(fontfile), str(core_file), core_rel)
    out = Path.cwd() / "GameHUD_preview_alertas.png"
    build_preview(bg, stats, root / "res" / "fonts", alert=True).save(out)
    print(f"Vista previa con avisos guardada en {out}")


def preview_idle(root):
    core_rel, core_file = pick_core_font(root)
    fontfile = root / "res" / "fonts" / FONT
    ex = root / "res" / "themes" / "theme_example.yaml"
    ex_stats = (read_yaml(ex) or {}).get("STATS", {}) if ex.exists() else {}
    stats, *_ = design(str(core_file), core_rel, ex_stats.get("DATE"), text_fontfile=str(fontfile))
    bg = build_background(str(fontfile), str(core_file), core_rel)
    out = Path.cwd() / "GameHUD_preview_reposo.png"
    build_preview(bg, stats, root / "res" / "fonts", idle=True).save(out)
    print(f"Vista previa del modo reposo (sin juego) guardada en {out}")


def uninstall(root):
    sc = root / "library" / "sensors" / "sensors_custom.py"
    lines = [l for l in sc.read_text(encoding="utf8").splitlines() if TAG not in l]
    sc.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf8")
    for p in (root / "library" / "sensors" / "sensors_gamehud.py",):
        p.unlink(missing_ok=True)
    shutil.rmtree(root / "res" / "themes" / THEME, ignore_errors=True)
    print("GameHUD eliminado (sensors_custom.py restaurado quitando solo la línea añadida).")


def probe(root):
    sys.path.insert(0, str(root))
    os.chdir(root)
    import library.sensors.sensors_custom  # noqa: F401  (carga sensors_gamehud al final)
    from library.sensors import sensors_gamehud as g
    out = []

    def P(*a):
        line = " ".join(str(x) for x in a)
        out.append(line)
        print(line)

    st, fps, name = g._rtss_poll()
    P("RTSS:", {"off": "no detectado (¿está RTSS/Afterburner abierto?)",
                "idle": "activo, sin juego con overlay", "ok": f"{name} -> {fps:.0f} FPS"}[st])
    ms = g.all_metrics()
    if not ms:
        P("Sensores: ninguno. Error LHM:", g._LHM["err"] or "(sin error; ¿consola sin administrador?)")
    key = ("12v", "hvpwr", "16-pin", "input", "pcie")
    P("\nVOLTAJES, POTENCIAS Y CORRIENTES (placa y GPU)   [<<< = candidatos para el conector 12VHPWR]")
    for i, (h, n, v, u) in enumerate(ms, 1):
        mark = "  <<<" if h.startswith("Gpu") and any(k in n.lower() for k in key) else ""
        P(f"  {i:2d}. [{h[:12]:<12}] {n:<30}{v:9.3f} {u}{mark}")
    gpu_rows = [(n, v, u) for h, n, v, u in ms if h.startswith("Gpu")]
    P(f"\nDe la GPU se ven {len(gpu_rows)} sensores de voltaje/potencia/corriente" +
      ("" if gpu_rows else " (LHM no expone ninguno: el conector 12VHPWR no se puede leer por esta vía)"))
    fans = g.all_fans()
    P("\nVentiladores de la placa:" + ("" if fans else " ninguno visible"))
    for i, (n, v) in enumerate(fans, 1):
        P(f"  {i:2d}. {n:<28}{v:8.0f} RPM")
    cf, gf = g.cpu_fan(), g.gpu_fan()
    P(f"\nVentilador de CPU elegido: {cf if cf else 'ninguno'}   |   de GPU: {gf if gf else 'ninguno'}")
    P("Filas del panel POWER:", [(n, round(v, 3), u) for n, v, u in g._picked_voltages()])
    clk, used, total = g.gpu_info()
    P(f"\nGPU: reloj memoria={clk} MHz, VRAM usada={used} MB, total={total} MB  (None = LHM no lo expone)")
    g.HudRamSpeed().as_string()
    time.sleep(3)
    P("RAM:", g.HudRamSpeed().as_string())
    P("\nPara elegir otras filas del panel POWER, edita gamehud_voltages.txt (una línea por fila, máximo 5):\n"
      "  alternativa1, alternativa2 | etiqueta corta        (se usa la primera alternativa que exista)")
    (root / "gamehud_probe.txt").write_text("\n".join(out) + "\n", encoding="utf8")
    print(f"\n(Todo esto se ha guardado también en {root / 'gamehud_probe.txt'})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--vendor", action="store_true", help="genera el paquete para el programa oficial de TURZX")
    ap.add_argument("--alertas", action="store_true", help="genera GameHUD_preview_alertas.png (colores de aviso)")
    ap.add_argument("--reposo", action="store_true", help="genera GameHUD_preview_reposo.png (panel central sin juego)")
    a = ap.parse_args()
    r = find_root()
    probe(r) if a.probe else uninstall(r) if a.uninstall else export_vendor(r) if a.vendor else preview_alertas(r) if a.alertas else preview_idle(r) if a.reposo else install(r)
