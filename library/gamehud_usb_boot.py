# GameHUD - arranque robusto de la pantalla TURZX por USB.
#
# PROBLEMA QUE RESUELVE
#   1) La pantalla TURZX no siempre aparece en el bus USB en el instante en que arranca
#      el programa (recien encendido el PC, tras suspender, al enchufarla, o cuando el
#      concentrador USB reinicia el dispositivo). Si no esta, find_usb_device() lanza
#      ValueError y el programa MUERE durante el import: codigo de salida 0 y ningun
#      mensaje en pantalla, porque pythonw no tiene consola. La tarea programada lo
#      daba por bueno y no lo reiniciaba.
#   2) libusb da acceso EXCLUSIVO al dispositivo. Si otra instancia del HUD lo tiene
#      abierto, find_usb_device() tampoco lo ve. Asi que al pulsar "Save & run" en el
#      configurador mientras la instancia antigua sigue viva, la nueva moria en
#      silencio y la vieja se queda con "Access denied" al apagar la pantalla.
#
# QUE HACE
#   Reintenta la busqueda del dispositivo durante un rato, dejando constancia en
#   log.log (que es el unico sitio donde se ve algo, al no haber consola), y pide a
#   Windows que re-enumere los dispositivos USB por si la pantalla se ha quedado en
#   un estado fantasma.
#
# DONDE SE CARGA
#   library/config.py es lo primero que importa cualquier ejecutable del proyecto
#   (main.py, configure.py, theme-editor.py), asi que el parche se aplica antes de
#   que nadie intente abrir la pantalla. La linea la anade install_gamehud.py.
#
# Compatible con Python 3.9+ (igual que el resto del proyecto).

import subprocess
import time

from library.log import logger

# Segundos que se espera a que aparezca la pantalla al arrancar.
WAIT_SECONDS = 90

# Instantes (en segundos desde el primer fallo) en los que se pide a Windows que
# re-enumere los dispositivos USB: rescata la pantalla cuando Windows la ha dejado
# en un estado fantasma (aparece en el Panel de control pero libusb no la ve).
RESCAN_AFTER = (8, 25, 50)

# Cada cuantos segundos se recuerda en el log que se sigue esperando.
LOG_EVERY = 15


def _rescan_usb():
    """Pide a Windows que vuelva a enumerar los dispositivos USB (resucita los fantasma)."""
    try:
        subprocess.run(
            ["pnputil", "/scan-devices"],
            capture_output=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        logger.info("GameHUD: se ha pedido a Windows que re-enumere los dispositivos USB")
    except Exception as e:  # noqa: BLE001 - es una mejora, nunca debe romper el arranque
        logger.debug("GameHUD: no se pudo re-enumerar USB: %s", e)


def _find_usb_device(orig, wait):
    """Llama a find_usb_device() original reintentando hasta que el dispositivo aparezca."""
    started = time.monotonic()
    deadline = started + wait
    announced = 0.0
    scans = 0
    while True:
        try:
            return orig()
        except Exception as e:  # noqa: BLE001 - se reintenta hasta agotar el tiempo
            now = time.monotonic()
            if now >= deadline:
                logger.error(
                    "GameHUD: la pantalla TURZX no aparece en USB tras %d s (%s). "
                    "Comprueba el cable USB y que la pantalla este encendida.",
                    wait, e,
                )
                raise
            if announced == 0.0:
                announced = now
                logger.warning(
                    "GameHUD: esperando a la pantalla TURZX en USB (hasta %d s)...", wait
                )
            elif now - announced >= LOG_EVERY:
                announced = now
                logger.info("GameHUD: la pantalla TURZX sigue sin aparecer; reintentando...")
            if scans < len(RESCAN_AFTER) and now - started >= RESCAN_AFTER[scans]:
                scans += 1
                _rescan_usb()
            time.sleep(1.0)


def install():
    """Parchea find_usb_device() para que reintente en vez de morir al instante."""
    try:
        from library.lcd import lcd_comm_turing_usb as t
    except Exception as e:  # noqa: BLE001 - si no hay USB este parche no aplica
        logger.debug("GameHUD: no se instalo la espera de USB: %s", e)
        return

    # El driver TUR_USB ya incluye reconexión infinita (con re-enumeración y
    # restauración de estado). Duplicar la espera sólo añadiría 90 s de retardo
    # y dificultaría salir de la aplicación mientras la pantalla está ausente.
    if hasattr(getattr(t, "LcdCommTuringUSB", None), "_connect"):
        logger.info("GameHUD: reconexión USB nativa activa; se omite la espera de arranque duplicada")
        return

    orig = getattr(t, "find_usb_device", None)
    if orig is None:
        return
    if getattr(orig, "_gamehud", False):
        return

    def find_usb_device(wait=WAIT_SECONDS):
        return _find_usb_device(orig, wait)

    find_usb_device._gamehud = True
    # El original se guarda para las llamadas internas que no deben esperar
    # (por ejemplo, reconectar la pantalla con el USB ya ocupado).
    find_usb_device.original = orig
    t.find_usb_device = find_usb_device
    logger.info("GameHUD: espera de la pantalla USB activada (%d s)", WAIT_SECONDS)


install()
