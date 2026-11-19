/*
  Curtain servo serial console

  Interactive command prompt for a continuous-rotation servo on pin 6.
  Open the Serial Monitor at 9600 baud, type "help" and press Enter.
  Set the Serial Monitor line ending to "Newline". "Carriage return" and
  "Both NL & CR" also work; "No line ending" does not.

  Written for AVR boards (Uno, Nano, Mega). Nothing here calls delay(), so
  a stop command is acted on straight away, even in the middle of a move.
*/

#include <Servo.h>
#include <EEPROM.h>

const uint8_t SERVO_PIN = 6;
const unsigned long BAUD = 9600;

// Pulse widths that Servo.write(0), write(90) and write(180) produce after a
// plain attach(pin). Using them as defaults makes "f", "b" and "s" behave
// exactly like write(180), write(0) and write(90).
const int US_WRITE_0 = 544;
const int US_WRITE_90 = 1472;
const int US_WRITE_180 = 2400;

const int US_ABS_MIN = 500;
const int US_ABS_MAX = 2500;

const unsigned long TICK_MS = 10;
const unsigned long STALE_INPUT_MS = 5000;
const unsigned long SWEEP_REST_MS = 1000;
const unsigned long MAX_MOVE_MS = 3600000UL;
const unsigned int MAX_RAMP_MS = 5000;
const unsigned int MAX_LIMIT_SEC = 3600;
const uint8_t LINE_CAPACITY = 40;
const uint8_t MAX_TOKENS = 5;
const uint8_t STATUS_LINES = 11;

const uint16_t SETTINGS_MAGIC = 0xC5E1;
const int EEPROM_ADDR = 0;

struct Settings {
  uint16_t magic;
  int16_t stopUs;
  int16_t minUs;
  int16_t maxUs;
  uint16_t rampMs;
  uint16_t limitSec;
  uint32_t openMs;
  uint32_t closeMs;
  uint8_t speedPct;
  uint8_t invert;
};

enum Mode : uint8_t { MODE_STOPPED, MODE_RUN, MODE_RAW, MODE_CYCLE, MODE_SWEEP };
enum Job : uint8_t { JOB_NONE, JOB_HELP, JOB_STATUS };

// Kept in flash and printed one line per loop pass so a long listing never
// holds up the motor timing. Lines must stay under 62 characters.
const char HELP_TEXT[] PROGMEM =
  "Motion\n"
  "  f [speed] [secs]     forward: f | f 40 | f 100 10\n"
  "  b [speed] [secs]     backward\n"
  "  s | x | blank Enter  stop now\n"
  "  jog f|b [ms]         short pulse, default 200 ms\n"
  "  open [secs]          forward for the open time\n"
  "  close [secs]         backward for the close time\n"
  "  cycle [n] [run] [pause]   forward, pause, backward, pause\n"
  "                       default 1 10 2 (secs), n = 0 repeats\n"
  "Raw output (no ramp)\n"
  "  w <0-180>            same pulse as Servo.write(angle)\n"
  "  us <500-2500>        pulse width in microseconds\n"
  "  sweep [us] [ms]      step out from stop, both directions\n"
  "  detach | attach      servo signal off / on\n"
  "Tuning (give no value to show the current one)\n"
  "  speed <0-100>        default speed in percent\n"
  "  trim <us> | +n | -n  stop pulse, to cure creep when stopped\n"
  "  min <us> | max <us>  pulse widths used at 100 percent\n"
  "  ramp <ms>            soft start and stop, 0 = instant\n"
  "  invert [on|off]      swap forward and backward\n"
  "  opentime <secs> | closetime <secs>\n"
  "  limit <secs>         auto-stop for untimed moves, 0 = off\n"
  "Info and storage\n"
  "  status               everything at a glance\n"
  "  pos | zero           net run time estimate, and reset it\n"
  "  save | load | reset  EEPROM settings, factory defaults\n"
  "  help | ?             this list\n";

Servo curtainMotor;
Settings cfg;
bool unsaved = false;

bool attached = false;
int outputUs = US_WRITE_90;
int targetUs = US_WRITE_90;
unsigned long lastTickMs = 0;
unsigned long rampAccum = 0;
long posAccum = 0;
long netMs = 0;

Mode mode = MODE_STOPPED;
bool phaseTimed = false;
unsigned long phaseStartMs = 0;
unsigned long phaseDurMs = 0;

int8_t runDir = 1;
uint8_t runPct = 0;
bool runInstant = false;
bool runLimited = false;

unsigned long cycleTotal = 0;
unsigned long cycleIndex = 0;
uint8_t cyclePhase = 0;
unsigned long cycleRunMs = 0;
unsigned long cyclePauseMs = 0;

int8_t sweepDir = 1;
int sweepOffset = 0;
int sweepStepUs = 0;
unsigned long sweepStepMs = 0;
bool sweepResting = false;

char lineBuf[LINE_CAPACITY + 1];
uint8_t lineLen = 0;
bool lineOverflow = false;
bool lastWasCR = false;
unsigned long lastRxMs = 0;

Job job = JOB_NONE;
uint16_t jobPos = 0;
int txNeed = 0;
bool promptShown = false;

// ---------------------------------------------------------------- console

void prompt() {
  Serial.print(F("> "));
  promptShown = true;
}

// Call before printing anything that is not the direct reply to a command,
// so it does not land on the same line as a waiting prompt.
void eventLine() {
  if (promptShown) {
    Serial.println();
    promptShown = false;
  }
}

void printSeconds(unsigned long ms) {
  Serial.print(ms / 1000.0, 2);
  Serial.print(F(" s"));
}

void printDir(int8_t dir) {
  Serial.print(dir > 0 ? F("forward") : F("backward"));
}

void printSigned(long value) {
  if (value >= 0) Serial.print('+');
  Serial.print(value);
}

void usage(const __FlashStringHelper *text) {
  Serial.print(F("usage: "));
  Serial.println(text);
}

// --------------------------------------------------------------- settings

void setDefaults() {
  cfg.magic = SETTINGS_MAGIC;
  cfg.stopUs = US_WRITE_90;
  cfg.minUs = US_WRITE_0;
  cfg.maxUs = US_WRITE_180;
  cfg.rampMs = 0;
  cfg.limitSec = 60;
  cfg.openMs = 10000;
  cfg.closeMs = 10000;
  cfg.speedPct = 100;
  cfg.invert = 0;
}

bool loadSettings() {
  Settings s;
  EEPROM.get(EEPROM_ADDR, s);
  bool ok = s.magic == SETTINGS_MAGIC
            && s.minUs >= US_ABS_MIN && s.maxUs <= US_ABS_MAX
            && s.minUs < s.stopUs && s.stopUs < s.maxUs
            && s.rampMs <= MAX_RAMP_MS && s.limitSec <= MAX_LIMIT_SEC
            && s.openMs >= 1 && s.openMs <= MAX_MOVE_MS
            && s.closeMs >= 1 && s.closeMs <= MAX_MOVE_MS
            && s.speedPct <= 100 && s.invert <= 1;
  if (ok) cfg = s;
  return ok;
}

// ----------------------------------------------------------- servo output

void writeOutput(int us) {
  outputUs = us;
  if (attached) curtainMotor.writeMicroseconds(us);
}

void setTarget(int us, bool instant) {
  targetUs = us;
  if (instant || cfg.rampMs == 0) writeOutput(us);
}

void attachServo() {
  outputUs = targetUs = cfg.stopUs;
  // Set the pulse before attaching so the first pulse sent is "stop".
  curtainMotor.writeMicroseconds(cfg.stopUs);
  curtainMotor.attach(SERVO_PIN, US_ABS_MIN, US_ABS_MAX);
  curtainMotor.writeMicroseconds(cfg.stopUs);
  attached = true;
}

void ensureAttached() {
  if (attached) return;
  attachServo();
  Serial.println(F("(servo re-attached)"));
}

// True when a logical direction maps to pulses longer than the stop pulse.
bool pulsesUp(int8_t dir) {
  return (dir > 0) != (cfg.invert != 0);
}

int spanFor(int8_t dir) {
  return pulsesUp(dir) ? cfg.maxUs - cfg.stopUs : cfg.stopUs - cfg.minUs;
}

int usForOffset(int8_t dir, int offset) {
  return pulsesUp(dir) ? cfg.stopUs + offset : cfg.stopUs - offset;
}

int usForSpeed(int8_t dir, uint8_t pct) {
  return usForOffset(dir, (int)((long)spanFor(dir) * pct / 100));
}

// ----------------------------------------------------------------- motion

void beginPhase(unsigned long durationMs) {
  phaseStartMs = millis();
  phaseDurMs = durationMs;
  phaseTimed = true;
}

void haltMotion(bool instant) {
  mode = MODE_STOPPED;
  phaseTimed = false;
  setTarget(cfg.stopUs, instant);
}

// durationMs 0 means untimed, which the "limit" setting may still cap.
void armRunTimer(unsigned long durationMs) {
  runLimited = false;
  phaseTimed = false;
  if (durationMs == 0 && cfg.limitSec > 0) {
    durationMs = cfg.limitSec * 1000UL;
    runLimited = true;
  }
  if (durationMs > 0) beginPhase(durationMs);
}

void startRun(int8_t dir, uint8_t pct, unsigned long durationMs, bool instant) {
  ensureAttached();
  mode = MODE_RUN;
  runDir = dir;
  runPct = pct;
  runInstant = instant;
  armRunTimer(durationMs);
  setTarget(usForSpeed(dir, pct), instant);
}

void startRaw(int us) {
  ensureAttached();
  if (us == cfg.stopUs) {
    haltMotion(true);
    return;
  }
  mode = MODE_RAW;
  runInstant = true;
  armRunTimer(0);
  setTarget(us, true);
}

void finishRun() {
  bool limited = runLimited;
  unsigned long ranMs = phaseDurMs;
  haltMotion(runInstant);
  eventLine();
  if (limited) {
    Serial.print(F("[limit] stopped after "));
    printSeconds(ranMs);
    Serial.println(F(" - see 'limit'"));
  } else {
    Serial.println(F("[done] move finished"));
  }
  prompt();
}

void enterCyclePhase() {
  bool moving = (cyclePhase % 2) == 0;
  int8_t dir = cyclePhase == 0 ? 1 : -1;
  setTarget(moving ? usForSpeed(dir, cfg.speedPct) : cfg.stopUs, false);
  beginPhase(moving ? cycleRunMs : cyclePauseMs);
  if (!moving) return;
  eventLine();
  Serial.print(F("[cycle "));
  Serial.print(cycleIndex + 1);
  if (cycleTotal > 0) {
    Serial.print('/');
    Serial.print(cycleTotal);
  }
  Serial.print(F("] "));
  printDir(dir);
  Serial.println();
}

void startCycle(unsigned long count, unsigned long runMs, unsigned long pauseMs) {
  ensureAttached();
  mode = MODE_CYCLE;
  cycleTotal = count;
  cycleIndex = 0;
  cyclePhase = 0;
  cycleRunMs = runMs;
  cyclePauseMs = pauseMs;
  enterCyclePhase();
}

void advanceCycle() {
  if (++cyclePhase == 4) {
    cyclePhase = 0;
    cycleIndex++;
    if (cycleTotal > 0 && cycleIndex >= cycleTotal) {
      haltMotion(false);
      eventLine();
      Serial.println(F("[cycle] finished"));
      prompt();
      return;
    }
  }
  enterCyclePhase();
}

void printSweepPoint() {
  printDir(sweepDir);
  Serial.print(F(" +"));
  Serial.print(sweepOffset);
  Serial.print(F(" us = "));
  Serial.print(usForOffset(sweepDir, sweepOffset));
  Serial.println(F(" us"));
}

void advanceSweep() {
  if (sweepResting) {
    sweepResting = false;
    sweepDir = -1;
    sweepOffset = 0;
  }
  int span = spanFor(sweepDir);
  if (sweepOffset >= span) {
    setTarget(cfg.stopUs, true);
    if (sweepDir > 0) {
      sweepResting = true;
      beginPhase(SWEEP_REST_MS);
      return;
    }
    haltMotion(true);
    eventLine();
    Serial.println(F("[sweep] finished"));
    prompt();
    return;
  }
  sweepOffset = min(sweepOffset + sweepStepUs, span);
  setTarget(usForOffset(sweepDir, sweepOffset), true);
  beginPhase(sweepStepMs);
  eventLine();
  Serial.print(F("[sweep] "));
  printSweepPoint();
}

void startSweep(int stepUs, unsigned long stepMs) {
  ensureAttached();
  mode = MODE_SWEEP;
  sweepDir = 1;
  sweepOffset = 0;
  sweepStepUs = stepUs;
  sweepStepMs = stepMs;
  sweepResting = false;
  advanceSweep();
}

// Net run time in the forward direction, weighted by speed. It is only a
// time-based estimate: the sketch has no position feedback from the servo.
void trackPosition(unsigned long dt) {
  if (!attached) return;
  long offset = outputUs - cfg.stopUs;
  if (offset == 0) return;
  long span = offset > 0 ? cfg.maxUs - cfg.stopUs : cfg.stopUs - cfg.minUs;
  long permille = offset * 1000L / span;
  if (cfg.invert) permille = -permille;
  posAccum += permille * (long)dt;
  netMs += posAccum / 1000;
  posAccum %= 1000;
}

void stepRamp(unsigned long dt) {
  if (outputUs == targetUs) {
    rampAccum = 0;
    return;
  }
  if (cfg.rampMs == 0) {
    writeOutput(targetUs);
    return;
  }
  // rampMs is the time to cover a full stop-to-top-speed change.
  rampAccum += (unsigned long)(US_WRITE_180 - US_WRITE_90) * dt;
  int step = (int)min(rampAccum / cfg.rampMs, 2000UL);
  rampAccum %= cfg.rampMs;
  if (step == 0) return;
  int gap = targetUs - outputUs;
  if (gap > step) gap = step;
  if (gap < -step) gap = -step;
  writeOutput(outputUs + gap);
}

void motionTick() {
  unsigned long now = millis();
  unsigned long dt = now - lastTickMs;
  if (dt >= TICK_MS) {
    lastTickMs = now;
    trackPosition(dt);
    stepRamp(dt);
  }
  if (!phaseTimed || now - phaseStartMs < phaseDurMs) return;
  switch (mode) {
    case MODE_RUN:
    case MODE_RAW:
      finishRun();
      break;
    case MODE_CYCLE:
      advanceCycle();
      break;
    case MODE_SWEEP:
      advanceSweep();
      break;
    default:
      phaseTimed = false;
      break;
  }
}

// ---------------------------------------------------------------- parsing

bool parseLong(const char *text, long lo, long hi, long &out) {
  char *end;
  long value = strtol(text, &end, 10);
  if (end == text || *end != '\0' || value < lo || value > hi) return false;
  out = value;
  return true;
}

// Reads seconds such as "10" or "2.5" and returns milliseconds.
bool parseSeconds(const char *text, unsigned long minMs, unsigned long &out) {
  char *end;
  double value = strtod(text, &end);
  if (end == text || *end != '\0') return false;
  if (!(value >= 0.0 && value <= MAX_MOVE_MS / 1000.0)) return false;
  unsigned long ms = (unsigned long)(value * 1000.0 + 0.5);
  if (ms < minMs) return false;
  out = ms;
  return true;
}

bool parseDirection(const char *text, int8_t &dir) {
  if (!strcmp_P(text, PSTR("f")) || !strcmp_P(text, PSTR("fwd")) || !strcmp_P(text, PSTR("forward"))) {
    dir = 1;
    return true;
  }
  if (!strcmp_P(text, PSTR("b")) || !strcmp_P(text, PSTR("back")) || !strcmp_P(text, PSTR("backward"))) {
    dir = -1;
    return true;
  }
  return false;
}

// Optional argument of a "<name> [value]" tuning command. Returns false when
// the argument is unusable, and leaves value alone when there is none.
bool settingArg(uint8_t argc, char **argv, long lo, long hi, long &value) {
  if (argc == 0) return true;
  if (argc == 1 && parseLong(argv[0], lo, hi, value)) {
    unsaved = true;
    return true;
  }
  Serial.print(F("expected one whole number from "));
  Serial.print(lo);
  Serial.print(F(" to "));
  Serial.println(hi);
  return false;
}

// --------------------------------------------------------------- commands

void announceRun() {
  printDir(runDir);
  Serial.print(' ');
  Serial.print(runPct);
  Serial.print(F("% = "));
  Serial.print(targetUs);
  Serial.print(F(" us"));
  if (!phaseTimed) {
    Serial.println(F(", until stopped"));
    return;
  }
  Serial.print(runLimited ? F(", auto-stop after ") : F(" for "));
  printSeconds(phaseDurMs);
  Serial.println();
}

void cmdStop() {
  bool midSweep = mode == MODE_SWEEP && !sweepResting;
  haltMotion(true);
  if (midSweep) {
    Serial.print(F("stopped - sweep was at "));
    printSweepPoint();
  } else {
    Serial.println(F("stopped"));
  }
}

void cmdRun(int8_t dir, uint8_t argc, char **argv) {
  long pct = cfg.speedPct;
  unsigned long ms = 0;
  if (argc > 2
      || (argc >= 1 && !parseLong(argv[0], 0, 100, pct))
      || (argc >= 2 && !parseSeconds(argv[1], 1, ms))) {
    usage(F("f|b [speed 0-100] [secs up to 3600]"));
    return;
  }
  startRun(dir, (uint8_t)pct, ms, false);
  announceRun();
}

void cmdTravel(int8_t dir, uint8_t argc, char **argv) {
  unsigned long ms = dir > 0 ? cfg.openMs : cfg.closeMs;
  if (argc > 1 || (argc == 1 && !parseSeconds(argv[0], 1, ms))) {
    usage(F("open|close [secs up to 3600]"));
    return;
  }
  startRun(dir, cfg.speedPct, ms, false);
  announceRun();
}

void cmdJog(uint8_t argc, char **argv) {
  int8_t dir = 1;
  long ms = 200;
  if (argc < 1 || argc > 2 || !parseDirection(argv[0], dir)
      || (argc == 2 && !parseLong(argv[1], 10, 5000, ms))) {
    usage(F("jog f|b [ms 10-5000]"));
    return;
  }
  startRun(dir, cfg.speedPct, (unsigned long)ms, true);
  Serial.print(F("jog "));
  printDir(dir);
  Serial.print(' ');
  Serial.print(ms);
  Serial.println(F(" ms"));
}

void cmdCycle(uint8_t argc, char **argv) {
  long count = 1;
  unsigned long runMs = 10000;
  unsigned long pauseMs = 2000;
  if (argc > 3
      || (argc >= 1 && !parseLong(argv[0], 0, 100000, count))
      || (argc >= 2 && !parseSeconds(argv[1], 1, runMs))
      || (argc >= 3 && !parseSeconds(argv[2], 0, pauseMs))) {
    usage(F("cycle [count, 0 = repeat] [run secs] [pause secs]"));
    return;
  }
  Serial.print(F("cycle: "));
  if (count == 0) {
    Serial.print(F("repeating"));
  } else {
    Serial.print(count);
    Serial.print(F(" x"));
  }
  Serial.print(F(", run "));
  printSeconds(runMs);
  Serial.print(F(", pause "));
  printSeconds(pauseMs);
  Serial.println();
  startCycle((unsigned long)count, runMs, pauseMs);
}

void cmdRaw(bool asAngle, uint8_t argc, char **argv) {
  long value = 0;
  if (asAngle) {
    if (argc != 1 || !parseLong(argv[0], 0, 180, value)) {
      usage(F("w <angle 0-180>"));
      return;
    }
    value = map(value, 0, 180, US_WRITE_0, US_WRITE_180);
  } else if (argc != 1 || !parseLong(argv[0], US_ABS_MIN, US_ABS_MAX, value)) {
    usage(F("us <500-2500>"));
    return;
  }
  startRaw((int)value);
  Serial.print(F("raw output "));
  Serial.print(value);
  Serial.print(F(" us"));
  if (mode != MODE_RAW) {
    Serial.println(F(" = stop"));
    return;
  }
  if (phaseTimed) {
    Serial.print(F(", auto-stop after "));
    printSeconds(phaseDurMs);
  }
  Serial.println();
}

void cmdSweep(uint8_t argc, char **argv) {
  long stepUs = 20;
  long stepMs = 500;
  if (argc > 2
      || (argc >= 1 && !parseLong(argv[0], 1, 200, stepUs))
      || (argc >= 2 && !parseLong(argv[1], 100, 10000, stepMs))) {
    usage(F("sweep [step us 1-200] [step ms 100-10000]"));
    return;
  }
  Serial.print(F("sweep: "));
  Serial.print(stepUs);
  Serial.print(F(" us every "));
  Serial.print(stepMs);
  Serial.println(F(" ms, send s when it moves"));
  startSweep((int)stepUs, (unsigned long)stepMs);
}

void cmdTrim(uint8_t argc, char **argv) {
  if (argc == 1) {
    bool relative = argv[0][0] == '+' || argv[0][0] == '-';
    long value = 0;
    if (!parseLong(argv[0], -2000, US_ABS_MAX, value)) {
      usage(F("trim <us> | trim +n | trim -n"));
      return;
    }
    if (relative) value += cfg.stopUs;
    if (value <= cfg.minUs || value >= cfg.maxUs) {
      Serial.print(F("stop pulse must stay between "));
      Serial.print(cfg.minUs + 1);
      Serial.print(F(" and "));
      Serial.print(cfg.maxUs - 1);
      Serial.println(F(" us"));
      return;
    }
    cfg.stopUs = (int16_t)value;
    unsaved = true;
    haltMotion(true);
  } else if (argc > 1) {
    usage(F("trim <us> | trim +n | trim -n"));
    return;
  }
  Serial.print(F("stop pulse = "));
  Serial.print(cfg.stopUs);
  Serial.print(F(" us ("));
  printSigned((long)cfg.stopUs - US_WRITE_90);
  Serial.println(F(" from write(90))"));
}

void cmdInvert(uint8_t argc, char **argv) {
  bool wanted = !cfg.invert;
  if (argc == 1 && !strcmp_P(argv[0], PSTR("on"))) wanted = true;
  else if (argc == 1 && !strcmp_P(argv[0], PSTR("off"))) wanted = false;
  else if (argc != 0) {
    usage(F("invert [on|off]"));
    return;
  }
  haltMotion(true);
  cfg.invert = wanted;
  unsaved = true;
  Serial.print(F("invert = "));
  Serial.println(cfg.invert ? F("on") : F("off"));
}

void cmdTravelTime(bool opening, uint8_t argc, char **argv) {
  unsigned long ms = opening ? cfg.openMs : cfg.closeMs;
  if (argc > 1 || (argc == 1 && !parseSeconds(argv[0], 1, ms))) {
    usage(F("opentime|closetime <secs up to 3600>"));
    return;
  }
  if (argc == 1) {
    if (opening) cfg.openMs = ms;
    else cfg.closeMs = ms;
    unsaved = true;
  }
  Serial.print(opening ? F("open time = ") : F("close time = "));
  printSeconds(ms);
  Serial.println();
}

void printPosition() {
  if (netMs >= 0) Serial.print('+');
  Serial.print(netMs / 1000.0, 2);
  Serial.println(F(" s net forward, speed-weighted estimate"));
}

void printSetting(const __FlashStringHelper *label, long value, const __FlashStringHelper *unit) {
  Serial.print(label);
  Serial.print(value);
  Serial.println(unit);
}

void execute(uint8_t tokenCount, char **tokens) {
  const char *cmd = tokens[0];
  uint8_t argc = tokenCount - 1;
  char **argv = tokens + 1;
  long value;

#define IS(name) (strcmp_P(cmd, PSTR(name)) == 0)

  if (IS("s") || IS("stop") || IS("x")) {
    cmdStop();
  } else if (IS("f") || IS("fwd") || IS("forward")) {
    cmdRun(1, argc, argv);
  } else if (IS("b") || IS("back") || IS("backward")) {
    cmdRun(-1, argc, argv);
  } else if (IS("open")) {
    cmdTravel(1, argc, argv);
  } else if (IS("close")) {
    cmdTravel(-1, argc, argv);
  } else if (IS("jog")) {
    cmdJog(argc, argv);
  } else if (IS("cycle")) {
    cmdCycle(argc, argv);
  } else if (IS("w")) {
    cmdRaw(true, argc, argv);
  } else if (IS("us")) {
    cmdRaw(false, argc, argv);
  } else if (IS("sweep")) {
    cmdSweep(argc, argv);
  } else if (IS("detach")) {
    haltMotion(true);
    if (attached) curtainMotor.detach();
    attached = false;
    Serial.println(F("servo detached - no signal on the pin"));
  } else if (IS("attach")) {
    if (attached) {
      Serial.println(F("servo already attached"));
    } else {
      attachServo();
      Serial.println(F("servo attached, stopped"));
    }
  } else if (IS("speed")) {
    value = cfg.speedPct;
    if (!settingArg(argc, argv, 0, 100, value)) return;
    cfg.speedPct = (uint8_t)value;
    printSetting(F("speed = "), value, F(" %"));
  } else if (IS("trim")) {
    cmdTrim(argc, argv);
  } else if (IS("min")) {
    value = cfg.minUs;
    if (!settingArg(argc, argv, US_ABS_MIN, cfg.stopUs - 1, value)) return;
    cfg.minUs = (int16_t)value;
    printSetting(F("min pulse = "), value, F(" us"));
  } else if (IS("max")) {
    value = cfg.maxUs;
    if (!settingArg(argc, argv, cfg.stopUs + 1, US_ABS_MAX, value)) return;
    cfg.maxUs = (int16_t)value;
    printSetting(F("max pulse = "), value, F(" us"));
  } else if (IS("ramp")) {
    value = cfg.rampMs;
    if (!settingArg(argc, argv, 0, MAX_RAMP_MS, value)) return;
    cfg.rampMs = (uint16_t)value;
    printSetting(F("ramp = "), value, F(" ms"));
  } else if (IS("invert")) {
    cmdInvert(argc, argv);
  } else if (IS("opentime")) {
    cmdTravelTime(true, argc, argv);
  } else if (IS("closetime")) {
    cmdTravelTime(false, argc, argv);
  } else if (IS("limit")) {
    value = cfg.limitSec;
    if (!settingArg(argc, argv, 0, MAX_LIMIT_SEC, value)) return;
    cfg.limitSec = (uint16_t)value;
    printSetting(F("limit = "), value, value ? F(" s") : F(" (off)"));
  } else if (IS("status")) {
    job = JOB_STATUS;
    jobPos = 0;
  } else if (IS("pos")) {
    Serial.print(F("position: "));
    printPosition();
  } else if (IS("zero")) {
    netMs = 0;
    posAccum = 0;
    Serial.print(F("position: "));
    printPosition();
  } else if (IS("save")) {
    EEPROM.put(EEPROM_ADDR, cfg);
    unsaved = false;
    Serial.println(F("settings saved to EEPROM"));
  } else if (IS("load")) {
    if (loadSettings()) {
      unsaved = false;
      haltMotion(true);
      Serial.println(F("settings loaded from EEPROM, stopped"));
    } else {
      Serial.println(F("no saved settings found"));
    }
  } else if (IS("reset")) {
    setDefaults();
    unsaved = true;
    haltMotion(true);
    Serial.println(F("defaults restored - 'save' to keep them"));
  } else if (IS("help") || IS("?")) {
    job = JOB_HELP;
    jobPos = 0;
  } else {
    Serial.print(F("unknown command '"));
    Serial.print(cmd);
    Serial.println(F("' - type help"));
  }

#undef IS
}

// ------------------------------------------------------- long listings

bool printHelpLine() {
  for (;;) {
    char c = (char)pgm_read_byte(HELP_TEXT + jobPos);
    if (c == '\0') return false;
    jobPos++;
    if (c == '\n') {
      Serial.println();
      return true;
    }
    Serial.write(c);
  }
}

void printStateLine() {
  Serial.print(F("state    : "));
  switch (mode) {
    case MODE_RUN:
      printDir(runDir);
      Serial.print(' ');
      Serial.print(runPct);
      Serial.print('%');
      break;
    case MODE_RAW:
      Serial.print(F("raw output"));
      break;
    case MODE_CYCLE:
      Serial.print(F("cycle "));
      Serial.print(cycleIndex + 1);
      if (cycleTotal > 0) {
        Serial.print('/');
        Serial.print(cycleTotal);
      }
      if (cyclePhase == 0) Serial.print(F(" forward"));
      else if (cyclePhase == 2) Serial.print(F(" backward"));
      else Serial.print(F(" pause"));
      break;
    case MODE_SWEEP:
      Serial.print(F("sweep"));
      break;
    default:
      Serial.print(F("stopped"));
      break;
  }
  if (phaseTimed) {
    unsigned long elapsed = millis() - phaseStartMs;
    Serial.print(F(", "));
    printSeconds(elapsed < phaseDurMs ? phaseDurMs - elapsed : 0);
    Serial.print(F(" left"));
  }
  Serial.println();
}

bool printStatusLine() {
  if (jobPos >= STATUS_LINES) return false;
  switch (jobPos++) {
    case 0:
      printStateLine();
      break;
    case 1:
      Serial.print(F("output   : "));
      Serial.print(outputUs);
      Serial.print(F(" us"));
      if (outputUs != targetUs) {
        Serial.print(F(" ramping to "));
        Serial.print(targetUs);
      }
      Serial.println(attached ? F("") : F(" (detached, no signal)"));
      break;
    case 2:
      printSetting(F("speed    : "), cfg.speedPct, F(" %"));
      break;
    case 3:
      printSetting(F("stop     : "), cfg.stopUs, F(" us"));
      break;
    case 4:
      Serial.print(F("range    : "));
      Serial.print(cfg.minUs);
      Serial.print(F(" to "));
      Serial.print(cfg.maxUs);
      Serial.println(F(" us"));
      break;
    case 5:
      printSetting(F("ramp     : "), cfg.rampMs, F(" ms"));
      break;
    case 6:
      Serial.print(F("invert   : "));
      Serial.println(cfg.invert ? F("on") : F("off"));
      break;
    case 7:
      Serial.print(F("open     : "));
      printSeconds(cfg.openMs);
      Serial.print(F(", close "));
      printSeconds(cfg.closeMs);
      Serial.println();
      break;
    case 8:
      printSetting(F("limit    : "), cfg.limitSec, cfg.limitSec ? F(" s") : F(" (off)"));
      break;
    case 9:
      Serial.print(F("position : "));
      printPosition();
      break;
    default:
      Serial.print(F("settings : "));
      Serial.println(unsaved ? F("changed, not saved") : F("match EEPROM or defaults"));
      break;
  }
  return true;
}

// Prints one line of a pending listing whenever the serial buffer has room,
// so the loop keeps servicing the motor and incoming commands meanwhile.
void outputTick() {
  if (job == JOB_NONE || Serial.availableForWrite() < txNeed) return;
  bool printed = job == JOB_HELP ? printHelpLine() : printStatusLine();
  if (!printed) {
    job = JOB_NONE;
    prompt();
  }
}

// ----------------------------------------------------------- serial input

void submitLine() {
  lineBuf[lineLen] = '\0';
  bool overflow = lineOverflow;
  lineLen = 0;
  lineOverflow = false;
  job = JOB_NONE;

  if (!promptShown) Serial.print(F("> "));
  Serial.println(lineBuf);
  promptShown = false;

  if (overflow) {
    Serial.println(F("line too long - ignored"));
  } else {
    char *tokens[MAX_TOKENS];
    uint8_t count = 0;
    bool tooMany = false;
    for (char *p = lineBuf; *p; p++) *p = (char)tolower((unsigned char)*p);
    for (char *t = strtok(lineBuf, " \t,"); t != NULL; t = strtok(NULL, " \t,")) {
      if (count < MAX_TOKENS) tokens[count++] = t;
      else tooMany = true;
    }
    if (tooMany) Serial.println(F("too many values - type help"));
    else if (count == 0) cmdStop();
    else execute(count, tokens);
  }

  if (job == JOB_NONE) prompt();
}

void readSerial() {
  while (Serial.available() > 0) {
    int c = Serial.read();
    lastRxMs = millis();
    if (c == '\r' || c == '\n') {
      bool secondOfPair = c == '\n' && lastWasCR;
      lastWasCR = c == '\r';
      if (!secondOfPair) submitLine();
      continue;
    }
    lastWasCR = false;
    if (c == 8 || c == 127) {
      if (lineLen > 0) lineLen--;
      continue;
    }
    if (c < 32 || c > 126) continue;
    if (lineLen < LINE_CAPACITY) lineBuf[lineLen++] = (char)c;
    else lineOverflow = true;
  }
  // Text that never gets its Enter is dropped rather than left to be joined
  // onto whatever is typed next.
  if ((lineLen > 0 || lineOverflow) && millis() - lastRxMs >= STALE_INPUT_MS) {
    lineLen = 0;
    lineOverflow = false;
    eventLine();
    Serial.println(F("(no Enter received - input dropped)"));
    Serial.println(F("(set the Serial Monitor line ending to Newline)"));
    prompt();
  }
}

// ------------------------------------------------------------------ setup

void setup() {
  Serial.begin(BAUD);
  txNeed = min(Serial.availableForWrite(), 63);

  bool loaded = loadSettings();
  if (!loaded) setDefaults();
  attachServo();
  lastTickMs = millis();

  Serial.println();
  Serial.println(F("Curtain servo console - servo on pin 6, stopped"));
  Serial.println(loaded ? F("Settings loaded from EEPROM") : F("Using default settings"));
  Serial.println(F("Type help and press Enter. Enter on its own stops."));
  prompt();
}

void loop() {
  readSerial();
  motionTick();
  outputTick();
}
