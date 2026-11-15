import json
import socket
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from arduino import parse_arduino_control
from core import parse_device_json
from transport import DemoClient, ListenerClient


class ReadTimeout(Exception):
    pass


class FakeSocket:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.sent = []
        self.sopt = None

    @property
    def sock(self):
        raise OSError("TCP keepalive tuning unavailable")

    def connect(self, endpoint, **kwargs):
        self.sopt = kwargs["sockopt"]

    def settimeout(self, timeout):
        pass

    def send(self, value):
        self.sent.append(value)

    def recv(self):
        return ListenerClient.ACCEPTED

    def recv_data(self):
        try:
            return next(self.frames)
        except StopIteration:
            raise ReadTimeout()

    def shutdown(self):
        pass


class TransportTests(unittest.TestCase):
    def test_count_data_frames_including_empty_and_binary_until_close(self):
        first = FakeSocket([(1, b""), (2, b"\xff"), (8, b"")])
        second = FakeSocket([(1, b'{"commandId":403,"id":200}'), (8, b"")])
        sockets = iter((first, second))
        module = SimpleNamespace(WebSocket=lambda **kwargs: next(sockets),
                                 WebSocketTimeoutException=ReadTimeout,
                                 ABNF=SimpleNamespace(OPCODE_CLOSE=8))
        packets = []
        finished = threading.Event()

        def record(kind, value):
            if kind == "packet":
                packets.append(value)
                if len(packets) == 3:
                    finished.set()

        client = ListenerClient("192.168.7.2", 7860, record, reconnect_seconds=0.01)
        with patch.dict("sys.modules", {"websocket": module}):
            client.start()
        try:
            self.assertTrue(finished.wait(2))
        finally:
            client.stop()
        self.assertEqual([p.rx_no for p in packets], [1, 2, 1])
        self.assertEqual([p.raw for p in packets], [b"", b"\xff", b'{"commandId":403,"id":200}'])
        self.assertEqual(first.sopt, ((socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),))
        self.assertEqual(first.sent, [ListenerClient.GREETING])
        self.assertEqual(second.sent, [ListenerClient.GREETING])

    def test_demo_contains_six_protocol_scenarios(self):
        events = []
        client = DemoClient(lambda kind, value: events.append((kind, value)))
        client._rx_no = 0
        client._gpio_started_ns = 0
        client._gpio_sequence = 0
        packets = []
        with patch.object(client._stop, "wait", return_value=False):
            for scenario in range(6):
                self.assertTrue(client._demo_cycle(scenario, scenario + 1, scenario + 1))
                controls = [parse_arduino_control(value.text) for kind, value in events if kind == "arduino_line"]
                self.assertTrue(all(c is not None and 0 < c.sent <= c.total for c in controls))
                data = [value for kind, value in events if kind == "packet"]
                packets.extend(data)
                messages = [parse_device_json(value.raw) for value in data]
                stops = [m["params"]["stopReasonInt"] for m, _ in messages if m["id"] == 201]
                self.assertEqual(stops, ([0], [6], [0], [], [2], [0])[scenario])
                finals = [(m, flag) for m, flag in messages if m["id"] == 206
                          and m["params"]["result"]["analysis"]["final"]]
                self.assertEqual(len(finals), int(scenario in (0, 5)))
                if scenario == 2:
                    reports = [value for kind, value in events if kind == "arduino_report"]
                    states = [value for value in reports if value.event == "STATE"]
                    self.assertEqual(len(states), 5)
                    self.assertTrue(all(value.ready and not value.rad_on for value in states))
                    self.assertEqual({value.sequence for value in states}, {reports[-6].sequence})
                if scenario == 3:
                    self.assertIn("NO_RESPONSE", [c.event for c in controls])
                if scenario == 4:
                    self.assertEqual([c.event for c in controls],
                                     ["DOUBLE_FIRST", "DOUBLE_SECOND", "DOUBLE_DONE"])
                if scenario == 5:
                    self.assertTrue(finals[0][1])
                    json.dumps(finals[0][0], allow_nan=False)
                events.clear()
        self.assertEqual([p.rx_no for p in packets], list(range(1, len(packets) + 1)))
