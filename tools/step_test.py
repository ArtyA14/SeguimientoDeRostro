"""Prueba de cableado y sentido de giro (sin camara).

Mueve el motor a varias posiciones y muestra lo que reporta el Arduino.
Util para verificar IN1..IN4 y que el eje gire en el sentido esperado.

    python tools/step_test.py --port COM3
    python tools/step_test.py --port COM3 --amplitude 30
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracker.serial_link import SerialLink  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Prueba de movimiento del motor")
    ap.add_argument("--port", default="auto")
    ap.add_argument("--amplitude", type=float, default=20.0, help="grados a cada lado")
    ap.add_argument("--cycles", type=int, default=2)
    ap.add_argument("--rate", type=float, default=120.0, help="velocidad maxima (grados/s)")
    ap.add_argument("--accel", type=float, default=240.0, help="aceleracion (grados/s^2)")
    args = ap.parse_args()

    link = SerialLink(port=args.port, on_log=print)
    if not link.connect():
        print("No se pudo conectar. Revisa el puerto con: python main.py --list-ports")
        return 1

    link.set_motion(args.rate, args.accel)
    link.set_limits(-90.0, 90.0)
    time.sleep(2.2)  # el Arduino se resetea al abrir el puerto

    sequence = [0.0, args.amplitude, 0.0, -args.amplitude, 0.0] * args.cycles
    try:
        for i, angle in enumerate(sequence, 1):
            print(f"--> {angle:+6.1f} deg")
            link.send_target(angle, force=True)
            time.sleep(0.25)  # dejar que arranque antes de mirar 'moving'
            deadline = time.monotonic() + 12.0
            while time.monotonic() < deadline:
                st = link.status()
                if st["pos_deg"] is not None and not st["moving"]:
                    break
                time.sleep(0.05)
            st = link.status()
            print(f"    pos={st['pos_deg']} objetivo={st['target_deg']} limite={st['limit']}")
    finally:
        link.close()
    print("Prueba terminada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
