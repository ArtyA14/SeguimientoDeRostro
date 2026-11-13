"""Dibujo del HUD sobre el frame (OpenCV).

Solo texto ASCII: cv2.putText no renderiza acentos de forma fiable.
"""

from __future__ import annotations

import cv2
import numpy as np

GREEN = (80, 220, 80)
YELLOW = (0, 210, 255)
RED = (60, 60, 235)
GRAY = (170, 170, 170)
WHITE = (245, 245, 245)
DARK = (25, 25, 25)


def _panel(frame: np.ndarray, x: int, y: int, w: int, h: int, alpha: float = 0.55) -> None:
    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + w, y + h), DARK, -1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


def draw(
    frame: np.ndarray,
    face,
    aim,
    status: dict,
    fps: float,
    *,
    show_landmarks: bool = False,
    mode: str = "aim",
    warning: str | None = None,
    show_status: bool = True,
) -> np.ndarray:
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2

    # Cruz central = eje optico de la camara
    cv2.line(frame, (cx, 0), (cx, h), (70, 70, 70), 1)
    cv2.line(frame, (0, cy), (w, cy), (70, 70, 70), 1)
    cv2.drawMarker(frame, (cx, cy), GRAY, cv2.MARKER_CROSS, 18, 1)

    color = GREEN if face is not None else YELLOW

    if face is not None:
        x1, y1 = int(face.x_min), int(face.y_min)
        x2, y2 = int(face.x_max), int(face.y_max)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.circle(frame, (int(face.cx), int(face.cy)), 5, color, -1)
        cv2.line(frame, (cx, cy), (int(face.cx), int(face.cy)), color, 1, cv2.LINE_AA)

        if show_landmarks and face.landmarks:
            for p in face.landmarks:
                cv2.circle(frame, (int(p.x * w), int(p.y * h)), 1, (0, 200, 255), -1)

    # Panel de estado
    # (se oculta mientras la pestana de ajustes esta abierta)
    if not show_status:
        return frame

    lines = []
    if aim.face_angle_deg is not None:
        lines.append(f"Angulo rostro : {aim.face_angle_deg:+6.1f} deg")
    else:
        lines.append("Angulo rostro :   ---")
    lines.append(f"Consigna motor: {aim.target_deg:+6.1f} deg")
    lines.append(f"Ganancia motor: x{getattr(aim, 'gain', 1.0):4.2f}")

    if status.get("pos_deg") is not None:
        lines.append(f"Posicion real : {status['pos_deg']:+6.1f} deg")
    else:
        lines.append("Posicion real :   ---")

    if status.get("camera") is not None:
        mirror_txt = "on" if status.get("mirror") else "off"
        lines.append(f"Camara        : {status['camera']}   espejo: {mirror_txt}")

    if status.get("connected"):
        port = status.get("port") or "?"
        if status.get("stale"):
            link_txt, link_col = f"Serial: {port} (sin datos)", YELLOW
        else:
            link_txt, link_col = f"Serial: {port} OK", GREEN
    else:
        link_txt, link_col = "Serial: sin conexion", RED
    lines.append(link_txt)

    lines.append(f"FPS: {fps:5.1f}   modo: {mode}")

    line_h = 22
    panel_h = line_h * len(lines) + 12
    text_w = max(cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)[0][0] for t in lines)
    _panel(frame, 8, 8, max(250, text_w + 22), panel_h)
    for i, text in enumerate(lines):
        col = link_col if text.startswith("Serial") else WHITE
        if text.startswith("Angulo rostro") and face is None:
            col = YELLOW
        cv2.putText(
            frame,
            text,
            (16, 30 + i * line_h),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            col,
            1,
            cv2.LINE_AA,
        )

    # Aviso si se alcanzo un limite
    if status.get("limit"):
        cv2.putText(frame, "LIMITE ALCANZADO", (16, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, RED, 2, cv2.LINE_AA)

    # Aviso importante (sketch equivocado, sin serial, etc.)
    if warning:
        text = warning.upper()
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        x = max(8, (w - tw) // 2)
        y = h - 62
        overlay = frame.copy()
        cv2.rectangle(overlay, (x - 10, y - th - 10), (x + tw + 10, y + 10), (20, 20, 90), -1)
        cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
        cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (90, 200, 255), 2, cv2.LINE_AA)

    # Ayuda de teclas (con banda oscura para que se lea sobre imagen clara)
    help_txt = "TAB ajustes | q salir | z cero | h hold | x soltar | m espejo"
    (hw, hh), _ = cv2.getTextSize(help_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    hx, hy = w - hw - 20, h - hh - 14
    _panel(frame, hx - 6, hy - 4, hw + 12, hh + 12)
    cv2.putText(frame, help_txt, (hx, hy + hh), cv2.FONT_HERSHEY_SIMPLEX, 0.45, GRAY, 1, cv2.LINE_AA)

    return frame
