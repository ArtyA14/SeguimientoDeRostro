"""Seguimiento de rostro con MediaPipe y motor a pasos (pan).

Ejemplos:
    python main.py                      # camara + Arduino autodetectado
    python main.py --port COM3          # puerto explicito
    python main.py --dry-run            # sin Arduino: solo imprime consignas
    python main.py --simulate           # Arduino virtual (prueba el protocolo)
    python main.py --list-ports         # ver puertos COM
    python main.py --no-display --max-frames 120   # prueba automatica
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2

from tracker import hud
from tracker.aiming import Aimer
from tracker.camera import Camera, FileSource
from tracker.face_detector import FaceDetector
from tracker.panel import SettingsPanel
from tracker.serial_link import SerialLink, autodetect_port, list_serial_ports
from tracker.simulator import SimulatedLink

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"


# --------------------------------------------------------------------- config
def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"No existe el archivo de configuracion: {path}")
    with path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    defaults = {
        "model_path": "models/face_landmarker.task",
        "camera": {"index": 0, "width": 640, "height": 480, "fps": 30, "mirror": True},
        "aiming": {},
        "serial": {"port": "auto", "baud": 115200, "send_hz": 20, "state_timeout_ms": 1000},
        "ui": {"show_landmarks": False, "window": "Seguimiento de rostro"},
    }
    merged = {**defaults, **cfg}
    for key in ("camera", "aiming", "serial", "ui"):
        merged[key] = {**defaults.get(key, {}), **cfg.get(key, {})}
    return merged


def resolve_model_path(cfg: dict) -> Path:
    p = Path(cfg["model_path"])
    return p if p.is_absolute() else (ROOT / p)


# ----------------------------------------------------------------------- args
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Seguimiento de rostro con MediaPipe + motor a pasos")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help="ruta de config.json")
    ap.add_argument("--camera", type=int, help="indice de camara (0, 1, ...)")
    ap.add_argument("--source", help="archivo de imagen o video en vez de la camara (pruebas)")
    ap.add_argument("--port", help="puerto serie (COM3) o 'auto'")
    ap.add_argument("--dry-run", action="store_true", help="no abre el puerto serie")
    ap.add_argument("--simulate", action="store_true", help="usa un Arduino simulado")
    ap.add_argument("--no-display", action="store_true", help="sin ventana (solo consola)")
    ap.add_argument("--max-frames", type=int, default=0, help="salir tras N frames")
    ap.add_argument("--show-landmarks", action="store_true", help="dibujar los 478 puntos")
    ap.add_argument("--offset", type=float, help="offset de calibracion en grados")
    ap.add_argument("--invert", action="store_true", help="invertir el sentido de giro")
    ap.add_argument("--fov", type=float, help="campo de vision horizontal en grados")
    ap.add_argument("--gain", type=float, help="ganancia de angulo (>1 = el servo gira mas)")
    ap.add_argument("--list-ports", action="store_true", help="listar puertos y salir")
    return ap.parse_args(argv)


def save_settings(path: Path, *, camera_index: int | None = None, port: str | None = None) -> None:
    """Guarda en config.json la camara y/o el puerto elegidos en la pestana."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        raw = {}
    if camera_index is not None:
        raw.setdefault("camera", {})["index"] = int(camera_index)
    if port is not None:
        raw.setdefault("serial", {})["port"] = port
    try:
        path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"[AVISO] no se pudo guardar {path.name}: {exc}")


def print_ports() -> int:
    ports = list_serial_ports()
    if not ports:
        print("No hay puertos COM detectados. Conecta el Arduino por USB.")
        return 1
    print("Puertos serie detectados:")
    for p in ports:
        vid = f"{p['vid']:04X}" if p["vid"] is not None else "----"
        pid = f"{p['pid']:04X}" if p["pid"] is not None else "----"
        print(f"  {p['device']:<8} {p['description']:<40} VID:PID {vid}:{pid}")
    print(f"\nAutodetectado: {autodetect_port()}")
    return 0


# ----------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list_ports:
        return print_ports()

    cfg = load_config(Path(args.config))
    if args.camera is not None:
        cfg["camera"]["index"] = args.camera
    if args.port:
        cfg["serial"]["port"] = args.port
    if args.offset is not None:
        cfg["aiming"]["offset_deg"] = args.offset
    if args.invert:
        cfg["aiming"]["invert"] = True
    if args.fov is not None:
        cfg["aiming"]["h_fov_deg"] = args.fov
    if args.gain is not None:
        cfg["aiming"]["angle_gain"] = args.gain

    model_path = resolve_model_path(cfg)
    if not model_path.exists():
        print(f"ERROR: falta el modelo en {model_path}")
        print("Ejecuta:  python download_model.py")
        return 2

    cam_cfg = cfg["camera"]
    cam_index = int(cam_cfg["index"])

    def make_camera(index: int) -> Camera:
        return Camera(
            index=index,
            width=int(cam_cfg["width"]),
            height=int(cam_cfg["height"]),
            fps=int(cam_cfg["fps"]),
            mirror=bool(cam_cfg.get("mirror", False)),
        )

    if args.source:
        try:
            camera = FileSource(args.source, mirror=bool(cam_cfg.get("mirror", False)))
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}")
            return 3
        print(f"Fuente de archivo: {args.source}")
    else:
        camera = make_camera(cam_index)
    if not camera.open():
        print(f"ERROR: no se pudo abrir la camara {cam_index}.")
        print("Prueba con --camera 1, o cierra otras apps que la esten usando.")
        return 3

    aim_cfg = cfg["aiming"]
    aimer = Aimer(
        h_fov_deg=aim_cfg.get("h_fov_deg", 68.0),
        offset_deg=aim_cfg.get("offset_deg", 0.0),
        invert=aim_cfg.get("invert", False),
        angle_gain=aim_cfg.get("angle_gain", 1.0),
        ema_alpha=aim_cfg.get("ema_alpha", 0.25),
        deadband_deg=aim_cfg.get("deadband_deg", 1.5),
        max_rate_deg_s=aim_cfg.get("max_rate_deg_s", 45.0),
        min_deg=aim_cfg.get("min_deg", -90.0),
        max_deg=aim_cfg.get("max_deg", 90.0),
        hold_ms=aim_cfg.get("hold_ms", 1500),
        return_to_center=aim_cfg.get("return_to_center", False),
        mode=aim_cfg.get("mode", "aim"),
        kp_closed_loop=aim_cfg.get("kp_closed_loop", 0.6),
    )

    driver = cfg.get("driver", "servo")
    servo_cfg = cfg.get("servo", {})
    if driver == "stepper":
        # El firmware de pasos trabaja en pasos/s; el simulador, en grados/s
        steps_per_deg = 4096.0 / 360.0
        motion_rate = 600.0 / steps_per_deg      # ~52.7 deg/s
        motion_accel = 500.0 / steps_per_deg     # ~43.9 deg/s^2
        wire_rate, wire_accel = 600.0, 500.0
    else:
        motion_rate = float(servo_cfg.get("max_rate_deg_s", 120.0))
        motion_accel = float(servo_cfg.get("accel_deg_s2", 240.0))
        wire_rate, wire_accel = motion_rate, motion_accel

    warning: str | None = None
    link = None
    link_started = 0.0
    expected = "servo_tracker" if driver == "servo" else "pan_tracker"

    def firmware_warning() -> str | None:
        """Aviso de firmware recalculado en cada frame.

        Antes se decidia una sola vez al arrancar y se quedaba fijo en pantalla
        aunque el Arduino respondiera medio segundo despues (el bootloader del
        Uno tarda ~2 s y el auto-test del servo otros 2 s). Ahora el aviso
        desaparece solo en cuanto llega el banner.
        """
        if link is None:
            return None
        banner = getattr(link, "banner", None)
        if banner:
            if expected not in banner:
                return f"Sketch incorrecto: '{banner}' - esperado '{expected}'"
            return None
        if link_started and (time.monotonic() - link_started) >= 6.0:
            return f"Arduino sin respuesta: carga {expected}.ino"
        return None

    if args.simulate:
        link = SimulatedLink(
            max_rate_deg_s=motion_rate,
            accel_deg_s2=motion_accel,
            min_deg=aim_cfg.get("min_deg", -90.0),
            max_deg=aim_cfg.get("max_deg", 90.0),
            on_log=print,
        )
    elif not args.dry_run:
        serial_cfg = cfg["serial"]
        link = SerialLink(
            port=serial_cfg.get("port", "auto"),
            baud=int(serial_cfg.get("baud", 115200)),
            send_hz=float(serial_cfg.get("send_hz", 20)),
            state_timeout_ms=float(serial_cfg.get("state_timeout_ms", 1000)),
            on_log=print,
        )
        if not link.connect():
            print("AVISO: sin Arduino. Se continua en modo --dry-run.")
            link = None
        else:
            # Esperar el banner de arranque (informativo: el aviso real se
            # decide en cada frame con firmware_warning()).
            link_started = time.monotonic()
            deadline = link_started + 3.0
            while time.monotonic() < deadline and link.banner is None:
                time.sleep(0.05)

    if link is not None:
        link.set_limits(aimer.min_deg, aimer.max_deg)
        link.set_motion(wire_rate, wire_accel)

    detector = FaceDetector(model_path)
    window = cfg["ui"].get("window", "Seguimiento de rostro")
    show_landmarks = args.show_landmarks or bool(cfg["ui"].get("show_landmarks", False))
    display = not args.no_display

    # Pestana de ajustes (COM + camara) dentro de la misma ventana
    panel = SettingsPanel(
        ports=list_serial_ports(),
        cameras=[0, 1, 2, 3],
        port=getattr(link, "port_name", None) if link is not None else None,
        cam=cam_index,
    )
    if display:
        cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(window, panel.on_mouse)

    mode_txt = "simulado" if args.simulate else ("dry-run" if link is None else "hardware")
    print(f"Modo: {mode_txt} | FOV {aimer.h_fov_deg:.1f} deg | offset {aimer.offset_deg:+.1f} deg")
    print(f"Ganancia de angulo x{aimer.angle_gain:.2f} | servo {motion_rate:.0f} deg/s, {motion_accel:.0f} deg/s^2")
    print("Teclas: q salir | TAB ajustes | z cero | h hold | x soltar | m espejo")

    t0 = time.monotonic()
    fps = 0.0
    fps_t = t0
    fps_frames = 0
    last_log = 0.0
    last_print = 0.0
    last_warn_txt: str | None = None
    frames = 0

    try:
        while True:
            now = time.monotonic()
            frame = camera.read()
            if frame is None:
                if now - t0 > 5.0:
                    print("ERROR: la camara no entrega imagen.")
                    return 4
                time.sleep(0.01)
                continue

            frames += 1
            h, w = frame.shape[:2]
            face = detector.detect(frame, int((now - t0) * 1000))

            face_x = None
            if face is not None:
                # La imagen ya viene volteada por Camera cuando mirror=True, asi
                # que face.cx YA esta en coordenadas de lo que se ve en pantalla.
                # No hay que invertirla otra vez: el servo debe apuntar al mismo
                # lado en el que el usuario ve moverse su rostro.
                face_x = face.cx

            aim = aimer.update(face_x, w, now)

            if link is not None:
                link.send_target(aim.target_deg)
                status = link.status()
            else:
                status = {"connected": False, "port": None, "pos_deg": None, "moving": False, "limit": False, "stale": True}
                if now - last_print >= 0.2:
                    last_print = now
                    ang = f"{aim.face_angle_deg:+6.1f}" if aim.face_angle_deg is not None else "  ---"
                    print(f"rostro={ang} deg  consigna={aim.target_deg:+6.1f} deg  (sin Arduino)")

            status["camera"] = cam_index
            status["mirror"] = bool(camera.mirror)

            fps_frames += 1
            if now - fps_t >= 0.5:
                fps = fps_frames / (now - fps_t)
                fps_frames = 0
                fps_t = now

            if now - last_log >= 1.0:
                last_log = now
                ang = f"{aim.face_angle_deg:+6.1f}" if aim.face_angle_deg is not None else "  ---"
                pos = f"{status['pos_deg']:+6.1f}" if status.get("pos_deg") is not None else "  ---"
                print(f"[{frames:5d}] fps={fps:4.1f} rostro={ang} consigna={aim.target_deg:+6.1f} real={pos}")

            # El aviso se recalcula aqui: aparece si el firmware no responde y
            # se borra solo en cuanto el Arduino manda el banner.
            warning = firmware_warning()
            if warning != last_warn_txt:
                last_warn_txt = warning
                if warning:
                    print(f"[AVISO] {warning}")
                    if warning.startswith("Sketch incorrecto"):
                        print("        Sube el sketch correcto a la placa y vuelve a intentarlo.")

            if display:
                view = hud.draw(
                    frame,
                    face,
                    aim,
                    status,
                    fps,
                    show_landmarks=show_landmarks,
                    mode=aimer.mode,
                    warning=warning,
                    show_status=not panel.visible,
                )
                panel.port_active = getattr(link, "port_name", None) if link is not None else None
                panel.cam_active = cam_index
                view = panel.draw(view)
                cv2.imshow(window, view)

            raw_key = 0
            key = 0
            action = None
            if display:
                raw_key = cv2.waitKeyEx(1) if hasattr(cv2, "waitKeyEx") else (cv2.waitKey(1) & 0xFF)
                key = raw_key & 0xFF
                action = panel.handle_key(raw_key, key)
                if panel.visible:
                    # Con la pestana abierta, las teclas son solo del panel
                    key = 0
                click = panel.take_click()
                if click is not None:
                    clicked = panel.click(*click)
                    if clicked is not None:
                        action = clicked

            if action and action[0] == "toggle" and panel.visible:
                # Al abrir la pestana, releer los puertos por si se conecto algo
                panel.refresh_ports(list_serial_ports())

            if action and action[0] == "apply":
                _, new_port, new_cam = action
                current_port = getattr(link, "port_name", None) if link is not None else None

                # --- puerto serie ---
                if new_port != current_port:
                    if link is not None:
                        link.close()
                        link = None
                    new_link = SerialLink(
                        port=new_port,
                        baud=int(cfg["serial"].get("baud", 115200)),
                        send_hz=float(cfg["serial"].get("send_hz", 20)),
                        state_timeout_ms=float(cfg["serial"].get("state_timeout_ms", 1000)),
                        on_log=print,
                    )
                    if new_link.connect():
                        new_link.set_limits(aimer.min_deg, aimer.max_deg)
                        new_link.set_motion(wire_rate, wire_accel)
                        link = new_link
                        link_started = time.monotonic()
                        panel.set_message(f"Conectado a {link.port_name}", True)
                        save_settings(Path(args.config), port=link.port_name)
                    else:
                        new_link.close()
                        panel.set_message(f"No se pudo abrir {new_port}", False)

                # --- camara ---
                if not args.source and new_cam != cam_index:
                    previous = camera
                    previous.close()
                    candidate = make_camera(new_cam)
                    if candidate.open():
                        camera = candidate
                        cam_index = new_cam
                        panel.set_message(f"Camara {new_cam} conectada", True)
                        save_settings(Path(args.config), camera_index=cam_index)
                    else:
                        candidate.close()
                        if previous.open():
                            camera = previous
                        panel.set_message(f"No se pudo abrir la camara {new_cam}", False)

                last_warn_txt = None  # que el aviso se reevalue con el nuevo enlace

            elif action is None and display and key in (27, ord("q")):
                break
            elif action is None and key == ord("z"):
                aimer.zero_here()
                if link is not None:
                    link.zero()
                print("cero fijado en la posicion actual")
            elif action is None and key == ord("h"):
                if link is not None:
                    link.hold()
                print("hold")
            elif action is None and key == ord("x"):
                if link is not None:
                    link.release()
                print("bobinas sueltas")
            elif action is None and key == ord("m"):
                camera.mirror = not camera.mirror
                print(f"espejo: {'on' if camera.mirror else 'off'}")

            if args.max_frames and frames >= args.max_frames:
                break

    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
    finally:
        if link is not None:
            link.close()
        detector.close()
        camera.close()
        if display:
            cv2.destroyAllWindows()

    print(f"Listo. Frames procesados: {frames}, fps medio: {frames / max(1e-6, time.monotonic() - t0):.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
