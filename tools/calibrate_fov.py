"""Calibracion del campo de vision horizontal (h_fov_deg).

Metodo del ruler:
  1. Pon una cinta metrica perpendicular a la camara, a una distancia D.
  2. Mira en la ventana que tramo de la cinta ocupa el ancho completo de la
     imagen (desde el borde izquierdo al derecho). Ese tramo es S.
  3. FOV = 2 * atan((S/2) / D)

    python tools/calibrate_fov.py
    python tools/calibrate_fov.py --distance 100 --span 135

Sin camara tambien sirve: pasa --distance y --span por consola.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]


def compute_fov(distance_cm: float, span_cm: float) -> float:
    if distance_cm <= 0 or span_cm <= 0:
        raise ValueError("la distancia y el tramo deben ser positivos")
    return math.degrees(2.0 * math.atan((span_cm / 2.0) / distance_cm))


def ask_float(prompt: str) -> float:
    while True:
        raw = input(prompt).strip().replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            print("  valor no valido, intenta de nuevo")


def capture_span(camera_index: int) -> tuple[float, float] | None:
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print("No se pudo abrir la camara. Usa --distance y --span.")
        return None

    print("Coloca la cinta metrica perpendicular a la camara.")
    print("Pulsa ESPACIO para congelar la imagen, Esc para cancelar.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            cv2.line(frame, (2, 0), (2, h), (0, 220, 0), 2)
            cv2.line(frame, (w - 3, 0), (w - 3, h), (0, 220, 0), 2)
            cv2.putText(
                frame,
                "Ajusta la cinta: el tramo visible entre las lineas verdes = S",
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 220, 0),
                1,
            )
            cv2.putText(
                frame,
                "ESPACIO = capturar   Esc = cancelar",
                (12, h - 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (200, 200, 200),
                1,
            )
            cv2.imshow("Calibrar FOV", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                return None
            if key == 32:
                return (ask_float("Distancia camara-cinta D (cm): "), ask_float("Tramo visible S (cm): "))
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> int:
    ap = argparse.ArgumentParser(description="Calibrar FOV horizontal")
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--distance", type=float, help="distancia en cm")
    ap.add_argument("--span", type=float, help="tramo visible en cm")
    ap.add_argument("--save", action="store_true", help="escribir h_fov_deg en config.json")
    args = ap.parse_args()

    if args.distance and args.span:
        distance, span = args.distance, args.span
    else:
        got = capture_span(args.camera)
        if got is None:
            print("Cancelado.")
            return 0
        distance, span = got

    fov = compute_fov(distance, span)
    print(f"\nFOV horizontal = {fov:.1f} deg")
    print(f"(D={distance:.0f} cm, S={span:.0f} cm -> mitad del angulo = {fov / 2:.1f} deg)")

    if args.save:
        cfg_path = Path(args.config)
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg.setdefault("aiming", {})["h_fov_deg"] = round(fov, 1)
        cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Guardado en {cfg_path}: aiming.h_fov_deg = {fov:.1f}")
    else:
        print("No se guardo nada. Anade --save o edita config.json a mano.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
