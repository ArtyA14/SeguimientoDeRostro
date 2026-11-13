"""Captura de video con reconexion automatica.

En Windows se usa el backend DSHOW porque abre mucho mas rapido que MSMF
y no se queda colgado cuando la camara esta ocupada.
"""

from __future__ import annotations

import platform
import time
from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


class Camera:
    def __init__(
        self,
        index: int = 0,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        mirror: bool = False,
    ) -> None:
        self.index = index
        self.width = width
        self.height = height
        self.fps = fps
        self.mirror = mirror
        self._cap: cv2.VideoCapture | None = None
        self._failures = 0
        self._last_open = 0.0

    # ------------------------------------------------------------------ open
    def open(self) -> bool:
        backends = [cv2.CAP_DSHOW] if platform.system() == "Windows" else []
        backends.append(cv2.CAP_ANY)

        for backend in backends:
            cap = cv2.VideoCapture(self.index, backend)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                cap.set(cv2.CAP_PROP_FPS, self.fps)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self._cap = cap
                self._failures = 0
                self._last_open = time.monotonic()
                return True
            cap.release()

        self._cap = None
        return False

    # ------------------------------------------------------------------ read
    def read(self) -> np.ndarray | None:
        if self._cap is None:
            if time.monotonic() - self._last_open < 1.0:
                return None
            return self._reopen()

        ok, frame = self._cap.read()
        if ok and frame is not None:
            self._failures = 0
            if self.mirror:
                frame = cv2.flip(frame, 1)
            return frame

        self._failures += 1
        if self._failures >= 15:  # ~0.5 s sin imagen: reabrir
            return self._reopen()
        return None

    def _reopen(self) -> np.ndarray | None:
        self.close()
        self._last_open = time.monotonic()
        if not self.open():
            return None
        ok, frame = self._cap.read() if self._cap is not None else (False, None)
        if ok and frame is not None:
            self._failures = 0
            if self.mirror:
                frame = cv2.flip(frame, 1)
            return frame
        return None

    # ----------------------------------------------------------------- close
    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class FileSource:
    """Fuente de video desde archivo (imagen fija o video), para pruebas.

    Con una imagen repite el mismo frame; con un video lo reproduce en bucle.
    Tiene la misma interfaz que Camera (open/read/close/mirror).
    """

    def __init__(self, path: str | Path, mirror: bool = False) -> None:
        self.path = str(path)
        self.mirror = mirror
        self._image: np.ndarray | None = None
        self._cap: cv2.VideoCapture | None = None

        if Path(self.path).suffix.lower() in IMAGE_EXTS:
            img = cv2.imread(self.path)
            if img is None:
                raise FileNotFoundError(f"No se pudo leer la imagen: {self.path}")
            self._image = img
        else:
            cap = cv2.VideoCapture(self.path)
            if not cap.isOpened():
                raise FileNotFoundError(f"No se pudo abrir el video: {self.path}")
            self._cap = cap

    def open(self) -> bool:
        return self._image is not None or self._cap is not None

    def read(self) -> np.ndarray | None:
        if self._image is not None:
            frame = self._image.copy()
        else:
            assert self._cap is not None
            ok, frame = self._cap.read()
            if not ok:  # rebobinar al terminar
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
            if not ok or frame is None:
                return None
        if self.mirror:
            frame = cv2.flip(frame, 1)
        return frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
