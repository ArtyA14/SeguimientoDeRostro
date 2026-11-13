"""Diagnostico de la cadena PC -> Arduino -> servo.

Comprueba en orden: puerto, banner del firmware, lineas de estado, envio de
consignas y respuesta de posicion. Al final imprime un veredicto con el punto
exacto donde se rompe la cadena.

    python tools/diagnose.py
    python tools/diagnose.py --port COM3
    python tools/diagnose.py --no-move      # solo lectura, sin mover el servo
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracker.serial_link import SerialLink, autodetect_port, list_serial_ports  # noqa: E402

OK = "[ OK ]"
WARN = "[AVISO]"
FAIL = "[FALLO]"


def mostrar_puertos() -> str | None:
    ports = list_serial_ports()
    if not ports:
        print(f"{FAIL} No hay ningun puerto COM. Conecta el Arduino por USB.")
        return None
    print("Puertos detectados:")
    for p in ports:
        vid = f"{p['vid']:04X}" if p["vid"] is not None else "----"
        pid = f"{p['pid']:04X}" if p["pid"] is not None else "----"
        print(f"   {p['device']:<8} {p['description']:<35} VID:PID {vid}:{pid}")
    return autodetect_port()


def esperar(condicion, timeout: float, paso: float = 0.05) -> bool:
    lim = time.monotonic() + timeout
    while time.monotonic() < lim:
        if condicion():
            return True
        time.sleep(paso)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnostico del enlace con el Arduino")
    ap.add_argument("--port", default="auto")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--no-move", action="store_true", help="no mover el servo")
    ap.add_argument("--sweep", action="store_true", help="barrido amplio +-45 grados para verlo a simple vista")
    args = ap.parse_args()

    print("=" * 60)
    print(" DIAGNOSTICO: PC -> Arduino -> servo")
    print("=" * 60)

    # 1. Puerto ------------------------------------------------------------
    port = args.port
    if port.lower() == "auto":
        port = mostrar_puertos()
        if port is None:
            return 1
        print(f"{OK} Puerto autodetectado: {port}")

    # 2. Conexion ----------------------------------------------------------
    link = SerialLink(port=port, baud=args.baud, on_log=print)
    if not link.connect():
        print(f"{FAIL} No se pudo abrir {port}.")
        print("        - Cierra el Monitor Serie del IDE de Arduino")
        print("        - Comprueba que el COM es el correcto")
        return 1
    print(f"{OK} Puerto abierto. Esperando arranque del Arduino...")

    problemas: list[str] = []

    # 3. Banner ------------------------------------------------------------
    esperar(lambda: link.banner is not None, 4.0)
    if link.banner is None:
        print(f"{FAIL} El Arduino no envia el banner 'R ...'.")
        problemas.append("El firmware no responde: probablemente no esta cargado servo_tracker.ino.")
    else:
        print(f"{OK} Firmware: {link.banner}")
        if "servo_tracker" not in link.banner:
            print(f"{FAIL} Ese no es el firmware del servo.")
            problemas.append(
                f"Hay otro sketch cargado ('{link.banner}'). Sube arduino/servo_tracker/servo_tracker.ino."
            )
        else:
            # El auto-test de arranque (90->45->135->90) dura ~2 s: esperar a
            # que el servo quede quieto en el centro antes de medir nada.
            print("       esperando el auto-test de arranque del servo...")
            time.sleep(2.2)
            esperar(lambda: link.state.pos_deg is not None
                    and abs(link.state.pos_deg) < 0.5 and not link.state.moving, 4.0)

    # 4. Lineas de estado --------------------------------------------------
    vistos = set()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 2.0:
        raw = link.state.raw
        if raw:
            vistos.add(raw)
        time.sleep(0.05)
    if not vistos:
        print(f"{FAIL} No llegan lineas de estado 'S ...'.")
        problemas.append("Sin telemetria: revisa baudios (115200) o el sketch cargado.")
    else:
        print(f"{OK} Telemetria activa ({len(vistos)} estados distintos en 2 s)")
        print(f"        ultimo: {link.state.raw}")

    st = link.status()
    print(f"        posicion={st['pos_deg']} objetivo={st['target_deg']} moviendo={st['moving']}")

    # 5. Envio de consignas -----------------------------------------------
    if not args.no_move:
        print("\nProbando consignas (el servo deberia girar):")
        for angle in (0.0, 25.0, -25.0, 0.0):
            link.send_target(angle, force=True)
            ok = esperar(lambda: link.state.target_deg is not None and abs(link.state.target_deg - angle) < 1.0, 2.0)
            if not ok:
                print(f"{FAIL} Enviado P {angle:+.0f} pero el Arduino no actualiza el objetivo "
                      f"(objetivo={link.state.target_deg})")
                problemas.append("El Arduino recibe el comando pero no lo aplica (firmware incorrecto).")
                break

            movio = esperar(lambda: not link.state.moving, 6.0)
            pos = link.state.pos_deg
            if not movio:
                print(f"{FAIL} Se quedo 'moviendo' con objetivo {angle:+.0f} y posicion {pos}")
                problemas.append("El servo no alcanza la consigna (cableado de senal/GND o alimentacion).")
                break

            cerca = pos is not None and abs(pos - angle) < 2.0
            marca = OK if cerca else WARN
            print(f"{marca} P {angle:+5.1f}  ->  posicion {pos:+.2f}  (moviendo={link.state.moving})")
            if not cerca:
                problemas.append("La posicion reportada no coincide con la consigna.")
                break
            time.sleep(0.3)

    # 5b. Barrido visible (para confirmar movimiento fisico) ---------------
    if args.sweep and not args.no_move:
        print("\nBarrido visible (+-45 grados, 3 ciclos) - mira el servo:")
        link.set_motion(90, 180)  # despacio para poder verlo
        time.sleep(0.2)
        for i in range(3):
            for angle in (45.0, -45.0):
                link.send_target(angle, force=True)
                esperar(lambda: not link.state.moving, 4.0)
                time.sleep(0.25)
            print(f"   ciclo {i + 1}/3 hecho")
        link.send_target(0.0, force=True)
        esperar(lambda: not link.state.moving, 4.0)
        print("   vuelta al centro")
        print("   (la posicion es calculada por el firmware: no hay realimentacion)")

    link.close()

    # 6. Veredicto ---------------------------------------------------------
    print("\n" + "=" * 60)
    if not problemas:
        print(f"{OK} TODO CORRECTO.")
        print("      Si el servo no se mueve con main.py, revisa que la camara")
        print("      detecte el rostro y que 'invert'/'offset' esten calibrados.")
        return 0

    print(f"{FAIL} Se encontraron {len(problemas)} problema(s):")
    for i, p in enumerate(problemas, 1):
        print(f"  {i}. {p}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
