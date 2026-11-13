"""Pestana de ajustes dentro de la misma ventana de video.

Permite elegir el puerto COM y la camara sin cerrar la aplicacion: se abre con
TAB (o con el raton sobre la pestana AJUSTES), se navega con las flechas o
W/A/S/D y se aplica con ENTER o con el boton APLICAR.

El panel solo dibuja sobre el frame: no depende de Qt ni de Tk, asi que
funciona con cualquier backend de OpenCV.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

FONT = cv2.FONT_HERSHEY_SIMPLEX

DARK = (22, 22, 22)
CARD = (34, 34, 34)
ROW = (46, 46, 46)
ROW_SEL = (78, 84, 96)
WHITE = (240, 240, 240)
GRAY = (165, 165, 165)
ACCENT = (0, 200, 255)   # ambar (BGR)
GREEN = (90, 220, 90)
RED = (80, 80, 235)

MAX_ROWS = 7
CARD_W = 640
CARD_H = 340

# Codigos de flecha que devuelve cv2.waitKeyEx (Windows y GTK)
UP = 2490368
DOWN = 2621440
LEFT = 2424832
RIGHT = 2555904


def _panel(frame: np.ndarray, x: int, y: int, w: int, h: int, color=DARK, alpha: float = 0.78) -> None:
    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + w, y + h), color, -1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


def _fit(text: str, max_px: int, scale: float = 0.5) -> str:
    """Recorta el texto para que quepa en `max_px` pixeles."""
    if cv2.getTextSize(text, FONT, scale, 1)[0][0] <= max_px:
        return text
    while text and cv2.getTextSize(text + "...", FONT, scale, 1)[0][0] > max_px:
        text = text[:-1]
    return text + "..."


class SettingsPanel:
    """Estado + dibujo + teclado/raton de la pestana de ajustes."""

    def __init__(self, ports: list[dict], cameras: list[int], port: str | None = None, cam: int = 0) -> None:
        self.visible = False
        self.ports = list(ports)
        self.cameras = list(cameras)
        self.port_active = port
        self.cam_active = cam
        self.focus = 0                      # 0 = puertos, 1 = camaras
        self.port_sel = self._index_of_port(port)
        self.cam_sel = self._index_of_cam(cam)
        self.message = ""
        self.message_ok = True
        self.message_until = 0.0
        self._hits: list[tuple[tuple[int, int, int, int], tuple]] = []
        self._click: tuple[int, int] | None = None

    # --------------------------------------------------------------- estado
    def _index_of_port(self, port: str | None) -> int:
        for i, p in enumerate(self.port_entries):
            if p["device"] == (port or "auto"):
                return i
        return 0

    def _index_of_cam(self, cam: int) -> int:
        try:
            return self.cameras.index(int(cam))
        except ValueError:
            return 0

    @property
    def port_entries(self) -> list[dict]:
        auto = {"device": "auto", "description": "detectar automaticamente"}
        return [auto] + self.ports

    def set_message(self, text: str, ok: bool = True) -> None:
        self.message = text
        self.message_ok = ok
        self.message_until = time.monotonic() + 4.0

    def selected_port(self) -> str:
        return self.port_entries[self.port_sel]["device"]

    def selected_cam(self) -> int:
        return self.cameras[self.cam_sel]

    def refresh_ports(self, ports: list[dict] | None = None) -> None:
        if ports is not None:
            self.ports = list(ports)
        self.port_sel = max(0, min(self.port_sel, len(self.port_entries) - 1))

    # ------------------------------------------------------------ raton/teclas
    def on_mouse(self, event: int, x: int, y: int, flags: int, param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            self._click = (x, y)

    def take_click(self) -> tuple[int, int] | None:
        click, self._click = self._click, None
        return click

    def click(self, x: int, y: int) -> tuple | None:
        for (rx, ry, rw, rh), action in self._hits:
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                if action[0] == "pick":
                    self.focus, index = action[1], action[2]
                    if self.focus == 0:
                        self.port_sel = index
                    else:
                        self.cam_sel = index
                    return ("pick",)
                if action[0] == "tab":
                    self.visible = bool(action[1])
                    return ("toggle",)
                return action
        return None

    def handle_key(self, raw: int, key: int) -> tuple | None:
        """Devuelve una accion: ('toggle',), ('close',), ('apply', puerto, camara)."""
        if key == 9:  # TAB
            self.visible = not self.visible
            return ("toggle",)
        if not self.visible:
            return None
        if key in (27, ord("q")):
            self.visible = False
            return ("close",)
        if key in (13, 10):  # ENTER
            return ("apply", self.selected_port(), self.selected_cam())
        if key == ord("r"):
            self.refresh_ports()
            self.set_message("Lista de puertos actualizada")
            return ("refresh",)

        step = 0
        if raw == UP or key == ord("w"):
            step = -1
        elif raw == DOWN or key == ord("s"):
            step = +1
        if step:
            if self.focus == 0:
                self.port_sel = max(0, min(self.port_sel + step, len(self.port_entries) - 1))
            else:
                self.cam_sel = max(0, min(self.cam_sel + step, len(self.cameras) - 1))
            return ("nav",)

        if raw in (LEFT, RIGHT) or key in (ord("a"), ord("d")):
            self.focus = 1 - self.focus
            return ("focus",)
        return None

    # ----------------------------------------------------------------- dibujo
    def draw(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        self._hits = []

        self._draw_tabs(frame, w)
        if self.visible:
            self._draw_card(frame, w, h)
        return frame

    # pestana superior derecha: VISTA | AJUSTES
    def _draw_tabs(self, frame: np.ndarray, w: int) -> None:
        labels = ("VISTA", "AJUSTES")
        pad, gap, th = 12, 6, 24
        widths = [cv2.getTextSize(t, FONT, 0.45, 1)[0][0] + pad * 2 for t in labels]
        total = sum(widths) + gap * (len(labels) - 1)
        x = max(8, w - total - 10)
        y = 8
        for i, (text, tw) in enumerate(zip(labels, widths)):
            active = (i == 1) == self.visible
            color = ACCENT if active else CARD
            _panel(frame, x, y, tw, th, color, 0.85 if active else 0.55)
            tc = DARK if active else GRAY
            cv2.putText(frame, text, (x + pad, y + 17), FONT, 0.45, tc, 1, cv2.LINE_AA)
            self._hits.append(((x, y, tw, th), ("tab", i)))
            x += tw + gap

    def _draw_card(self, frame: np.ndarray, w: int, h: int) -> None:
        cw = min(CARD_W, w - 20)
        ch = min(CARD_H, h - 16)
        x0 = (w - cw) // 2
        y0 = max(8, (h - ch) // 2)

        _panel(frame, x0, y0, cw, ch, DARK, 0.94)
        cv2.rectangle(frame, (x0, y0), (x0 + cw, y0 + ch), (90, 90, 90), 1)

        cv2.putText(frame, "AJUSTES", (x0 + 18, y0 + 28), FONT, 0.62, ACCENT, 2, cv2.LINE_AA)
        if self.message and time.monotonic() < self.message_until:
            col = GREEN if self.message_ok else RED
            cv2.putText(frame, _fit(self.message, cw - 36, 0.45), (x0 + 18, y0 + ch - 52),
                        FONT, 0.45, col, 1, cv2.LINE_AA)

        col_w = (cw - 54) // 2
        left_x = x0 + 18
        right_x = x0 + 36 + col_w
        top = y0 + 58

        self._draw_column(frame, "PUERTO COM", self.port_entries, self.port_sel, self.focus == 0, 0,
                          left_x, top, col_w, self._port_label, self.port_active)
        self._draw_column(frame, "CAMARA", [{"device": str(c), "description": "indice de camara"} for c in self.cameras],
                          self.cam_sel, self.focus == 1, 1, right_x, top, col_w,
                          lambda p: f"Camara {p['device']}", str(self.cam_active))

        # Boton APLICAR
        bw, bh = 120, 30
        bx, by = x0 + 18, y0 + ch - 44
        _panel(frame, bx, by, bw, bh, (60, 90, 40), 0.95)
        cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), GREEN, 1)
        tw = cv2.getTextSize("APLICAR", FONT, 0.5, 1)[0][0]
        cv2.putText(frame, "APLICAR", (bx + (bw - tw) // 2, by + 20), FONT, 0.5, GREEN, 1, cv2.LINE_AA)
        self._hits.append(((bx, by, bw, bh), ("apply", self.selected_port(), self.selected_cam())))

        cv2.putText(frame, "TAB cerrar | W/S mover | A/D columna | ENTER aplicar | R refrescar",
                    (x0 + 150, y0 + ch - 23), FONT, 0.4, GRAY, 1, cv2.LINE_AA)

    def _port_label(self, p: dict) -> str:
        if p["device"] == "auto":
            return "auto (detectar)"
        desc = p.get("description") or ""
        return f"{p['device']}  {desc}" if desc else p["device"]

    def _draw_column(self, frame, title, entries, sel, focused, focus_id, x, y, width, label, active) -> None:
        col = ACCENT if focused else WHITE
        cv2.putText(frame, title, (x, y), FONT, 0.5, col, 1, cv2.LINE_AA)
        if focused:
            cv2.line(frame, (x, y + 5), (x + cv2.getTextSize(title, FONT, 0.5, 1)[0][0], y + 5), ACCENT, 1)

        rows = len(entries)
        start = 0
        if rows > MAX_ROWS:
            start = max(0, min(sel - MAX_ROWS + 1, rows - MAX_ROWS))
        shown = entries[start:start + MAX_ROWS]

        row_h = 24
        for i, entry in enumerate(shown):
            idx = start + i
            ry = y + 12 + i * row_h
            rx = x - 6
            rw = width + 8
            if idx == sel:
                cv2.rectangle(frame, (rx, ry), (rx + rw, ry + row_h - 2), ROW_SEL, -1)
            text = label(entry)
            is_active = str(entry["device"]) == str(active)
            mark = "* " if is_active else "  "
            color = GREEN if is_active else (WHITE if idx == sel else GRAY)
            cv2.putText(frame, mark + _fit(text, rw - 24, 0.45), (x, ry + 17),
                        FONT, 0.45, color, 1, cv2.LINE_AA)
            self._hits.append(((rx, ry, rw, row_h - 2), ("pick", focus_id, idx)))

        if rows > MAX_ROWS:
            extra = rows - start - MAX_ROWS
            if extra > 0:
                cv2.putText(frame, f"... {extra} mas", (x, y + 12 + MAX_ROWS * row_h + 12),
                            FONT, 0.4, GRAY, 1, cv2.LINE_AA)
