"""Enlace serie con el Arduino (protocolo ASCII de una linea por mensaje).

Comandos PC -> Arduino
    P <grados>          consigna absoluta
    Z                   marcar la posicion actual como 0
    L <min> <max>       limites suaves en grados
    S <vel> <acel>      velocidad maxima (grados/s) y aceleracion (grados/s^2)
    H                   parar (desacelerando)
    X                   soltar bobinas
    ?                   pedir estado

Respuestas Arduino -> PC
    R <version>                    al arrancar
    S <pos> <obj> <mov> <limite>   estado cada 50 ms
    E <mensaje>                    error

El Arduino tiene watchdog: si deja de recibir comandos durante 1,2 s se
detiene solo. Eso evita que el motor se vaya al tope si Python se cuelga, sin
cortar los desplazamientos largos (que a 180 deg/s tardan ~0,7 s).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import serial
from serial.tools import list_ports

# VID conocidos de conversores USB-serie
_KNOWN_VIDS = {
    0x1A86: "CH340",
    0x0403: "FTDI",
    0x2341: "Arduino",
    0x2A03: "Arduino",
    0x10C4: "CP210x",
}
_PREFERRED_WORDS = ("arduino", "ch340", "ch341", "ftdi", "cp210", "usb-serial", "usb serial")


@dataclass
class MotorState:
    pos_deg: float | None = None
    target_deg: float | None = None
    moving: bool = False
    limit: bool = False
    ts: float = 0.0
    raw: str = field(default="", repr=False)


def list_serial_ports() -> list[dict]:
    out = []
    for p in list_ports.comports():
        out.append(
            {
                "device": p.device,
                "description": p.description or "",
                "vid": p.vid,
                "pid": p.pid,
            }
        )
    return out


def autodetect_port() -> str | None:
    """Elige el puerto mas probable: VID conocido > descripcion > primero."""
    ports = list_serial_ports()
    if not ports:
        return None

    def score(p: dict) -> int:
        s = 0
        if p["vid"] in _KNOWN_VIDS:
            s += 3
        desc = p["description"].lower()
        if any(word in desc for word in _PREFERRED_WORDS):
            s += 2
        return s

    ports.sort(key=score, reverse=True)
    return ports[0]["device"]


class SerialLink:
    def __init__(
        self,
        port: str = "auto",
        baud: int = 115200,
        send_hz: float = 20.0,
        state_timeout_ms: float = 1000.0,
        on_log=None,
    ) -> None:
        self.requested_port = port
        self.baud = int(baud)
        self.send_hz = max(1.0, float(send_hz))
        self.state_timeout_s = float(state_timeout_ms) / 1000.0
        self.on_log = on_log or (lambda msg: None)

        self.state = MotorState()
        self.port_name: str | None = None
        self.banner: str | None = None
        self.connected = False

        self._ser: serial.Serial | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_send = 0.0
        self._ready_at = 0.0
        self._reconnect_at = 0.0
        self._pending: list[str] = []

    # --------------------------------------------------------------- conexion
    def connect(self) -> bool:
        port = self.requested_port
        if port.lower() == "auto":
            port = autodetect_port()
            if port is None:
                self.on_log("[serial] no hay puertos COM disponibles")
                return False
            self.on_log(f"[serial] puerto autodetectado: {port}")

        try:
            ser = serial.Serial(port, self.baud, timeout=0.2, write_timeout=0.5)
        except (serial.SerialException, OSError) as exc:
            self.on_log(f"[serial] no se pudo abrir {port}: {exc}")
            return False

        self._ser = ser
        self.port_name = port
        self.connected = True
        # Abrir el puerto resetea el Uno (DTR): esperar al bootloader
        self._ready_at = time.monotonic() + 2.0
        self._last_send = 0.0
        self.on_log(f"[serial] conectado a {port} @ {self.baud}")

        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._reader_loop, name="serial-reader", daemon=True)
            self._thread.start()
        return True

    def _mark_disconnected(self, reason: str = "") -> None:
        if self.connected:
            self.on_log(f"[serial] desconectado {reason}".strip())
        self.connected = False
        with self._lock:
            if self._ser is not None:
                try:
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None
        self._reconnect_at = time.monotonic() + 2.0

    def _try_reconnect(self) -> bool:
        if time.monotonic() < self._reconnect_at:
            return False
        if self.requested_port.lower() != "auto" and self.port_name:
            port = self.port_name
        else:
            port = autodetect_port()
        if not port:
            self._reconnect_at = time.monotonic() + 2.0
            return False
        try:
            ser = serial.Serial(port, self.baud, timeout=0.2, write_timeout=0.5)
        except (serial.SerialException, OSError):
            self._reconnect_at = time.monotonic() + 2.0
            return False
        with self._lock:
            self._ser = ser
        self.port_name = port
        self.connected = True
        self._ready_at = time.monotonic() + 2.0
        self.on_log(f"[serial] reconectado a {port}")
        return True

    # ------------------------------------------------------------- hilo lector
    def _reader_loop(self) -> None:
        while self._running:
            if self._ser is None:
                if not self._try_reconnect():
                    time.sleep(0.2)
                    continue
            ser = self._ser
            if ser is None:
                continue
            try:
                line = ser.readline()
            except (serial.SerialException, OSError) as exc:
                self._mark_disconnected(str(exc))
                continue
            if line:
                self._handle_line(line.decode("ascii", errors="ignore").strip())
            self._flush_pending()

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        if line.startswith("S "):
            parts = line[2:].split()
            if len(parts) >= 4:
                try:
                    self.state.pos_deg = float(parts[0])
                    self.state.target_deg = float(parts[1])
                    self.state.moving = parts[2] not in ("0", "0.0")
                    self.state.limit = parts[3] not in ("0", "0.0")
                    self.state.ts = time.monotonic()
                    self.state.raw = line
                except ValueError:
                    pass
        elif line.startswith("R"):
            self.banner = line[1:].strip()
            self.on_log(f"[serial] Arduino listo: {line}")
            self._ready_at = time.monotonic()
        elif line.startswith("E"):
            self.on_log(f"[serial] error del Arduino: {line}")

    # ------------------------------------------------------------------ envio
    def _write(self, data: str, queue_if_not_ready: bool = False) -> bool:
        ser = self._ser
        if ser is None or not self.connected:
            return False
        if time.monotonic() < self._ready_at:
            # El Uno se resetea al abrir el puerto: guardar para luego
            if queue_if_not_ready:
                self._pending.append(data)
            return False
        with self._lock:
            try:
                ser.write(data.encode("ascii"))
                ser.flush()
                return True
            except (serial.SerialException, OSError) as exc:
                self._mark_disconnected(str(exc))
                return False

    def _flush_pending(self) -> None:
        if not self._pending or time.monotonic() < self._ready_at:
            return
        ser = self._ser
        if ser is None or not self.connected:
            return
        pending = self._pending
        self._pending = []
        with self._lock:
            try:
                for data in pending:
                    ser.write(data.encode("ascii"))
                ser.flush()
            except (serial.SerialException, OSError) as exc:
                self._mark_disconnected(str(exc))

    def send_target(self, angle_deg: float, force: bool = False) -> bool:
        now = time.monotonic()
        if now < self._ready_at:
            return False
        if not force and (now - self._last_send) < (1.0 / self.send_hz):
            return False
        self._last_send = now
        return self._write(f"P {angle_deg:.2f}\n")

    def zero(self) -> bool:
        return self._write("Z\n", queue_if_not_ready=True)

    def set_limits(self, min_deg: float, max_deg: float) -> bool:
        return self._write(f"L {min_deg:.2f} {max_deg:.2f}\n", queue_if_not_ready=True)

    def set_motion(self, max_rate_deg_s: float, accel_deg_s2: float) -> bool:
        return self._write(
            f"S {max_rate_deg_s:.0f} {accel_deg_s2:.0f}\n", queue_if_not_ready=True
        )

    def hold(self) -> bool:
        return self._write("H\n", queue_if_not_ready=True)

    def release(self) -> bool:
        return self._write("X\n", queue_if_not_ready=True)

    def request_status(self) -> bool:
        return self._write("?\n")

    # ----------------------------------------------------------------- estado
    def status(self) -> dict:
        age = time.monotonic() - self.state.ts if self.state.ts else None
        stale = age is None or age > self.state_timeout_s
        return {
            "connected": self.connected,
            "port": self.port_name,
            "banner": self.banner,
            "pos_deg": self.state.pos_deg,
            "target_deg": self.state.target_deg,
            "moving": self.state.moving,
            "limit": self.state.limit,
            "age_s": age,
            "stale": stale,
        }

    # ----------------------------------------------------------------- cierre
    def close(self) -> None:
        if self.connected:
            try:
                self.hold()
            except Exception:
                pass
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._mark_disconnected()

    def __enter__(self) -> "SerialLink":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
