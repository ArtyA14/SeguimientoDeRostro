/*
 * servo_tracker.ino - Seguimiento de rostro: eje pan con servo SG90
 *
 * El PC (Python + MediaPipe) hace la vision y manda la consigna en grados
 * dentro del rango logico [-90, +90]. Este sketch la convierte al rango
 * fisico del servo (0..180) y la aplica con un perfil suave (rampa con
 * aceleracion) para que la mira no de tirones.
 *
 * Protocolo serie (115200, una linea por comando, terminada en \n):
 *   P <grados>        consigna absoluta (-90..+90)
 *   Z                 poner el cero en la posicion actual
 *   L <min> <max>     limites suaves (grados logicos)
 *   S <vel> <acel>    velocidad maxima (grados/s) y aceleracion (grados/s^2)
 *   H                 mantener posicion (frena)
 *   X                 soltar el servo (detach)
 *   ?                 pedir estado
 *
 * Respuestas:
 *   R servo_tracker 1.3
 *   S <pos> <obj> <moviendo> <limite>      cada 50 ms
 *
 * Cableado (SG90):
 *   Naranja (senal) -> D9
 *   Rojo   (+)      -> fuente externa 5 V (NO del Arduino)
 *   Marron (GND)    -> GND Arduino y GND de la fuente (GND comun)
 *
 * Requiere la libreria "Servo" (Gestor de librerias del IDE).
 */

#include <Servo.h>

// ------------------------------------------------------------------- pines
const uint8_t PIN_SERVO = 9;

// Anchura de pulso del SG90. 500..2400 us aprovecha todo el recorrido; si el
// servo zumba o se calienta en los extremos, sube a 600..2300.
const int PULSE_MIN_US = 500;
const int PULSE_MAX_US = 2400;

// Angulo fisico del servo que corresponde al 0 logico
const float SERVO_CENTER = 90.0;

// --------------------------------------------------------------- ajustes
float maxRateDeg = 180.0;   // grados/s (movimiento vivo pero suave)
float accelDeg = 450.0;     // grados/s^2

float minDeg = -90.0;
float maxDeg = 90.0;
float targetDeg = 0.0;
float posDeg = 0.0;
float velDeg = 0.0;

const unsigned long WATCHDOG_MS = 1200;  // sin comandos -> frenar
const unsigned long STATUS_MS = 50;      // reporte de estado
const unsigned long STEP_MS = 5;         // periodo del perfil

unsigned long lastCmdMs = 0;
unsigned long lastStatusMs = 0;
unsigned long lastStepMs = 0;
bool stale = false;
bool attached = false;

// Auto-test de arranque (no bloqueante: la telemetria sigue saliendo)
bool booting = true;
uint8_t bootStep = 0;
unsigned long bootMs = 0;
const unsigned long BOOT_STEP_MS = 450;

Servo servo;

char buf[32];
uint8_t bufLen = 0;

// -------------------------------------------------------------- utilidades
void servoApply() {
  float angle = SERVO_CENTER + posDeg;
  if (angle < 0.0) angle = 0.0;
  if (angle > 180.0) angle = 180.0;
  if (attached) servo.write((int)(angle + 0.5));
}

void attachServo() {
  if (!attached) {
    servo.attach(PIN_SERVO, PULSE_MIN_US, PULSE_MAX_US);
    attached = true;
  }
}

void setTargetDeg(float deg) {
  if (deg < minDeg) deg = minDeg;
  if (deg > maxDeg) deg = maxDeg;
  targetDeg = deg;
  attachServo();
}

// Perfil trapezoidal: acelera, corre a maxRateDeg y frena al acercarse.
void stepProfile(float dt) {
  if (stale) {
    // Frenado suave sin cambiar de objetivo
    float dv = accelDeg * dt;
    if (velDeg > 0) {
      velDeg = (velDeg <= dv) ? 0.0 : velDeg - dv;
    } else if (velDeg < 0) {
      velDeg = (-velDeg <= dv) ? 0.0 : velDeg + dv;
    }
    posDeg += velDeg * dt;
  } else {
    float err = targetDeg - posDeg;
    if (fabs(err) < 0.05 && fabs(velDeg) < 1.0) {
      posDeg = targetDeg;
      velDeg = 0.0;
    } else {
      float desired = sqrtf(2.0 * accelDeg * fabs(err));
      if (desired > maxRateDeg) desired = maxRateDeg;
      if (err < 0) desired = -desired;

      float dv = accelDeg * dt;
      float delta = desired - velDeg;
      if (delta > dv) delta = dv;
      if (delta < -dv) delta = -dv;
      velDeg += delta;
      posDeg += velDeg * dt;
    }
  }

  // Limites mecanicos del rango logico
  if (posDeg <= minDeg) {
    posDeg = minDeg;
    if (velDeg < 0) velDeg = 0;
  } else if (posDeg >= maxDeg) {
    posDeg = maxDeg;
    if (velDeg > 0) velDeg = 0;
  }

  servoApply();
}

// Barrido de arranque 90 -> 45 -> 135 -> 90 sin usar delay(): asi el puerto
// serie sigue respondiendo y el PC no cree que la placa esta muda.
void bootSweep(unsigned long now) {
  static const int8_t seq[4] = {90, 45, 135, 90};

  if (now - bootMs < BOOT_STEP_MS) return;
  bootMs = now;
  bootStep++;

  if (bootStep < 4) {
    servo.write(seq[bootStep]);
    posDeg = (float)seq[bootStep] - SERVO_CENTER;
    targetDeg = posDeg;
  } else {
    booting = false;
    posDeg = 0.0;
    targetDeg = 0.0;
    velDeg = 0.0;
    servoApply();
    lastCmdMs = now;
    lastStepMs = now;
  }
}

void reportStatus() {
  Serial.print(F("S "));
  Serial.print(posDeg, 2);
  Serial.print(' ');
  Serial.print(targetDeg, 2);
  Serial.print(' ');
  Serial.print(fabs(targetDeg - posDeg) > 0.3 ? 1 : 0);
  Serial.print(' ');
  Serial.println((posDeg <= minDeg + 0.01 || posDeg >= maxDeg - 0.01) ? 1 : 0);
}

void handleLine(char *line) {
  while (*line == ' ') line++;
  if (*line == 0) return;

  char cmd = toupper((unsigned char)line[0]);
  char *arg = line + 1;
  while (*arg == ' ' || *arg == ',') arg++;

  switch (cmd) {
    case 'P':
      if (*arg) setTargetDeg(atof(arg));
      break;

    case 'Z':
      posDeg = 0.0;
      targetDeg = 0.0;
      velDeg = 0.0;
      attachServo();
      servoApply();
      break;

    case 'L': {
      float a = atof(arg);
      char *sep = strpbrk(arg, " ,");
      if (sep) {
        float b = atof(sep + 1);
        if (b > a) {
          minDeg = a;
          maxDeg = b;
          setTargetDeg(targetDeg);
        }
      }
      break;
    }

    case 'S': {
      float rate = atof(arg);
      char *sep = strpbrk(arg, " ,");
      if (rate > 0) maxRateDeg = rate;
      if (sep) {
        float ac = atof(sep + 1);
        if (ac > 0) accelDeg = ac;
      }
      break;
    }

    case 'H':
      targetDeg = posDeg;
      velDeg = 0.0;
      stale = false;
      break;

    case 'X':
      servo.detach();
      attached = false;
      targetDeg = posDeg;
      velDeg = 0.0;
      break;

    case '?':
      reportStatus();
      break;

    default:
      Serial.print(F("E comando desconocido: "));
      Serial.println(cmd);
      break;
  }

  lastCmdMs = millis();
  stale = false;
}

// ------------------------------------------------------------------ setup
void setup() {
  Serial.begin(115200);

  // Adjuntar el servo SIEMPRE al arrancar. Sin esto no se emite ningun pulso
  // y el servo no se mueve (Servo::write no hace nada si no esta attached).
  servo.attach(PIN_SERVO, PULSE_MIN_US, PULSE_MAX_US);
  attached = true;

  // Banner ANTES del auto-test: asi el PC sabe que el firmware correcto esta
  // cargado aunque el barrido de arranque siga en marcha.
  Serial.println(F("R servo_tracker 1.3"));
  Serial.flush();

  // Auto-test de arranque: 90 -> 45 -> 135 -> 90 (una vez, no bloqueante).
  // Sirve para comprobar de un vistazo que el servo tiene alimentacion y
  // que el sketch cargado es este y no otro.
  booting = true;
  bootStep = 0;
  bootMs = millis();
  servo.write(90);

  posDeg = 0.0;
  targetDeg = 0.0;
  velDeg = 0.0;

  lastCmdMs = millis();
  lastStepMs = millis();
  lastStatusMs = millis();
}

// ------------------------------------------------------------------- loop
void loop() {
  unsigned long now = millis();

  // Comandos serie (no bloqueante). Se atienden tambien durante el arranque:
  // la consigna queda guardada y se aplica al terminar el barrido.
  while (Serial.available() > 0) {
    char ch = (char)Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (bufLen > 0) {
        buf[bufLen] = 0;
        handleLine(buf);
        bufLen = 0;
      }
    } else if (bufLen < sizeof(buf) - 1) {
      buf[bufLen++] = ch;
    } else {
      bufLen = 0;  // linea demasiado larga: descartar
    }
  }

  if (booting) {
    bootSweep(now);
  } else {
    // Watchdog: si el PC deja de hablar, frenar suavemente
    if (now - lastCmdMs > WATCHDOG_MS) {
      stale = true;
    }

    // Perfil de movimiento
    if (now - lastStepMs >= STEP_MS) {
      float dt = (now - lastStepMs) / 1000.0;
      lastStepMs = now;
      stepProfile(dt);
    }
  }

  // Reporte de estado (tambien durante el barrido de arranque)
  if (now - lastStatusMs >= STATUS_MS) {
    lastStatusMs = now;
    reportStatus();
  }
}
