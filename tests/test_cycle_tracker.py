import unittest

from core import ResultNotice
from cycle_tracker import CycleTracker, Outcome


NS = 1_000_000_000
COMPLETE = {"stopReason": "Test Complete", "stopReasonInt": 0}
PROXIMITY = {"stopReason": "Proximity Failure", "stopReasonInt": 6}
ABORT = {"stopReason": "User Abort", "stopReasonInt": 2}


class CycleTrackerTests(unittest.TestCase):
    def setUp(self):
        self.closed = []
        self.tracker = CycleTracker(self.closed.append)
        self.tracker.on_connect(0)
        self.tracker.on_connect(0, "arduino")
        self.tracker.on_gpio(True, False, 0)

    def begin(self, sent=1, at=0):
        self.tracker.on_trigger(sent, at)
        self.tracker.on_api(200, {}, at + NS // 8)

    def result(self, test_id, at, *, final=True, key=None, status=None):
        self.tracker.on_result(ResultNotice(str(test_id), final, status), at, result_key=key)

    def test_normal_final_before_stop(self):
        self.begin()
        self.result(10, NS // 2, final=False, key="one")
        self.result(10, NS, key="one")
        self.tracker.on_api(201, COMPLETE, 2 * NS)
        record, = self.closed
        self.assertEqual(record.outcome, Outcome.NORMAL)
        self.assertEqual(record.intermediate_206, 1)
        self.assertEqual(record.to_entry()["t_201_to_final_ms"], -1000)

    def test_normal_final_after_stop(self):
        self.begin()
        self.tracker.on_api(201, COMPLETE, NS)
        self.result(10, 2 * NS, key="one")
        self.assertEqual(self.closed[0].outcome, Outcome.NORMAL)

    def test_proximity_followed_by_reuse_of_provisional_id(self):
        self.begin()
        self.result(1660, NS // 2, final=False, key="empty")
        self.tracker.on_api(201, PROXIMITY, NS)
        self.begin(2, 2 * NS)
        self.result(1660, 3 * NS, final=False, key="new")
        self.tracker.on_api(201, COMPLETE, 4 * NS)
        self.result(1660, 5 * NS, key="new")
        self.tracker.tick(6 * NS)
        by_sequence = {c.no: c for c in self.closed}
        self.assertEqual(by_sequence[1].outcome, Outcome.EMPTY_SHOT)
        self.assertEqual(by_sequence[2].outcome, Outcome.NORMAL)

    def test_proximity_with_final_is_abnormal(self):
        self.begin()
        self.result(1568, NS // 2, key="stopped")
        self.tracker.on_api(201, PROXIMITY, NS)
        record, = self.closed
        self.assertEqual(record.outcome, Outcome.ABNORMAL_STOP)
        self.assertEqual(record.test_id, "1568")
        self.assertEqual(record.final_206_ns, NS // 2)

    def test_user_abort_without_double(self):
        self.begin()
        self.tracker.on_api(201, ABORT, NS)
        self.tracker.tick(5 * NS)
        self.assertEqual(self.closed[0].outcome, Outcome.ABNORMAL_STOP)

    def test_device_key_notifications_can_show_double_start_without_final(self):
        self.tracker.on_api(704, {"keyActivated": 6}, NS)
        self.tracker.on_api(200, {}, NS)
        self.tracker.on_api(704, {"keyActivated": 7}, NS + 50_000_000)
        self.tracker.on_api(704, {"keyActivated": 6}, NS + 285_000_000)
        self.tracker.on_api(201, ABORT, 2 * NS)
        self.tracker.tick(5 * NS)
        record, = self.closed
        self.assertEqual(record.outcome, Outcome.DOUBLE_START_STOP)
        self.assertIsNone(record.final_206_ns)
        self.assertTrue(record.unsolicited)
        self.assertTrue(record.to_entry()["doubleSecond"])

    def test_duplicate_device_press_is_not_double_start(self):
        self.tracker.on_api(704, {"keyActivated": 6}, NS)
        self.tracker.on_api(200, {}, NS)
        self.tracker.on_api(704, {"keyActivated": 6}, NS + 50_000_000)
        self.tracker.on_api(201, ABORT, 2 * NS)
        self.tracker.tick(5 * NS)
        self.assertEqual(self.closed[0].outcome, Outcome.ABNORMAL_STOP)

    def test_double_stop_with_final(self):
        self.tracker.on_double_first(0)
        self.tracker.on_api(200, {}, NS // 8)
        self.tracker.on_double_second(NS // 2)
        self.tracker.on_api(201, ABORT, NS)
        self.result(1280, NS + NS // 4, key="stopped")
        record, = self.closed
        self.assertEqual(self.tracker.triggers, 2)
        self.assertEqual(record.outcome, Outcome.DOUBLE_START_STOP)
        self.assertEqual(record.test_id, "1280")

    def test_second_pulse_after_first_stop_starts_own_cycle(self):
        self.tracker.on_double_first(0)
        self.tracker.on_api(200, {}, NS // 8)
        self.result(10, NS // 4, key="first")
        self.tracker.on_api(201, COMPLETE, NS // 2)
        self.tracker.on_double_second(NS)
        self.tracker.on_api(200, {}, 2 * NS)
        self.result(11, 3 * NS, key="second")
        self.tracker.on_api(201, COMPLETE, 4 * NS)
        self.assertEqual([c.outcome for c in self.closed], [Outcome.NORMAL] * 2)
        self.assertEqual([c.trigger_no for c in self.closed], [1, 2])

    def test_missing_206_requires_complete_stop(self):
        self.begin()
        self.tracker.on_api(201, COMPLETE, NS)
        self.tracker.tick(6 * NS)
        self.assertEqual(self.closed[0].outcome, Outcome.NO_RESULT)

    def test_no_response_and_evidenced_start_without_200_are_distinct(self):
        self.tracker.on_trigger(1, 0)
        self.tracker.on_board_no_response(1, 3 * NS)
        self.tracker.tick(3 * NS)
        self.tracker.on_trigger(2, 4 * NS)
        self.tracker.on_api(704, {"keyActivated": 6}, 4 * NS + NS // 10)
        self.tracker.tick(9 * NS)
        self.assertEqual([c.outcome for c in self.closed], [Outcome.NO_RESPONSE, Outcome.INCONCLUSIVE])
        self.assertTrue(self.closed[0].board_no_response)

    def test_no_response_needs_both_capture_sources(self):
        self.tracker.on_disconnect(0, "arduino")
        self.tracker.on_trigger(1, NS)
        self.tracker.tick(4 * NS)
        self.assertEqual(self.closed[0].outcome, Outcome.INCONCLUSIVE)

    def test_activity_without_stop_cannot_be_classed_as_no_result(self):
        self.begin()
        self.result(10, NS // 2)
        self.tracker.on_api(209, {"reason": "exposure"}, NS)
        self.tracker.tick(181 * NS)
        self.assertEqual(self.closed[0].outcome, Outcome.INCONCLUSIVE)
        self.assertEqual(self.closed[0].ev209, [{"reason": "exposure"}])

    def test_exposure_without_200_is_inconclusive(self):
        self.tracker.on_trigger(1, 0)
        self.tracker.on_api(202, {}, NS // 4)
        self.tracker.tick(5 * NS)
        self.assertEqual(self.closed[0].outcome, Outcome.INCONCLUSIVE)

    def test_unknown_stop_even_with_final(self):
        self.begin()
        self.result(10, NS // 2)
        self.tracker.on_api(201, {"stopReason": "unexpected", "stopReasonInt": 400}, NS)
        self.assertEqual(self.closed[0].outcome, Outcome.UNKNOWN_STOP)

    def test_no_arduino_uses_unsolicited_but_can_check_missing_final(self):
        self.tracker.on_disconnect(0, "arduino")
        self.tracker.on_api(200, {}, NS)
        self.result(10, 2 * NS)
        self.tracker.on_api(201, COMPLETE, 3 * NS)
        self.tracker.on_api(200, {}, 4 * NS)
        self.tracker.on_api(201, COMPLETE, 5 * NS)
        self.tracker.tick(11 * NS)
        self.assertEqual([c.outcome for c in self.closed], [Outcome.UNSOLICITED, Outcome.NO_RESULT])
        self.assertTrue(all(c.unsolicited for c in self.closed))

    def test_disconnect_and_reset_close_pending(self):
        self.begin()
        self.tracker.on_disconnect(NS)
        self.tracker.on_connect(2 * NS)
        self.begin(2, 3 * NS)
        self.tracker.reset(5 * NS)
        self.assertEqual([c.outcome for c in self.closed], [Outcome.INCONCLUSIVE] * 2)
        self.assertTrue(self.closed[0].disconnected)
        self.assertEqual(self.tracker.triggers, 0)
        self.assertFalse(self.tracker.counts)
        self.assertFalse(self.tracker.open_cycles)

    def test_invalid_capture_downgrades_current_cycle(self):
        self.begin()
        self.tracker.on_invalid(NS, "rxNo 不连续")
        self.tracker.on_api(201, COMPLETE, 2 * NS)
        self.tracker.tick(7 * NS)
        self.assertEqual(self.closed[0].outcome, Outcome.INCONCLUSIVE)

    def test_known_late_result_does_not_fill_new_cycle(self):
        self.begin()
        self.result(10, NS // 2, final=False, key="old")
        self.tracker.on_api(201, COMPLETE, NS)
        self.tracker.tick(6 * NS)
        self.begin(2, 7 * NS)
        self.result(10, 8 * NS, key="old")
        self.tracker.on_api(201, COMPLETE, 9 * NS)
        self.result(11, 10 * NS, key="new")
        prior, orphan, current = self.closed
        self.assertEqual(prior.outcome, Outcome.NO_RESULT)
        self.assertEqual(orphan.outcome, Outcome.INCONCLUSIVE)
        self.assertEqual(current.outcome, Outcome.NORMAL)
        self.assertEqual(current.test_id, "11")

    def test_final_without_identity_fails_to_resolve_overlapping_envelopes(self):
        self.begin()
        self.tracker.on_api(201, COMPLETE, NS)
        self.begin(2, 2 * NS)
        self.result(10, 3 * NS, key="new identity")
        self.tracker.on_api(201, COMPLETE, 4 * NS)
        self.tracker.tick(10 * NS)
        self.assertEqual([c.outcome for c in self.closed], [Outcome.INCONCLUSIVE] * 3)

    def test_result_gap_counts_as_result_and_preserves_marker(self):
        self.begin()
        self.result(50, NS, status="gap")
        self.tracker.on_api(201, COMPLETE, 2 * NS)
        record, = self.closed
        self.assertEqual(record.outcome, Outcome.NORMAL)
        self.assertEqual(record.test_id_status, "gap")

    def ordered(self, test_id, at, status, delta, key):
        self.tracker.on_result(ResultNotice(str(test_id), True, status, delta), at, result_key=key)

    def test_id_jump_assigns_lost_result_to_earlier_cycle_while_both_wait(self):
        # Usual device order: final 206 first, then 201. Cycle 2's final is lost
        # and cycle 3's final arrives before cycle 2 reaches its deadline.
        self.begin(1, 0)
        self.ordered(1, NS, "first", None, "k1")
        self.tracker.on_api(201, COMPLETE, 2 * NS)
        self.begin(2, 5 * NS)
        self.tracker.on_api(201, COMPLETE, 8 * NS)
        self.begin(3, 10 * NS)
        self.ordered(3, 11 * NS, "gap", 2, "k3")
        self.tracker.on_api(201, COMPLETE, 12 * NS)
        self.tracker.tick(30 * NS)
        by_no = {c.no: c for c in self.closed}
        self.assertEqual([by_no[n].outcome for n in (1, 2, 3)],
                         [Outcome.NORMAL, Outcome.NO_RESULT, Outcome.NORMAL])
        self.assertEqual(by_no[3].test_id, "3")
        self.assertEqual(len(self.closed), 3)

    def test_id_jump_claims_cycle_already_closed_as_no_result(self):
        self.begin(1, 0)
        self.ordered(1, NS, "first", None, "k1")
        self.tracker.on_api(201, COMPLETE, 2 * NS)
        self.begin(2, 5 * NS)
        self.tracker.on_api(201, COMPLETE, 8 * NS)
        self.tracker.tick(14 * NS)
        self.begin(3, 15 * NS)
        self.ordered(3, 16 * NS, "gap", 2, "k3")
        self.tracker.on_api(201, COMPLETE, 17 * NS)
        by_no = {c.no: c for c in self.closed}
        self.assertEqual([by_no[n].outcome for n in (1, 2, 3)],
                         [Outcome.NORMAL, Outcome.NO_RESULT, Outcome.NORMAL])
        self.assertEqual(len(self.closed), 3)
        self.assertTrue(by_no[2].id_accounted)

    def test_each_lost_cycle_is_claimed_once(self):
        self.begin(1, 0)
        self.tracker.on_api(201, COMPLETE, NS)
        self.begin(2, 3 * NS)
        self.tracker.on_api(201, COMPLETE, 4 * NS)
        self.begin(3, 6 * NS)
        self.ordered(30, 7 * NS, "gap", 3, "k3")
        self.tracker.on_api(201, COMPLETE, 8 * NS)
        self.begin(4, 10 * NS)
        self.ordered(31, 11 * NS, "consecutive", 1, "k4")
        self.tracker.on_api(201, COMPLETE, 12 * NS)
        self.assertEqual([c.outcome for c in sorted(self.closed, key=lambda c: c.no)],
                         [Outcome.NO_RESULT, Outcome.NO_RESULT, Outcome.NORMAL, Outcome.NORMAL])

    def test_id_jump_does_not_skip_cycle_without_stop(self):
        # A cycle that has not stopped yet cannot be judged lost.
        self.begin(1, 0)
        self.begin(2, NS)
        self.ordered(5, 2 * NS, "gap", 2, "k5")
        self.assertFalse([c for c in self.closed if c.outcome is Outcome.NO_RESULT])

    def test_proximity_cycle_is_not_counted_in_id_order(self):
        self.begin(1, 0)
        self.tracker.on_api(201, PROXIMITY, NS)
        self.begin(2, 3 * NS)
        self.ordered(7, 4 * NS, "consecutive", 1, "k7")
        self.tracker.on_api(201, COMPLETE, 5 * NS)
        self.tracker.tick(10 * NS)
        by_no = {c.no: c for c in self.closed}
        self.assertEqual(by_no[1].outcome, Outcome.EMPTY_SHOT)
        self.assertEqual(by_no[2].outcome, Outcome.NORMAL)
        self.assertEqual(by_no[2].test_id, "7")


if __name__ == "__main__":
    unittest.main()
