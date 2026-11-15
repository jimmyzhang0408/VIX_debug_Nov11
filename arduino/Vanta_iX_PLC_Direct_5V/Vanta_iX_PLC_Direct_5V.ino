#include <Arduino_LED_Matrix.h>
#include <stdio.h>
#include <string.h>

constexpr uint8_t kReadyPin = 2;
constexpr uint8_t kRadOnPin = 3;
constexpr uint8_t kStartDrivePin = 4;  // Sink START to GND or release it as an input.
constexpr uint8_t kFaultPin = 8;  // P304 uses IRQ9 on UNO R4 WiFi.
constexpr uint8_t kReady = 0x01;
constexpr uint8_t kRadOn = 0x02;
constexpr uint8_t kFault = 0x04;
constexpr uint8_t kQueueSize = 64;
constexpr uint32_t kReportIntervalMs = 1000;
constexpr uint32_t kFaultBlinkHalfPeriodMs = 500;
constexpr uint32_t kReadyHoldMs = 2000;
constexpr uint32_t kStartPulseMs = 100;
constexpr uint32_t kDoubleStartShortGapMs = 500;
constexpr uint32_t kDoubleStartDefaultGapMs = 1000;

// The first word contains the top row. The last bit is the lower right pixel.
constexpr uint32_t kRadOnRow = 0xFFF00000;
constexpr uint32_t kFaultPixel = 0x00000001;

struct StatusRecord {
  uint32_t timeMs;
  uint32_t sequence;
  uint32_t dropped;
  uint8_t active;
  uint8_t changed;
};

enum class CyclePhase : uint8_t {
  Idle, WaitReady, HoldReady, Pulse, WaitReturn,
  DoubleFirstPulse, DoubleGap, DoubleSecondPulse,
};

struct TriggerCycle {
  volatile CyclePhase phase = CyclePhase::Idle;
  uint32_t requested = 0;
  uint32_t sent = 0;
  uint32_t phaseSince = 0;
  uint32_t inputRevision = 0;
  uint32_t readyDropsAtStart = 0;
  uint32_t doubleGapMs = 0;
};

struct InputSample {
  uint8_t active;
  bool faultLocked;
  uint32_t revision;
  uint32_t readyDrops;
  uint32_t timeMs;
};

ArduinoLEDMatrix matrix;
bool matrixStarted = false;
uint8_t displayedState = 0xFF;
uint32_t lastReportMs = 0;

volatile StatusRecord changes[kQueueSize];
volatile uint8_t readIndex = 0;
volatile uint8_t writeIndex = 0;
volatile uint8_t inputState = 0;
volatile uint32_t faultOnMs = 0;
volatile uint32_t sequence = 0;
volatile uint32_t droppedChanges = 0;
volatile uint32_t inputRevision = 0;
volatile uint32_t readyDrops = 0;
volatile bool faultLocked = false;

TriggerCycle cycle;
bool faultReported = false;
char commandBuffer[40];
size_t commandLength = 0;
bool discardCommand = false;

// Call from an input interrupt or with interrupts disabled.
void captureLevel(uint8_t signal, bool active) {
  if (active == ((inputState & signal) != 0)) {
    return;
  }

  const uint32_t now = millis();
  inputState ^= signal;
  if (signal == kReady && !active) {
    ++readyDrops;
  }
  if (signal == kFault && active) {
    faultOnMs = now;
  }
  ++sequence;
  const uint8_t next = (writeIndex + 1) % kQueueSize;
  if (next == readIndex) {
    ++droppedChanges;
    return;
  }

  volatile StatusRecord& record = changes[writeIndex];
  record.timeMs = now;
  record.sequence = sequence;
  record.dropped = droppedChanges;
  record.active = inputState;
  record.changed = signal;
  writeIndex = next;
}

void onReadyChange() {
  ++inputRevision;
  captureLevel(kReady, digitalRead(kReadyPin) == LOW);
}

void onRadOnChange() {
  ++inputRevision;
  captureLevel(kRadOn, digitalRead(kRadOnPin) == LOW);
}

void releaseStart() {
  pinMode(kStartDrivePin, INPUT);
}

void driveStartLow() {
  digitalWrite(kStartDrivePin, LOW);
  pinMode(kStartDrivePin, OUTPUT);
}

bool doubleStartActive(CyclePhase phase) {
  return phase == CyclePhase::DoubleFirstPulse || phase == CyclePhase::DoubleGap ||
         phase == CyclePhase::DoubleSecondPulse;
}

void latchFault() {
  faultLocked = true;
  if (!doubleStartActive(cycle.phase)) {
    releaseStart();
  }
  captureLevel(kFault, true);
}

void onFaultAsserted() {
  // The falling edge itself is evidence of a fault, even if the line cleared.
  latchFault();
}

InputSample sampleInputs() {
  noInterrupts();
  const bool faultActive = digitalRead(kFaultPin) == LOW;
  if (faultActive && !faultLocked) {
    latchFault();
  } else {
    captureLevel(kFault, faultActive);
  }
  const InputSample sample = {inputState, faultLocked, inputRevision, readyDrops, millis()};
  interrupts();
  return sample;
}

uint8_t readInputLevels() {
  return (digitalRead(kReadyPin) == LOW ? kReady : 0) |
         (digitalRead(kRadOnPin) == LOW ? kRadOn : 0) |
         (digitalRead(kFaultPin) == LOW ? kFault : 0);
}

bool assertStart(const InputSample& sample) {
  noInterrupts();
  const bool eligible = !faultLocked && inputRevision == sample.revision &&
                        readInputLevels() == kReady;
  if (eligible) {
    driveStartLow();
  }
  interrupts();
  return eligible;
}

void printCycle(const char* event) {
  char line[80];
  const int length = snprintf(line, sizeof(line), "CTRL %s sent=%lu total=%lu\r\n", event,
                              static_cast<unsigned long>(cycle.sent),
                              static_cast<unsigned long>(cycle.requested));
  if (length > 0 && static_cast<size_t>(length) < sizeof(line)) {
    Serial.write(reinterpret_cast<uint8_t*>(line), static_cast<size_t>(length));
  }
}

void endCycle(const char* event) {
  releaseStart();
  cycle.phase = CyclePhase::Idle;
  printCycle(event);
}

void beginReadyHold(const InputSample& sample) {
  cycle.phase = CyclePhase::HoldReady;
  cycle.phaseSince = sample.timeMs;
  cycle.inputRevision = sample.revision;
  printCycle("READY_HOLD");
}

void updateDoubleStart(uint32_t now) {
  const uint32_t elapsed = now - cycle.phaseSince;
  switch (cycle.phase) {
    case CyclePhase::DoubleFirstPulse:
      if (elapsed >= kStartPulseMs) {
        releaseStart();
        cycle.phaseSince = millis();
        cycle.phase = CyclePhase::DoubleGap;
        printCycle("DOUBLE_GAP");
      }
      break;
    case CyclePhase::DoubleGap:
      if (elapsed >= cycle.doubleGapMs) {
        driveStartLow();
        cycle.phaseSince = millis();
        cycle.phase = CyclePhase::DoubleSecondPulse;
        ++cycle.sent;
        printCycle("DOUBLE_SECOND");
      }
      break;
    case CyclePhase::DoubleSecondPulse:
      if (elapsed >= kStartPulseMs) {
        endCycle("DOUBLE_DONE");
      }
      break;
    default:
      break;
  }
}

void updateCycle() {
  const InputSample sample = sampleInputs();
  if (doubleStartActive(cycle.phase)) {
    updateDoubleStart(sample.timeMs);
    return;
  }
  if (sample.faultLocked) {
    if (cycle.phase != CyclePhase::Idle) {
      endCycle("FAULT_STOPPED");
      faultReported = true;
    } else if (!faultReported) {
      printCycle("FAULT_LOCKED");
      faultReported = true;
    }
    return;
  }

  const bool eligible = (sample.active & (kReady | kRadOn | kFault)) == kReady;
  switch (cycle.phase) {
    case CyclePhase::Idle:
      break;
    case CyclePhase::WaitReady:
      if (eligible) {
        beginReadyHold(sample);
      }
      break;
    case CyclePhase::HoldReady:
      if (!eligible || sample.revision != cycle.inputRevision) {
        cycle.phase = CyclePhase::WaitReady;
        printCycle("WAIT_READY");
        break;
      }
      if (sample.timeMs - cycle.phaseSince >= kReadyHoldMs) {
        if (!assertStart(sample)) {
          cycle.phase = CyclePhase::WaitReady;
          break;
        }
        cycle.phaseSince = millis();
        cycle.readyDropsAtStart = sample.readyDrops;
        cycle.phase = CyclePhase::Pulse;
        ++cycle.sent;
        printCycle("TRIGGER");
      }
      break;
    case CyclePhase::Pulse:
      if (sample.timeMs - cycle.phaseSince >= kStartPulseMs) {
        releaseStart();
        cycle.phase = CyclePhase::WaitReturn;
        printCycle("WAIT_READY_RETURN");
      }
      break;
    case CyclePhase::WaitReturn:
      // A new READY withdrawal must follow this pulse before the next one.
      if (sample.readyDrops == cycle.readyDropsAtStart || !eligible) {
        break;
      }
      if (cycle.sent == cycle.requested) {
        endCycle("DONE");
      } else {
        beginReadyHold(sample);
      }
      break;
    default:
      break;
  }
}

bool readCount(const char* text, uint32_t& count) {
  if (text == nullptr) {
    count = 1;
    return true;
  }
  count = 0;
  for (; *text != '\0'; ++text) {
    if (*text < '0' || *text > '9') {
      return false;
    }
    const uint32_t digit = *text - '0';
    if (count > (UINT32_MAX - digit) / 10) {
      return false;
    }
    count = count * 10 + digit;
  }
  return count > 0;
}

void clearFaultLock() {
  if (doubleStartActive(cycle.phase)) {
    Serial.println("CTRL ERROR CYCLE_ACTIVE");
    return;
  }
  noInterrupts();
  const bool asserted = digitalRead(kFaultPin) == LOW;
  const bool wasLocked = faultLocked;
  if (asserted) {
    latchFault();
  } else if (wasLocked) {
    // Cancel an old cycle even if the fault arrived after the last loop tick.
    releaseStart();
    cycle.phase = CyclePhase::Idle;
    faultLocked = false;
    faultReported = false;
  }
  interrupts();
  if (asserted) {
    Serial.println("CTRL ERROR FAULT_ACTIVE");
  } else if (wasLocked) {
    Serial.println("CTRL FAULT_CLEARED");
  } else {
    Serial.println("CTRL NO_FAULT_LOCK");
  }
}

char* nextWord(char*& cursor) {
  cursor += strspn(cursor, " \t");
  if (*cursor == '\0') {
    return nullptr;
  }
  char* word = cursor;
  cursor += strcspn(cursor, " \t");
  if (*cursor != '\0') {
    *cursor = '\0';
    ++cursor;
  }
  return word;
}

void requestCycle(uint32_t count) {
  if (sampleInputs().faultLocked) {
    Serial.println("CTRL ERROR FAULT_LOCKED");
  } else if (cycle.phase != CyclePhase::Idle) {
    Serial.println("CTRL ERROR CYCLE_ACTIVE");
  } else {
    cycle = TriggerCycle{};
    cycle.requested = count;
    cycle.phase = CyclePhase::WaitReady;
    printCycle("WAIT_READY");
  }
}

void requestDoubleStart(uint32_t gapMs) {
  if (cycle.phase != CyclePhase::Idle) {
    Serial.println("CTRL ERROR CYCLE_ACTIVE");
    return;
  }
  cycle = TriggerCycle{};
  cycle.requested = 2;
  cycle.doubleGapMs = gapMs;
  cycle.phase = CyclePhase::DoubleFirstPulse;
  driveStartLow();
  cycle.phaseSince = millis();
  cycle.sent = 1;
  printCycle("DOUBLE_FIRST");
}

void handleCommand(char* line) {
  const char* verb = nextWord(line);
  if (verb == nullptr) {
    return;
  }
  const char* argument = nextWord(line);
  const char* gap = nextWord(line);
  if (nextWord(line) != nullptr) {
    Serial.println("CTRL ERROR INVALID_COMMAND");
    return;
  }
  if (strcmp(verb, "DOUBLE") == 0 && argument != nullptr && strcmp(argument, "START") == 0) {
    if (gap == nullptr || strcmp(gap, "1") == 0) {
      requestDoubleStart(kDoubleStartDefaultGapMs);
    } else if (strcmp(gap, "0.5") == 0) {
      requestDoubleStart(kDoubleStartShortGapMs);
    } else {
      Serial.println("CTRL ERROR INVALID_DOUBLE_GAP");
    }
  } else if (gap != nullptr) {
    Serial.println("CTRL ERROR INVALID_COMMAND");
  } else if (strcmp(verb, "START") == 0) {
    uint32_t count;
    if (!readCount(argument, count)) {
      Serial.println("CTRL ERROR INVALID_COUNT");
    } else {
      requestCycle(count);
    }
  } else if (strcmp(verb, "STOP") == 0 && argument == nullptr) {
    endCycle("STOPPED");
  } else if (strcmp(verb, "CLEAR") == 0 && argument != nullptr && strcmp(argument, "FAULT") == 0) {
    clearFaultLock();
  } else {
    Serial.println("CTRL ERROR INVALID_COMMAND");
  }
}

void readCommand() {
  // Limit work per loop so command input cannot delay a trigger release.
  for (uint8_t i = 0; i < 32 && Serial.available() > 0; ++i) {
    const int value = Serial.read();
    if (value == '\r' || value == '\n') {
      if (discardCommand) {
        Serial.println("CTRL ERROR INVALID_COMMAND");
      } else if (commandLength != 0) {
        commandBuffer[commandLength] = '\0';
        handleCommand(commandBuffer);
      }
      commandLength = 0;
      discardCommand = false;
      return;
    }
    if (discardCommand) {
      continue;
    }
    if ((value != '\t' && (value < ' ' || value > '~')) ||
        commandLength == sizeof(commandBuffer) - 1) {
      discardCommand = true;
    } else {
      const int uppercase = value >= 'a' && value <= 'z' ? value - 'a' + 'A' : value;
      commandBuffer[commandLength++] = static_cast<char>(uppercase);
    }
  }
}

void updateIndicators() {
  noInterrupts();
  const uint8_t active = inputState;
  const uint32_t faultStart = faultOnMs;
  interrupts();

  const uint32_t faultElapsed = millis() - faultStart;
  const bool faultLit = (active & kFault) != 0 &&
                        (faultElapsed / kFaultBlinkHalfPeriodMs) % 2 == 0;
  const uint8_t display = (active & (kReady | kRadOn)) | (faultLit ? kFault : 0);
  if (display == displayedState) {
    return;
  }
  digitalWrite(LED_BUILTIN, (display & kReady) ? HIGH : LOW);
  if (matrixStarted) {
    const uint32_t frame[3] = {
        (display & kRadOn) ? kRadOnRow : 0,
        0,
        (display & kFault) ? kFaultPixel : 0,
    };
    matrix.loadFrame(frame);
  }
  displayedState = display;
}

void printStatus(const char* event, const StatusRecord& record) {
  char line[112];
  const int length = snprintf(
      line, sizeof(line),
      "t_ms=%lu event=%s seq=%lu READY=%d RAD_ON=%d FAULT=%d dropped=%lu matrix=%d\r\n",
      static_cast<unsigned long>(record.timeMs), event,
      static_cast<unsigned long>(record.sequence), (record.active & kReady) != 0,
      (record.active & kRadOn) != 0, (record.active & kFault) != 0,
      static_cast<unsigned long>(record.dropped), matrixStarted);
  if (length > 0 && static_cast<size_t>(length) < sizeof(line)) {
    Serial.write(reinterpret_cast<uint8_t*>(line), static_cast<size_t>(length));
  }
  lastReportMs = record.timeMs;
}

bool nextRecord(StatusRecord& record) {
  // Copy the record before the interrupt handlers can change the queue.
  noInterrupts();
  const uint32_t now = millis();
  bool available = true;
  if (readIndex != writeIndex) {
    const volatile StatusRecord& queued = changes[readIndex];
    record = {queued.timeMs, queued.sequence, queued.dropped, queued.active, queued.changed};
    readIndex = (readIndex + 1) % kQueueSize;
  } else if (now - lastReportMs >= kReportIntervalMs) {
    record = {now, sequence, droppedChanges, inputState, 0};
  } else {
    available = false;
  }
  interrupts();
  return available;
}

void setup() {
  releaseStart();
  pinMode(kReadyPin, INPUT_PULLUP);
  pinMode(kRadOnPin, INPUT_PULLUP);
  pinMode(kFaultPin, INPUT_PULLUP);
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
  Serial.begin(115200);
  matrixStarted = matrix.begin();

  noInterrupts();
  attachInterrupt(digitalPinToInterrupt(kReadyPin), onReadyChange, CHANGE);
  attachInterrupt(digitalPinToInterrupt(kRadOnPin), onRadOnChange, CHANGE);
  attachInterrupt(digitalPinToInterrupt(kFaultPin), onFaultAsserted, FALLING);
  inputState = readInputLevels();
  faultOnMs = millis();
  faultLocked = (inputState & kFault) != 0;
  const StatusRecord initial = {faultOnMs, 0, 0, inputState, 0};
  interrupts();

  updateIndicators();
  printStatus("BOOT", initial);
}

void loop() {
  readCommand();
  updateCycle();
  updateIndicators();

  StatusRecord record;
  if (!nextRecord(record)) {
    return;
  }

  const char* event = "STATE";
  if (record.changed == kReady) {
    event = "READY";
  } else if (record.changed == kRadOn) {
    event = "RAD_ON";
  } else if (record.changed == kFault) {
    event = "FAULT";
  }
  printStatus(event, record);
}
