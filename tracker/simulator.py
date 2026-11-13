"""Servo SG90 simulado para probar el protocolo sin hardware.

Imita la interfaz de `SerialLink` y reproduce el perfil trapezoidal del
firmware: velocidad maxima y aceleracion en grados/s y grados/s^2.
"""

from __future__ import annotations

import threading
import time


class SimulatedLink:
    def __init__(
        self,
        max_rate_deg_s: float = 120.0,
        accel_deg_s2: float = 240.0,
        min_deg: float = -90.0,
        max_deg: float = 90.0,
        on_log=None,
    ) -> None:
        self.on_log = on_log or (lambda msg: None)
        self.max_rate_deg_s = float(max_rate_deg_s)
        self.accel_deg_s2 = float(accel_deg_s2)
        self.min_deg = float(min_deg)
        self.max_deg = float(max_deg)

        self.port_name = "SIMULADO"
        self.connected = True
        self.state = type("State", (), {})()
        self.state.pos_deg = 0.0
        self.state.target_deg = 0.0
        self.state.moving = False
        self.state.limit = False
        self.state.ts = time.monotonic()
        self.state.raw = ""

        self._pos = 0.0
        self._target = 0.0
        self._vel = 0.0
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="sim-servo", daemon=True)
        self._thread.start()
        self.on_log(
            f"[sim] servo simulado: {self.max_rate_deg_s:.0f} deg/s, "
            f"{self.accel_deg_s2:.0f} deg/s^2"
        )

    # ------------------------------------------------------------------ bucle
    def _loop(self) -> None:
        last = time.monotonic()
        while self._running:
            time.sleep(0.005)
            now = time.monotonic()
            dt = now - last
            last = now

            err = self._target - self._pos
            if abs(err) < 0.05 and abs(self._vel) < 1.0:
                self._pos = self._target
                self._vel = 0.0
            else:
                # v = sqrt(2*a*d), limitada por la velocidad maxima
                desired = (2.0 * self.accel_deg_s2 * abs(err)) ** 0.5
                desired = min(desired, self.max_rate_deg_s)
                if err < 0:
                    desired = -desired
                dv = self.accel_deg_s2 * dt
                delta = max(-dv, min(dv, desired - self._vel))
                self._vel += delta
                self._pos += self._vel * dt

            if self._pos <= self.min_deg:
                self._pos = self.min_deg
                if self._vel < 0:
                    self._vel = 0.0
            elif self._pos >= self.max_deg:
                self._pos = self.max_deg
                if self._vel > 0:
                    self._vel = 0.0

            self.state.pos_deg = round(self._pos, 2)
            self.state.target_deg = round(self._target, 2)
            self.state.moving = abs(self._target - self._pos) > 0.3
            self.state.limit = (
                self._pos <= self.min_deg + 0.01 or self._pos >= self.max_deg - 0.01
            )
            self.state.ts = now

    # ---------------------------------------------------------------- interfaz
    def connect(self) -> bool:
        return True

    def send_target(self, angle_deg: float, force: bool = False) -> bool:
        self._target = max(self.min_deg, min(self.max_deg, float(angle_deg)))
        return True

    def zero(self) -> bool:
        self._pos = 0.0
        self._target = 0.0
        self._vel = 0.0
        return True

    def set_limits(self, min_deg: float, max_deg: float) -> bool:
        self.min_deg = float(min_deg)
        self.max_deg = float(max_deg)
        return True

    def set_motion(self, max_rate_deg_s: float, accel_deg_s2: float) -> bool:
        self.max_rate_deg_s = float(max_rate_deg_s)
        self.accel_deg_s2 = float(accel_deg_s2)
        return True

    def hold(self) -> bool:
        self._target = self._pos
        self._vel = 0.0
        return True

    def release(self) -> bool:
        return self.hold()

    def request_status(self) -> bool:
        return True

    def status(self) -> dict:
        age = time.monotonic() - self.state.ts
        return {
            "connected": True,
            "port": self.port_name,
            "pos_deg": self.state.pos_deg,
            "target_deg": self.state.target_deg,
            "moving": self.state.moving,
            "limit": self.state.limit,
            "age_s": age,
            "stale": False,
        }

    def close(self) -> None:
        self._running = False
        self._thread.join(timeout=1.0)
        self.connected = False
