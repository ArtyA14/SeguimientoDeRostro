"""Descarga el modelo FaceLandmarker de MediaPipe.

Uso:
    python download_model.py                # descarga si falta
    python download_model.py --force        # vuelve a descargar
    python download_model.py --out otra.task

El archivo oficial vive en storage.googleapis.com. En algunas redes ese
dominio no resuelve por DNS (la descarga se queda colgada). Este script
detecta ese caso, resuelve el nombre con DNS-over-HTTPS (dns.google) y
conecta directamente por IP manteniendo el SNI, que es lo que necesita TLS.

Verifica al final que el archivo sea un .task válido (es un zip con los
submodelos de MediaPipe) y que pese lo esperado.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import sys
import urllib.request
import zipfile

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
HOST = "storage.googleapis.com"
PATH = "/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
EXPECTED_SIZE = 3_758_596
DOH_URL = "https://dns.google/resolve?name=storage.googleapis.com&type=A"


def log(msg: str) -> None:
    print(f"[modelo] {msg}", flush=True)


def _doh_ips(timeout: float = 10.0) -> list[str]:
    """Resuelve el host con DNS-over-HTTPS (evita el DNS roto del sistema)."""
    req = urllib.request.Request(DOH_URL, headers={"Accept": "application/dns-json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    ips = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
    return ips


def _download_via_ip(dest: str, ip: str, timeout: float = 15.0) -> int:
    """GET por IP fija con SNI = HOST. Devuelve bytes escritos."""
    raw = socket.create_connection((ip, 443), timeout=timeout)
    ctx = ssl.create_default_context()
    with ctx.wrap_socket(raw, server_hostname=HOST) as s:
        s.sendall(
            (
                f"GET {PATH} HTTP/1.1\r\n"
                f"Host: {HOST}\r\n"
                "User-Agent: seguimiento-rostro/1.0\r\n"
                "Accept: */*\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
        )
        f = s.makefile("rb")
        status = f.readline().decode("latin-1").strip()
        if "200" not in status:
            raise RuntimeError(f"respuesta inesperada: {status}")

        headers = {}
        while True:
            line = f.readline().decode("latin-1").strip()
            if not line:
                break
            k, _, v = line.partition(":")
            headers[k.lower()] = v.strip()
        total_expected = int(headers.get("content-length", "0"))

        tmp = dest + ".part"
        written = 0
        with open(tmp, "wb") as out:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
        os.replace(tmp, dest)
        if total_expected and written != total_expected:
            raise RuntimeError(f"descarga incompleta: {written} de {total_expected} bytes")
        return written


def _download_via_url(dest: str, timeout: float = 30.0) -> int:
    """Camino normal: urllib sigue redirecciones y usa el DNS del sistema."""
    tmp = dest + ".part"
    written = 0
    with urllib.request.urlopen(MODEL_URL, timeout=timeout) as r, open(tmp, "wb") as out:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            out.write(chunk)
            written += len(chunk)
    os.replace(tmp, dest)
    return written


def verify(path: str) -> None:
    size = os.path.getsize(path)
    if size != EXPECTED_SIZE:
        log(f"AVISO: tamano {size} distinto del esperado {EXPECTED_SIZE}")
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    required = {"face_detector.tflite", "face_landmarks_detector.tflite"}
    if not required.issubset(names):
        raise RuntimeError(f"el archivo no parece un FaceLandmarker valido: {names}")
    log(f"OK: {path} ({size:,} bytes)")
    log(f"     contiene: {', '.join(names)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Descarga face_landmarker.task")
    ap.add_argument("--out", default=os.path.join("models", "face_landmarker.task"))
    ap.add_argument("--force", action="store_true", help="descargar aunque ya exista")
    args = ap.parse_args()

    dest = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    if os.path.exists(dest) and not args.force:
        log(f"ya existe {dest} (usa --force para reemplazarlo)")
        try:
            verify(dest)
            return 0
        except Exception as exc:  # archivo corrupto: volver a descargar
            log(f"archivo invalido ({exc}); se descarga de nuevo")

    log("descargando " + MODEL_URL)
    try:
        written = _download_via_url(dest)
        log(f"descarga directa completada ({written:,} bytes)")
    except Exception as exc:
        log(f"la descarga directa fallo ({type(exc).__name__}: {exc})")
        log("probando via DNS-over-HTTPS + IP directa...")
        ips = _doh_ips()
        if not ips:
            log("no se pudo resolver el host. Revisa la conexion a internet.")
            return 1
        last_error: Exception | None = None
        for ip in ips[:6]:
            try:
                log(f"  intentando {ip} ...")
                written = _download_via_ip(dest, ip)
                log(f"descarga por IP completada ({written:,} bytes)")
                break
            except Exception as exc2:
                last_error = exc2
                log(f"  fallo {ip}: {type(exc2).__name__}: {exc2}")
        else:
            log(f"no se pudo descargar. Ultimo error: {last_error}")
            return 1

    try:
        verify(dest)
    except Exception as exc:
        log(f"ERROR de verificacion: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
