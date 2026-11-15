from datetime import datetime, timezone
from queue import Queue
import unittest
from unittest.mock import patch

from arduino import ArduinoClient, ArduinoControl, parse_arduino_control, parse_arduino_report


class ArduinoParseTests(unittest.TestCase):
    def test_legacy_control(self):
        self.assertEqual(parse_arduino_control("CTRL TRIGGER sent=3 total=500"),
                         ArduinoControl("TRIGGER", 3, 500))
        self.assertEqual(parse_arduino_control("CTRL ERROR FAULT_LOCKED"),
                         ArduinoControl("ERROR", error="FAULT_LOCKED"))
        self.assertEqual(parse_arduino_control("CTRL FAULT_CLEARED"),
                         ArduinoControl("FAULT_CLEARED"))

    def test_control_extra(self):
        examples = {
            "CTRL TRIGGER sent=1 total=5 t_ms=4294967295": {"t_ms": 4294967295},
            "CTRL CYCLE_END sent=2 total=5 rad_on=1 ms=1234": {"rad_on": 1, "ms": 1234},
            "CTRL NO_RESPONSE sent=3 total=5 rad_on=0 ms=3001": {"rad_on": 0, "ms": 3001},
            "CTRL READY_RETURN_TIMEOUT sent=4 total=5 rad_on=1 ms=300050": {"rad_on": 1, "ms": 300050},
            "CTRL SUMMARY sent=5 total=5 no_response=1 rad_on_cycles=4": {
                "no_response": 1, "rad_on_cycles": 4,
            },
        }
        for line, extra in examples.items():
            with self.subTest(line=line):
                self.assertEqual(parse_arduino_control(line).extra, extra)

    def test_invalid_control(self):
        for line in (
            "CTRL TRIGGER sent=2 total=1",
            "CTRL TRIGGER sent=0 total=4294967296",
            "CTRL TRIGGER sent=1 total=2 t_ms=4294967296",
            "CTRL CYCLE_END sent=1 total=2 rad_on=2",
            "CTRL CYCLE_END sent=1 total=2 ms=-1",
            "CTRL CYCLE_END sent=1 total=2 ms=1 ms=1",
            "CTRL CYCLE_END sent=1 total=2 ms=1 total=9",
            "CTRL CYCLE_END sent=1 total=2 " + "ms=1 " * 400,
            "CTRL ERROR bad_error",
        ):
            with self.subTest(line=line[:100]):
                self.assertIsNone(parse_arduino_control(line))

    def test_gpio_status_uses_supplied_receipt_time(self):
        timestamp = datetime(2026, 11, 15, tzinfo=timezone.utc)
        status = b"t_ms=18 event=RAD_ON seq=5 READY=0 RAD_ON=1 FAULT=0 dropped=0 matrix=1"
        report = parse_arduino_report(status, received_at=timestamp, received_ns=123)
        self.assertEqual((report.uptime_ms, report.sequence, report.event), (18, 5, "RAD_ON"))
        self.assertEqual((report.ready, report.rad_on, report.fault, report.matrix), (False, True, False, True))
        self.assertEqual((report.received_at, report.received_ns), (timestamp, 123))
        self.assertIsNone(parse_arduino_report(status + b" RAD_ON=0"))
        self.assertIsNone(parse_arduino_report(status.replace(b"seq=5", b"seq=4294967296")))

    def test_serial_receipt_uses_chunk_with_end_of_line(self):
        notices = []
        client = ArduinoClient("COM4", lambda _, line: notices.append(line))

        class Connection:
            in_waiting = 128
            chunks = iter((
                b"CTRL TRIGGER sent=1 total=1 ",
                b"t_ms=8\r\nt_ms=9 event=READY seq=2 READY=0 RAD_ON=0 FAULT=0 dropped=0 matrix=1\n",
                b"",
            ))

            def read(self, limit):
                chunk = next(self.chunks)
                if not chunk:
                    client._stop.set()
                return chunk

        with patch("arduino.time.perf_counter_ns", side_effect=(10, 20)):
            client._serve(Connection(), Queue())
        control, status = notices
        self.assertEqual((control.received_ns, status.received_ns), (20, 20))
        self.assertEqual(status.report.received_ns, status.received_ns)
        self.assertEqual(status.report.received_at, status.at)
        self.assertEqual(parse_arduino_control(control.text).extra, {"t_ms": 8})
