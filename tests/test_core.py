import json
import unittest
from datetime import datetime, timezone

from core import ListenerModel, ResultNotice, parse_device_json
from device_status import DeviceStatus, classify_stop
from log_format import bounded_line


class ListenerModelTests(unittest.TestCase):
    def setUp(self):
        self.model = ListenerModel(max_records=2, max_seen=3)
        self.model.begin_session("device-A")
        self.at = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)

    def result(self, test_id, *, final=True, day="2026-11-12", daily=None, reading=5):
        return {
            "commandId": 403,
            "id": 206,
            "params": {"result": {
                "analysis": {"testId": test_id, "final": final, "testDateTime": f"{day} 13:00:00.000",
                             "dailyId": daily, "tidName": "123"},
                "chemistry": [{"elementName": "Fe", "concentration": reading}],
            }},
        }

    def send(self, test_id, **kwargs):
        return self.model.process(self.result(test_id, **kwargs), 100, self.at)

    def test_numeric_chain_ignores_intermediate_and_duplicate_notices(self):
        self.assertEqual(self.send(1), ResultNotice("1", True, "first"))
        self.assertEqual(self.send(2, final=False), ResultNotice("2", False))
        self.assertEqual(self.send(2), ResultNotice("2", True, "consecutive", 1))
        self.assertEqual(self.send(2), ResultNotice("2", True, "duplicate"))
        self.assertEqual(self.send(6), ResultNotice("6", True, "gap", 4))
        self.assertEqual(self.send(4), ResultNotice("4", True, "backward", -2))
        self.assertEqual(self.send("06"), ResultNotice("06", True, "repeated_id", 0))
        self.assertEqual(self.send(7), ResultNotice("7", True, "consecutive", 1))

    def test_result_error_is_kept_on_a_final_result(self):
        message = self.result(2014)
        message["params"]["result"]["analysis"].update(
            statusId=-2998, testErrorInfo="Exposure start failed. ")
        notice = self.model.process(message, 100, self.at)
        self.assertTrue(notice.is_final)
        self.assertEqual(notice.result_error, "statusId=-2998 · Exposure start failed.")

    def test_reconnect_and_reset_have_different_effects(self):
        self.send(1)
        self.send(2)
        self.model.begin_session("device-A")
        self.send(2)
        self.assertEqual(self.send(5), ResultNotice("5", True, "gap_after_reconnect", 3))
        self.assertEqual(self.send(7), ResultNotice("7", True, "gap", 2))
        self.model.begin_session("device-B")
        self.assertEqual(self.send(5).id_status, "first")
        self.model.reset_test_id_sequence()
        self.assertEqual(self.send(6).id_status, "first")

    def test_conflict_marks_original_and_trims_payload_history(self):
        self.send(1)
        self.assertEqual(self.send(1, reading=6).id_status, "conflict")
        self.assertTrue(self.model.records[0].issues)
        self.assertEqual(self.model.records[0].elements[0].concentration, 5)
        self.send(2)
        self.send(3)
        self.assertEqual([r.test_id for r in self.model.records], ["2", "3"])
        self.assertEqual(self.send(1, reading=6).id_status, "conflict")
        self.assertTrue(all(isinstance(value[0], bytes) and type(value[1]) is int
                            for value in self.model._seen.values()))
        self.send(4)
        self.assertEqual(len(self.model._seen), 3)

    def test_missing_numeric_id_clears_continuity(self):
        self.send(1)
        self.assertEqual(self.send(None).id_status, "missing_id")
        self.assertEqual(self.send(4).id_status, "first")
        self.assertEqual(self.send("label").id_status, "invalid_id")
        self.assertEqual(self.send(8).id_status, "first")

    def test_daily_id_uses_positive_integer_and_device_date(self):
        self.assertEqual(self.send(1, daily=20).daily_id_status, "first")
        notice = self.send(2, daily=23)
        self.assertEqual((notice.id_status, notice.daily_id_num, notice.daily_id_status, notice.daily_id_delta),
                         ("consecutive", 23, "gap", 3))
        self.assertTrue(self.model.records[-1].issues)
        self.assertEqual(self.send(3, day="2026-11-13", daily=1).daily_id_status, "daily_reset")
        for value in (-1, 0, True, "2"):
            with self.subTest(daily=value):
                notice = self.send(None, daily=value)
                self.assertIsNone(notice.daily_id_num)
                self.assertIsNone(notice.daily_id_status)
        self.assertEqual(self.send(5, day="2026-11-13", daily=8).daily_id_status, "first")

    def test_nonfinite_result_can_be_logged_as_standard_json(self):
        raw = json.dumps(self.result(1, reading=float("nan")))
        message, nonfinite = parse_device_json(raw)
        self.assertTrue(nonfinite)
        self.assertTrue(self.model.process(message, 100, self.at, nonfinite=nonfinite).is_final)
        record = self.model.records[0]
        self.assertEqual(record.elements[0].concentration, "NaN")
        self.assertTrue(any("NaN" in issue for issue in record.issues))
        json.dumps(message, allow_nan=False)
        values, nonfinite = parse_device_json("[1e999,-1e999,Infinity,-Infinity,0.25]")
        self.assertTrue(nonfinite)
        self.assertEqual(values, ["Infinity", "-Infinity", "Infinity", "-Infinity", 0.25])
        self.assertEqual(parse_device_json('{"reading":"NaN"}'), ({"reading": "NaN"}, False))

    def test_escaped_surrogate_does_not_break_fingerprint_or_display(self):
        message, nonfinite = parse_device_json(json.dumps(self.result(1, reading="\ud800")))
        notice = self.model.process(message, 100, self.at, nonfinite=nonfinite)
        self.assertTrue(notice.is_final)
        self.assertEqual(bounded_line(self.model.records[0].elements[0].concentration), r"\ud800")


class DeviceStatusTests(unittest.TestCase):
    def test_stop_reasons_match_recorded_201_codes(self):
        for reason, code, expected in [
            (" Test Complete ", 0, "complete"), ("Proximity Failure", 6, "proximity"),
            ("User Abort", 2, "stopped"), ("User Abort", 0, "unknown"),
            ("Time Elapsed", None, "unknown"), ("unseen reason", 0, "unknown"),
            ("", False, "unknown"), (None, 0, "complete"), ("User Abort", None, "stopped"),
        ]:
            with self.subTest(reason=reason, code=code):
                self.assertEqual(classify_stop(reason, code), expected)

    def test_diagnostics_do_not_change_measurement_phase(self):
        status = DeviceStatus()
        status.notification(200, {})
        phase = status.phase
        self.assertIn("START", status.notification(702, {}))
        self.assertIn("IO", status.notification(139, {"state": 3}))
        self.assertIn("2 行", status.notification(701, {"messages": ["first", "second"]}))
        self.assertEqual(status.phase, phase)
