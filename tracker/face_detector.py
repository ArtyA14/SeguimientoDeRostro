"""Envoltorio de MediaPipe FaceLandmarker (API `mp.tasks`).

Nota importante: mediapipe >= 1.0 ya no incluye `mp.solutions`. Hay que usar
`mp.tasks.vision.FaceLandmarker` con el archivo `face_landmarker.task`, que se
descarga con `download_model.py`.

Se usa el modo VIDEO (no IMAGE) porque reutiliza el seguimiento entre frames:
es mas estable y mas barato que detectar desde cero en cada fotograma.
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

# Indices de landmarks utiles (malla de 478 puntos)
NOSE_TIP = 1
LEFT_EYE_OUTER = 33
RIGHT_EYE_OUTER = 263
CHIN = 152
FOREHEAD = 10


def _create_quietly(options: vision.FaceLandmarkerOptions):
    """Crea el landmarker silenciando los logs nativos de TFLite/glog.

    MediaPipe escribe varios WARNING por stderr al inicializar; son inofensivos
    pero ensucian la salida. Se capturan y solo se muestran si falla.
    """
    try:
        sys.stderr.flush()
        fd = sys.stderr.fileno()
    except (AttributeError, OSError, ValueError):
        return vision.FaceLandmarker.create_from_options(options)

    saved = os.dup(fd)
    tmp = tempfile.TemporaryFile()
    try:
        os.dup2(tmp.fileno(), fd)
        return vision.FaceLandmarker.create_from_options(options)
    except Exception as exc:
        tmp.seek(0)
        detail = tmp.read().decode("utf-8", "replace").strip()
        raise RuntimeError(f"No se pudo crear el FaceLandmarker: {exc}\n{detail}") from exc
    finally:
        os.dup2(saved, fd)
        os.close(saved)
        tmp.close()


@dataclass
class FaceInfo:
    """Rostro detectado, en pixeles y en coordenadas normalizadas."""

    cx: float  # centro horizontal (punta de la nariz)
    cy: float  # centro vertical
    width_px: float
    height_px: float
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    landmarks: list = field(default_factory=list, repr=False)


class FaceDetector:
    def __init__(
        self,
        model_path: str | Path,
        num_faces: int = 1,
        min_detection_confidence: float = 0.5,
        min_presence_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ) -> None:
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"No existe el modelo: {model_path}\n"
                "Ejecuta:  python download_model.py"
            )

        base_options = mp_python.BaseOptions(model_asset_path=str(model_path))
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_faces=num_faces,
            min_face_detection_confidence=min_detection_confidence,
            min_face_presence_confidence=min_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        self._landmarker = _create_quietly(options)
        self._last_ts_ms = -1

    # ------------------------------------------------------------------ detect
    def detect(self, frame_bgr: np.ndarray, timestamp_ms: int) -> FaceInfo | None:
        """Devuelve el rostro mas grande o None. `timestamp_ms` debe crecer."""
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        ts = int(timestamp_ms)
        if ts <= self._last_ts_ms:  # VIDEO exige timestamps estrictamente crecientes
            ts = self._last_ts_ms + 1
        self._last_ts_ms = ts

        result = self._landmarker.detect_for_video(image, ts)
        if not result.face_landmarks:
            return None

        # Si hubiera varias caras, elegir la de mayor area (la mas cercana)
        best = None
        best_area = -1.0
        for lms in result.face_landmarks:
            xs = [p.x for p in lms]
            ys = [p.y for p in lms]
            area = (max(xs) - min(xs)) * (max(ys) - min(ys))
            if area > best_area:
                best_area = area
                best = lms
        if best is None:
            return None

        xs = [p.x for p in best]
        ys = [p.y for p in best]
        nose = best[NOSE_TIP]

        return FaceInfo(
            cx=nose.x * w,
            cy=nose.y * h,
            width_px=(max(xs) - min(xs)) * w,
            height_px=(max(ys) - min(ys)) * h,
            x_min=min(xs) * w,
            y_min=min(ys) * h,
            x_max=max(xs) * w,
            y_max=max(ys) * h,
            landmarks=best,
        )

    # ------------------------------------------------------------------- misc
    def close(self) -> None:
        try:
            self._landmarker.close()
        except Exception:
            pass

    def __enter__(self) -> "FaceDetector":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
