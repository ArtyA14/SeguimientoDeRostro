/*
 * pan_tracker.ino - Seguimiento de rostro: eje pan con 28BYJ-48 + ULN2003
 *
 * El PC (Python + MediaPipe) hace la vision y manda la consigna en grados.
 * El Arduino solo posiciona: perfil de pasos con aceleracion, limites suaves
 * y watchdog (si el PC deja de hablar, se detiene).
 *
 * Protocolo serie (115200, una linea por comando, terminada en \n):
 *   P <grados>        consigna absoluta
 *   Z                 marcar posicion actual como 0
 *   L <min> <max>     limites suaves (grados)
 *   S <vel> <acel>    velocidad maxima (pasos/s) y aceleracion (pasos/s^2)
 *   H                 parar desacelerando
 *   X                 soltar bobinas
 *   ?                 pedir estado
 *
 * Respuestas:
 *   R pan_tracker 1.0
 *   S <pos> <obj> <moviendo> <limite>      cada 50 ms
 *
 * Cableado (ULN2003 -> Arduino):
 *   IN1 -> D8      IN2 -> D9      IN3 -> D10     IN4 -> D11
 *   VCC del modulo -> fuente externa 5V (NO del Arduino)
 *   GND del modulo -> GND Arduino y GND de la fuente (GND comun)
 *
 * Requiere la libreria "AccelStepper" (Gestor de librerias -> buscar).
 */

#include <AccelStepper.h>

// ---------------------------------------------------------------- pines
const uint8_t PIN_IN1 = 8;
const uint8_t PIN_IN2 = 9;
const uint8_t PIN_IN3 = 10;
const uint8_t PIN_IN4 = 11;

// ------------------------------------------------------- motor 28BYJ-48
// En medio paso: 64 pasos internos * 64 de reductor = 4096 medios pasos/vuelta
const float STEPS_PER_REV = 4096.0;
const float DEG_PER_STEP = 360.0 / STEPS_PER_REV;  // 0.0879 deg

// Orden correcto para HALF4WIRE con ULN2003: IN1, IN3, IN2, IN4
AccelStepper stepper(AccelStepper::HALF4WIRE, PIN_IN1, PIN_IN3, PIN_IN2, PIN_IN4);

// ------------------------------------------------------------- ajustes
float maxSpeedSteps = 600.0;   // pasos/s (~52 deg/s). Mas de 800 suele perder pasos
float accelSteps = 500.0;      // pasos/s^2
long minStep = -1024;          // -90 deg
long maxStep = 1024;           // +90 deg
long targetStep = 0;

const unsigned long WATCHDOG_MS = 500;   // sin comandos -> parar
const unsigned long STATUS_MS = 50;      // reporte de estado

unsigned long lastCmdMs = 0;
unsigned long lastStatusMs = 0;
bool stale = false;
bool outputsEnabled = true;

char buf[32];
uint8_t bufLen = 0;

// -------------------------------------------------------------- utilidades
void applyMotion() {
  stepper.setMaxSpeed(maxSpeedSteps);
  stepper.setAcceleration(accelSteps);
}

void setTargetDeg(float deg) {
  long step = lround(deg / DEG_PER_STEP);
  if (step < minStep) step = minStep;
  if (step > maxStep) step = maxStep;
  targetStep = step;
  if (!outputsEnabled) {
    stepper.enableOutputs();
    outputsEnabled = true;
  }
  stepper.moveTo(targetStep);
}

void reportStatus() {
  Serial.print(F("S "));
  Serial.print(stepper.currentPosition() * DEG_PER_STEP, 2);
  Serial.print(' ');
  Serial.print(targetStep * DEG_PER_STEP, 2);
  Serial.print(' ');
  Serial.print(stepper.distanceToGo() != 0 ? 1 : 0);
  Serial.print(' ');
  long pos = stepper.currentPosition();
  Serial.println((pos <= minStep || pos >= maxStep) ? 1 : 0);
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
      stepper.setCurrentPosition(0);
      targetStep = 0;
      stepper.moveTo(0);
      break;

    case 'L': {
      float a = atof(arg);
      char *sep = strpbrk(arg, " ,");
      if (sep) {
        float b = atof(sep + 1);
        if (b > a) {
          minStep = lround(a / DEG_PER_STEP);
          maxStep = lround(b / DEG_PER_STEP);
          setTargetDeg(stepper.currentPosition() * DEG_PER_STEP);
        }
      }
      break;
    }

    case 'S': {
      float sp = atof(arg);
      char *sep = strpbrk(arg, " ,");
      if (sp > 0) maxSpeedSteps = sp;
      if (sep) {
        float ac = atof(sep + 1);
        if (ac > 0) accelSteps = ac;
      }
      applyMotion();
      break;
    }

    case 'H':
      stepper.stop();                       // desacelera hasta parar
      targetStep = stepper.targetPosition();
      break;

    case 'X':
      stepper.disableOutputs();             // motor libre
      outputsEnabled = false;
      targetStep = stepper.currentPosition();
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
  applyMotion();
  stepper.setCurrentPosition(0);
  stepper.enableOutputs();
  lastCmdMs = millis();
  Serial.println(F("R pan_tracker 1.0"));
}

// ------------------------------------------------------------------- loop
void loop() {
  // Watchdog: sin comandos del PC, detenerse solo
  if (millis() - lastCmdMs > WATCHDOG_MS) {
    if (!stale) {
      stale = true;
      stepper.stop();
      targetStep = stepper.targetPosition();
    }
  }

  stepper.run();

  if (millis() - lastStatusMs >= STATUS_MS) {
    lastStatusMs = millis();
    reportStatus();
  }

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
}
