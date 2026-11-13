"""Conversion rostro -> angulo de motor, con suavizado y limites.

La camara esta fija y el motor mueve el efector (laser, foco, pantalla...).
Por eso el control es de APUNTADO, no de bucle cerrado:

    angulo_rostro = atan((x - cx) / fx)          # geometria de pinhole
    angulo_motor  = offset + gain * angulo_rostro

donde `fx` sale del campo de vision horizontal (h_fov_deg) y `offset` es la
calibracion mecanica entre el eje de la camara y el del efector.

Si algun dia montas la camara SOBRE el motor, usa mode="closed_loop":
    angulo_motor += kp * angulo_rostro
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class AimState:
    target_deg: float          # consigna enviada al Arduino
    ema_deg: float             # valor filtrado antes de limites
    face_angle_deg: float | None
    has_face: bool
    returning: bool = False
    gain: float = 1.0          # multiplicador de angulo activo


class Aimer:
    def __init__(
        self,
        *,
        h_fov_deg: float = 68.0,
        offset_deg: float = 0.0,
        invert: bool = False,
        angle_gain: float = 1.0,
        ema_alpha: float = 0.25,
        deadband_deg: float = 1.5,
        max_rate_deg_s: float = 45.0,
        min_deg: float = -90.0,
        max_deg: float = 90.0,
        hold_ms: float = 1500.0,
        return_to_center: bool = False,
        mode: str = "aim",
        kp_closed_loop: float = 0.6,
    ) -> None:
        if mode not in ("aim", "closed_loop"):
            raise ValueError("mode debe ser 'aim' o 'closed_loop'")
        if min_deg >= max_deg:
            raise ValueError("min_deg debe ser menor que max_deg")

        self.h_fov_deg = float(h_fov_deg)
        self.offset_deg = float(offset_deg)
        self.invert = bool(invert)
        # Ganancia: cuantos grados gira el motor por cada grado de rostro.
        # 1.0 = geometria pura; 1.5-2.5 exagera el movimiento (mira mas viva).
        self.angle_gain = max(0.1, float(angle_gain))
        self.alpha = max(0.01, min(1.0, float(ema_alpha)))
        self.deadband = max(0.0, float(deadband_deg))
        self.max_rate = max(0.1, float(max_rate_deg_s))
        self.min_deg = float(min_deg)
        self.max_deg = float(max_deg)
        self.hold_ms = float(hold_ms)
        self.return_to_center = bool(return_to_center)
        self.mode = mode
        self.kp = float(kp_closed_loop)

        self.target = 0.0
        self._ema: float | None = None
        self._face_angle: float | None = None
        self._has_face = False
        self._returning = False
        self._last_t: float | None = None
        self._last_face_t = -1e9

    # ------------------------------------------------------------------ utils
    def focal_px(self, width: int) -> float:
        return (width / 2.0) / math.tan(math.radians(self.h_fov_deg) / 2.0)

    def face_angle_deg(self, x_px: float, width: int) -> float:
        """Angulo del rostro respecto al eje optico (grados, + = derecha)."""
        fx = self.focal_px(width)
        angle = math.degrees(math.atan2(x_px - width / 2.0, fx))
        return -angle if self.invert else angle

    def _clamp(self, value: float) -> float:
        return max(self.min_deg, min(self.max_deg, value))

    # ----------------------------------------------------------------- update
    def update(self, face_x_px: float | None, width: int, now: float) -> AimState:
        dt = 0.0 if self._last_t is None else max(0.0, now - self._last_t)
        self._last_t = now

        if face_x_px is None:
            self._has_face = False
            self._face_angle = None
            hold_expired = (now - self._last_face_t) * 1000.0 >= self.hold_ms
            if self.return_to_center and hold_expired:
                self._returning = True
                desired = 0.0
            else:
                # Congelar: no perseguir un rostro que ya no esta
                self._returning = False
                return AimState(
                    self.target,
                    self._ema if self._ema is not None else self.target,
                    None,
                    False,
                    gain=self.angle_gain,
                )
        else:
            self._has_face = True
            self._last_face_t = now
            self._returning = False

            angle = self.face_angle_deg(face_x_px, width)
            self._face_angle = angle
            aimed = angle * self.angle_gain
            if self.mode == "closed_loop":
                desired = self.target + self.kp * aimed
            else:
                desired = self.offset_deg + aimed

            # Suavizado exponencial (EMA) del objetivo
            if self._ema is None:
                self._ema = desired
            else:
                self._ema += self.alpha * (desired - self._ema)
            desired = self._ema

            # Banda muerta: evita el zumbido del motor por ruido de 1-2 px
            if abs(desired - self.target) < self.deadband:
                desired = self.target

        # Limite de velocidad angular: el 28BYJ-48 no da mas de ~60-90 deg/s
        if dt > 0.0:
            max_step = self.max_rate * dt
            delta = max(-max_step, min(max_step, desired - self.target))
            self.target += delta
        else:
            self.target = desired

        self.target = self._clamp(self.target)
        return AimState(
            target_deg=self.target,
            ema_deg=self._ema if self._ema is not None else self.target,
            face_angle_deg=self._face_angle,
            has_face=self._has_face,
            returning=self._returning,
            gain=self.angle_gain,
        )

    # ------------------------------------------------------------------- set
    def set_offset(self, offset_deg: float) -> None:
        self.offset_deg = float(offset_deg)

    def set_gain(self, angle_gain: float) -> None:
        self.angle_gain = max(0.1, float(angle_gain))

    def set_limits(self, min_deg: float, max_deg: float) -> None:
        self.min_deg = float(min_deg)
        self.max_deg = float(max_deg)
        self.target = self._clamp(self.target)

    def zero_here(self) -> None:
        """El Arduino marca su posicion actual como 0 y aqui se reinicia el lazo."""
        self.target = 0.0
        self._ema = None
        self._last_t = None
