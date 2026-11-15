"""Check that receipt, export and run summaries remain separately observable."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import parse_device_json
from journal import AsyncJournal


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.log = self.root / "logs" / "listener_test.jsonl"
        self.writer = AsyncJournal(self.log, result_dir=self.root / "results",
                                   summary_dir=self.root / "summaries")
        self.addCleanup(self.writer.close)

    def rows(self):
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def submit(self, entry):
        self.assertTrue(self.writer.submit(entry))

    def test_export_keeps_first_result_and_journals_conflicts(self):
        entry = {"kind": "api_result", "id": 206, "testID": "123", "isFinal": True,
                 "message": {"params": {"result": {"analysis": {"final": True}}}}}
        self.submit(entry)
        self.submit(entry)
        self.submit({**entry, "message": {"params": {"result": {"value": 1}}}})
        self.submit({**entry, "testID": "../123"})
        self.submit({"kind": "round_summary", "summaryNo": 1, "evidenceComplete": True})
        self.assertTrue(self.writer.flush())
        rows = self.rows()
        self.assertEqual([row["export"]["status"] for row in rows[:-1]],
                         ["saved", "already_saved", "conflict", "invalid_id"])
        self.assertEqual(json.loads((self.root / "results/123.json").read_text(encoding="utf-8")),
                         entry["message"])
        summary = json.loads(next((self.root / "summaries").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(summary, rows[-1])
        self.assertEqual(summary["exportIssues"], 2)
        self.assertEqual(summary["journalFailures"], 0)

    def test_nonfinite_and_unicode_can_be_recorded_as_standard_json(self):
        message, nonfinite = parse_device_json(r'{"concentration":NaN,"label":"\ud800"}')
        self.assertTrue(nonfinite)
        self.submit({"id": 206, "isFinal": True, "testID": "124",
                     "message": message, "nonFinite": True})
        self.assertTrue(self.writer.flush())
        self.assertEqual(self.rows()[0]["message"], message)
        payload = json.loads((self.root / "results/124.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["concentration"], "NaN")

    def test_journal_failure_marks_the_next_summary_as_incomplete(self):
        with patch.object(self.writer, "_write_entry", side_effect=OSError("simulated disk error")):
            self.submit({"kind": "api_other"})
            self.assertFalse(self.writer.flush())
        self.submit({"kind": "round_summary", "summaryNo": 2, "evidenceComplete": True})
        self.assertFalse(self.writer.flush())
        summary = self.rows()[0]
        self.assertFalse(summary["evidenceComplete"])
        self.assertEqual(summary["journalFailures"], 1)
