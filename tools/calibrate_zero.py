"""Calibracion del offset mecanico entre la camara y el efector.

El motor debe apuntar al mismo sitio que ve la camara en el centro de la
imagen. Este asistente mueve el motor con el teclado hasta que el efector
apunta al objetivo; al guardar, escribe `aiming.offset_deg` en config.json.

    python tools/calibrate_zero.py --port COM3

Teclas:
    a / d      mover -2 / +2 grados
    A / D      mover -10 / +10 grados  (Shift)
    Enter      guardar offset y salir
    Esc        salir sin guardar
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracker.serial_link import SerialLink  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description="Calibrar offset del motor")
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--port", default="auto")
    ap.add_argument("--camera", type=int, default=0)
    args = ap.parse_args()

    cfg_path = Path(args.config)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    link = SerialLink(port=args.port, on_log=print)
    if not link.connect():
        print("No se pudo conectar al Arduino.")
        return 1
    time.sleep(2.2)

    cam_cfg = cfg.get("camera", {})
    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print("No se pudo abrir la camara.")
        link.close()
        return 1

    st = link.status()
    pos = st["pos_deg"] if st["pos_deg"] is not None else 0.0
    cmd = pos
    print(f"Posicion inicial: {pos:+.1f} deg")
    print("Mueve con a/d (2 deg) o A/D (10 deg). Enter guarda, Esc cancela.")

    saved = None
    try:
        while True:
            ok, frame = cap.read()
            if ok:
                h, w = frame.shape[:2]
                cv2.line(frame, (w // 2, 0), (w // 2, h), (0, 220, 0), 1)
                cv2.putText(
                    frame,
                    f"offset candidato: {cmd:+.1f} deg",
                    (12, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 220, 0),
                    2,
                )
                cv2.putText(
                    frame,
                    "a/d=2deg  A/D=10deg  Enter=guardar  Esc=salir",
                    (12, h - 14),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (200, 200, 200),
                    1,
                )
                cv2.imshow("Calibrar offset", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            if key in (13, 10):
                # esperar a que el motor termine de llegar antes de medir
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    st = link.status()
                    if st["pos_deg"] is not None and not st["moving"]:
                        break
                    time.sleep(0.05)
                st = link.status()
                saved = st["pos_deg"] if st["pos_deg"] is not None else cmd
                break
            step = 0.0
            if key == ord("a"):
                step = -2.0
            elif key == ord("d"):
                step = 2.0
            elif key == ord("A"):
                step = -10.0
            elif key == ord("D"):
                step = 10.0
            if step:
                cmd = max(-90.0, min(90.0, cmd + step))
                link.send_target(cmd, force=True)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        link.close()

    if saved is None:
        print("Cancelado, no se guardo nada.")
        return 0

    cfg.setdefault("aiming", {})["offset_deg"] = round(saved, 2)
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Guardado: aiming.offset_deg = {saved:+.2f} en {cfg_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
