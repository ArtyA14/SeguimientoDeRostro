# Seguimiento de rostro con MediaPipe + servo motor

Detecta el rostro con la webcam usando **MediaPipe FaceLandmarker**, calcula su
ángulo respecto al eje de la cámara y mueve un **servo SG90** mediante un
**Arduino Uno/Nano** para apuntar hacia él.

```
Webcam ──► MediaPipe (478 landmarks) ──► ángulo del rostro
                                              │
                                    offset de calibración
                                              ▼
                        PC ──serie 115200──► Arduino ──PWM──► SG90 (D9)
                        ▲                        │
                        └── estado (pos/objetivo)┘
```

---

## 1. Hardware

| Elemento | Detalle |
|---|---|
| Arduino | Uno o Nano (ATmega328P) |
| Servo | SG90 (9 g, 5 V, rango útil 0–180°) |
| Fuente | **5 V ≥ 1 A externa** para el servo |
| Cámara | Webcam USB (probado con HP Wide Vision HD) |

### Cableado

| SG90 | Arduino |
|---|---|
| Naranja (señal) | **D9** |
| Rojo (+) | **Fuente externa 5 V** |
| Marrón (GND) | GND Arduino **y** GND de la fuente (GND común) |

> ⚠️ **No alimentes el servo desde el pin 5V del Arduino.** El SG90 consume
> 100–250 mA y picos de ~700 mA al arrancar con carga; eso reinicia la placa
> (síntoma típico: el servo tiembla y el Arduino se resetea a cada movimiento).
> Usa fuente externa y une los GND.
>
> ℹ️ `Servo.h` deshabilita el PWM nativo de los pines 9 y 10 del UNO. El pin
> **sigue funcionando** como salida de servo; solo pierdes `analogWrite` ahí.

### Datos del servo (para ajustar expectativas)

- Se controla por **pulso PWM de 50 Hz** (500–2400 µs configurado aquí).
- El servo **ya tiene su propio lazo cerrado**: tú le dices el ángulo y él va.
- Velocidad típica del SG90: **~0.1 s / 60°** (≈600 °/s en vacío), mucho más
  rápido que el motor a pasos anterior.
- **No tiene realimentación de posición**: la posición que reporta el Arduino es
  la que él mismo interpola, no una lectura del eje.
- Juego de engranajes: ~0.5–1°. Por eso la banda muerta del software es de 2.5°.
- Zumba si se queda cargado contra un tope: el software lo evita con los límites
  suaves y el comando `X` (detach).

---

## 2. Instalación

Ya están instalados en este equipo, pero para replicarlo:

```powershell
python -m pip install -r requirements.txt
```

Descargar el modelo (3.7 MB):

```powershell
python download_model.py
```

> **Nota sobre tu red:** `storage.googleapis.com` no resuelve por DNS en este
> equipo (las descargas se quedan colgadas). `download_model.py` detecta el
> fallo, resuelve el host por **DNS-over-HTTPS** y descarga por IP manteniendo
> el SNI.

Firmware: abre `arduino/servo_tracker/servo_tracker.ino` en el IDE de Arduino.
La librería **Servo** ya está instalada (Gestor de librerías si no).

Al encender, el sketch hace un **auto-test visible**: 90° → 45° → 135° → 90°.
Si el servo no hace ese barrido, el firmware no está cargado o no le llega
señal/alimentación. Ese barrido **no bloquea** el puerto: la telemetría sigue
saliendo. Además avisa por serie con `R servo_tracker 1.3`, y `main.py`
comprueba ese banner: si detecta otro sketch, muestra un aviso en la ventana.

> El sketch del motor a pasos sigue en `arduino/pan_tracker/pan_tracker.ino`
> por si quieres volver a él; requiere la librería **AccelStepper**.

---

## 3. Uso

La forma más rápida en Windows: doble clic en **`iniciar.bat`** (situado en la
raíz del proyecto). Descarga el modelo si falta, arranca el programa y deja la
ventana abierta al terminar.

También acepta argumentos, igual que `main.py`:

```powershell
iniciar.bat --port COM3
iniciar.bat --dry-run
iniciar.bat --simulate
```

Uso directo desde consola:

```powershell
python main.py                  # Arduino autodetectado
python main.py --port COM3      # puerto explícito
python main.py --dry-run        # sin Arduino (solo consola)
python main.py --simulate       # servo virtual
python main.py --list-ports     # ver puertos disponibles
python main.py --no-display --max-frames 150   # prueba automática
python main.py --source foto.jpg --simulate    # probar con una imagen/video
```

Teclas en la ventana:

| Tecla | Acción |
|---|---|
| `q` / `Esc` | salir |
| **`Tab`** | abrir/cerrar la pestaña **AJUSTES** |
| `z` | fijar el cero en la posición actual |
| `h` | mantener posición (frena) |
| `x` | soltar el servo (detach) |
| `m` | espejo on/off (por defecto **on**) |

El HUD muestra: ángulo del rostro, consigna enviada, ganancia, posición del
servo, cámara activa (con el estado del espejo), estado del puerto serie y FPS.

> **Orientación de la imagen.** `camera.mirror` está en `true`: la ventana
> funciona como un espejo, así que si el usuario se mueve a **su** izquierda,
> en la imagen también se mueve a la izquierda. La consigna del servo se calcula
> sobre esa misma imagen (coordenada `face.cx` tal cual), de modo que servo y
> pantalla apuntan siempre al mismo lado. Si un día quieres la vista "de
> cámara" (moverse a la izquierda aparece a la derecha), pulsa `m` o pon
> `"mirror": false`.

### 3.1 Pestaña AJUSTES (COM y cámara)

Arriba a la derecha de la ventana hay dos pestañas: **VISTA** y **AJUSTES**.
Haz clic en **AJUSTES** (o pulsa `Tab`) para elegir el puerto y la cámara sin
cerrar el programa.

| Control | Acción |
|---|---|
| `W` / `S` o flechas ↑↓ | mover la selección |
| `A` / `D` o flechas ←→ | cambiar de columna (COM ↔ cámara) |
| `Enter` o botón **APLICAR** | conectar el puerto y/o la cámara elegidos |
| `R` | releer la lista de puertos (si acabas de enchufar la placa) |
| `Tab` / `Esc` | cerrar |

- La opción **auto (detectar)** busca sola la placa (VID de Arduino/CH340/FTDI).
- El elemento activo se marca con `*` en verde.
- Al aplicar, la elección se guarda en `config.json`: la próxima vez arranca
  con ese puerto y esa cámara.
- También funciona con el ratón: clic en una fila para seleccionarla y en
  **APLICAR** para conectar.

---

## 4. Calibración (en este orden)

### 4.1 Offset mecánico — `aiming.offset_deg`

La cámara está fija y el servo mueve el efector (láser, foco, pantalla...). Hay
que decirle al programa qué ángulo de servo corresponde al centro de la imagen.

```powershell
python tools/calibrate_zero.py --port COM3
```

Mueve con `a`/`d` (2°) o `A`/`D` (10°) hasta que el efector apunte al objetivo
que ves en el centro de la imagen. `Enter` guarda `offset_deg` en `config.json`.

### 4.2 Campo de visión — `aiming.h_fov_deg`

```powershell
python tools/calibrate_fov.py --save
```

Pon una cinta métrica perpendicular a la cámara a una distancia `D`. Congela la
imagen con `Espacio` y escribe `D` y el tramo `S` que ocupa el ancho completo de
la imagen. Calcula `FOV = 2·atan((S/2)/D)`.

Valores típicos de webcam: 60–75°. Por defecto se usa 68°.

### 4.3 Sentido de giro — `aiming.invert`

Con el espejo activado, si el servo gira al lado contrario al que ves en
pantalla, cambia `invert` a `true` en `config.json` (o usa
`python main.py --invert`). Es un ajuste de software: el firmware del Arduino
no se toca.

Prueba de cableado y recorrido:

```powershell
python tools/step_test.py --port COM3
```

---

## 5. Cómo funciona el control

Con la cámara fija **no hay bucle cerrado**: es apuntado geométrico.

```
fx            = (ancho/2) / tan(FOV/2)
ángulo_rostro = atan((x_nariz − ancho/2) / fx)
ángulo_motor  = offset + ganancia · ángulo_rostro
```

La **ganancia** (`aiming.angle_gain`, por defecto 1.6) exagera el movimiento:
con 1.0 el servo barre exactamente el campo de visión de la cámara; con 1.6
gira 1.6° por cada grado de rostro, así que con movimientos pequeños de cabeza
el servo recorre más. Súbela si quieres más recorrido (2.0–2.5 llega enseguida
a los límites de ±90°) o ponla a 1.0 para geometría pura.

Después se aplica, en este orden:

1. **EMA** (`ema_alpha` = 0.3) para quitar el temblor de 1–2 px.
2. **Banda muerta** (`deadband_deg` = 2.5°) para que el servo no zumbe.
3. **Límite de velocidad angular** en Python (`max_rate_deg_s` = 260°/s), que
   solo evita saltos bruscos ante pérdidas puntuales del rostro.
4. **Límites suaves** (`min_deg`/`max_deg`, por defecto ±90°).
5. **Suavizado final en el firmware**: el servo no recibe saltos secos, sino un
   perfil trapezoidal a `max_rate_deg_s` = 180°/s y `accel_deg_s2` = 450°/s².
   Ahí está el "movimiento tipo cámara" pero vivo. Ajustable en `config.json`
   (`servo`) o en caliente con el comando `S`.

Si se pierde el rostro: mantiene la última posición durante `hold_ms` (1.5 s) y
luego se queda quieto (o vuelve al centro si `return_to_center` es `true`).

Si algún día montas la cámara **sobre** el servo, pon `aiming.mode` a
`"closed_loop"`: entonces la consigna se integra (`target += kp·ángulo`).

---

## 6. Protocolo serie

ASCII, 115200 baudios, una línea por mensaje terminada en `\n`.

| PC → Arduino | Efecto |
|---|---|
| `P <grados>` | consigna absoluta (−90…+90) |
| `Z` | fijar cero aquí |
| `L <min> <max>` | límites suaves |
| `S <vel> <acel>` | velocidad máxima y aceleración (grados/s, grados/s²) |
| `H` | mantener posición |
| `X` | soltar el servo (detach) |
| `?` | pedir estado |

| Arduino → PC | Significado |
|---|---|
| `R servo_tracker 1.3` | arranque |
| `S <pos> <obj> <mov> <lim>` | estado cada 50 ms |
| `E <texto>` | error |

**Watchdog:** si el Arduino no recibe comandos en 1,2 s, frena suavemente. Así
no se queda empujando contra un tope si Python se cuelga, pero los
desplazamientos largos (a 180°/s) sí terminan.

---

## 7. Estructura

```
main.py                  bucle principal (cámara → visión → control → serie)
iniciar.bat              lanzador de Windows (doble clic)
config.json              todos los parámetros
download_model.py        descarga del modelo (con fallback DoH)
tracker/
  camera.py              captura con reconexión (DSHOW en Windows)
  face_detector.py       MediaPipe FaceLandmarker (modo VIDEO)
  aiming.py              píxeles → ángulo, EMA, banda muerta, límites
  serial_link.py         hilo lector, autodetección, reconexión
  simulator.py           servo virtual para --simulate
  hud.py                 overlay de la ventana
  panel.py               pestaña de ajustes (COM + cámara)
arduino/
  servo_tracker/         firmware del servo SG90 (activo)
  pan_tracker/           firmware del motor a pasos 28BYJ-48 (alternativo)
tools/
  step_test.py           prueba de cableado/recorrido
  diagnose.py            diagnostico completo PC -> Arduino -> servo
  calibrate_zero.py      offset mecánico
  calibrate_fov.py       campo de visión
models/                  face_landmarker.task (no versionado)
```

---

## 8. Problemas frecuentes

| Síntoma | Causa / solución |
|---|---|
| `No existe el modelo` | ejecuta `python download_model.py` |
| La descarga del modelo se cuelga | DNS bloqueado: usa el fallback del script |
| **El servo no se mueve nunca** | `python tools\diagnose.py` te dice el eslabón exacto. Si el servo tampoco hace el barrido al encender, el sketch no está cargado o no llega señal/GND |
| `Sketch incorrecto` en pantalla | hay otro firmware cargado (p. ej. `pan_tracker`): sube `arduino/servo_tracker/servo_tracker.ino` |
| `no se pudo abrir la camara` | otra app la usa; prueba `--camera 1` |
| El servo no se mueve | ejecuta `python tools\diagnose.py`; revisa la señal en D9 y la fuente de 5 V |
| El Arduino se reinicia al mover el servo | alimentación insuficiente: fuente externa 5 V ≥ 1 A y GND común |
| El servo tiembla/zumba en reposo | sube `deadband_deg` (3–4°); evita que quede cargado |
| Gira al lado contrario | `"invert": true` en `config.json` |
| Apunta desplazado | recalibra `offset_deg` (§4.1) |
| Va a tirones | baja `servo.max_rate_deg_s` o `accel_deg_s2` |
| Se mueve lentísimo | sube `servo.max_rate_deg_s` (180 → 240) |
| El servo gira poco con el rostro | sube `aiming.angle_gain` (1.6 → 2.0) o usa `python main.py --gain 2` |
| La ventana no deja cambiar de cámara | cierra el programa que la esté usando y pulsa `R` en AJUSTES |
| `Serial: sin conexion` | el Arduino se reinicia al abrir el puerto; espera 2 s |

---

## 9. Límites de este montaje

El SG90 es rápido y suficiente para un puntero o un foco. Para mover algo con
peso (una cámara grande, un reflector) necesitas un servo con más par
(**MG996R**, **MG946R**) y, si el par es alto, una fuente más generosa.

Si vuelves al motor a pasos, el firmware `pan_tracker.ino` sigue operativo y el
protocolo es el mismo: solo cambian `STEPS_PER_REV`, los pines y los valores de
`speed`/`accel` (que en ese sketch se interpretan en pasos/s, no en grados/s).
