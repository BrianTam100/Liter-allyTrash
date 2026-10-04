"""Run with: python -m unittest discover -s BRH_Test -p 'test_website.py'."""
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from rover_bridge import RoverBridge
from website import create_app


class WebsiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = RoverBridge()
        self.app = create_app({"TESTING": True, "SECRET_KEY": "isolated-test-key",
            "DATABASE_URL": "", "SQLITE_PATH": str(Path(self.temp.name) / "test.db"),
            "COLLECTION_API_KEY": "test-bin-secret"}, bridge=self.bridge)
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.extensions["classifier"].close()
        self.bridge.close()
        self.temp.cleanup()

    def csrf(self, client=None):
        with (client or self.client).session_transaction() as state:
            return state["csrf_token"]

    def visit(self, client=None):
        return (client or self.client).get("/")

    def drop(self, count=1, category="recycling", request_id=None, item_name="Plastic bottle"):
        return self.client.post("/api/collections", json={"count": count, "category": category,
            "request_id": request_id or str(uuid.uuid4()), "item_name": item_name},
            headers={"X-CSRF-Token": self.csrf()})

    def test_public_pages_render_and_have_accessible_landmarks(self):
        for route in ["/", "/controls", "/log"]:
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200, route)
            self.assertIn(b'lang="en"', response.data)
            self.assertIn(b'id="main"', response.data)
            self.assertIn(b"Litter-ally Trash", response.data)
        self.assertEqual(self.client.get("/unknown").status_code, 404)

    def test_scanner_and_rover_console_have_their_own_pages(self):
        dashboard = self.client.get("/").data
        self.assertIn(b'id="scanner"', dashboard)
        self.assertNotIn(b'id="connect-button"', dashboard)
        controls = self.client.get("/controls")
        self.assertEqual(controls.status_code, 200)
        self.assertIn(b'id="connect-button"', controls.data)
        self.assertIn(b'data-command="z"', controls.data)
        self.assertIn(b'data-command="c"', controls.data)

    def test_detection_log_cache_reuses_data_and_expires(self):
        db = self.app.extensions["database"]
        with patch.object(db, "detection_summary", wraps=db.detection_summary) as summary:
            with patch("website.time.monotonic", return_value=100):
                self.assertEqual(self.client.get("/log").status_code, 200)
                self.client.get("/log")
                self.assertEqual(summary.call_count, 1)
                self.client.get("/log?period=week")
                self.assertEqual(summary.call_count, 2)
            with patch("website.time.monotonic", return_value=131):
                self.client.get("/log")
                self.assertEqual(summary.call_count, 3)

    def test_dashboard_cache_reuses_data_on_return_from_controls(self):
        db = self.app.extensions["database"]
        with patch.object(db, "stats", wraps=db.stats) as stats:
            with patch("website.time.monotonic", return_value=100):
                self.visit()
                self.client.get("/controls")
                self.visit()
                self.assertEqual(stats.call_count, 1)
                self.drop(2)
                page = self.visit()
                self.assertIn(b'id="stat-items">2<', page.data)
                self.assertEqual(stats.call_count, 3)  # Write response and fresh page.
            with patch("website.time.monotonic", return_value=131):
                self.visit()
                self.assertEqual(stats.call_count, 4)

    def test_detection_log_cache_invalidates_after_writes(self):
        self.visit()
        db = self.app.extensions["database"]
        with patch.object(db, "detection_summary", wraps=db.detection_summary) as summary:
            self.client.get("/log")
            scan_id = str(uuid.uuid4())
            db.add_detection(scan_id, 1, "Can", "recycling", False, 0.8, "browser")
            self.assertIn(b"Can", self.client.get("/log").data)
            db.add_collection(1, "recycling", 1, scan_id, "Can")
            self.client.get("/log")
            db.empty_bin("recycling")
            self.client.get("/log")
            db.clear_all()
            self.assertIn(b"Nothing scanned", self.client.get("/log").data)
            self.assertEqual(summary.call_count, 5)

    def test_no_account_needed_but_csrf_still_required(self):
        self.visit()
        other = self.app.test_client()
        self.visit(other)
        self.assertEqual(self.app.extensions["database"].detection_summary()["total"], 0)
        self.assertEqual(self.app.extensions["database"].user(1)["display_name"], "Pilot")
        self.assertEqual(self.client.post("/api/collections", json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/rover").status_code, 200)
        for route in ["/login", "/register"]:
            self.assertEqual(self.client.get(route).status_code, 404)

    def test_recycling_rewards_and_personal_item_history(self):
        self.visit()
        self.assertEqual(self.drop(3).get_json()["stats"]["points"], 30)
        response = self.drop(20, "trash", item_name="Food wrapper")
        self.assertEqual(response.get_json()["stats"]["points"], 30)
        self.assertEqual(response.get_json()["stats"]["items"], 23)
        page = self.client.get("/")
        self.assertIn(b"Plastic bottle", page.data)
        self.assertIn(b"Food wrapper", page.data)
        self.assertIn(b">+30<", page.data)
        self.assertIn(b'id="stat-items">23<', page.data)
        self.assertNotIn(b"built-in method", page.data)
        recent = self.app.extensions["database"].recent(1)
        self.assertEqual({entry["item_name"] for entry in recent}, {"Plastic bottle", "Food wrapper"})

    def test_retries_do_not_duplicate_scores(self):
        self.visit()
        request_id = str(uuid.uuid4())
        self.assertEqual(self.drop(2, request_id=request_id).status_code, 201)
        response = self.drop(2, request_id=request_id)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["saved"])
        self.assertEqual(response.get_json()["stats"]["points"], 20)

    def test_detection_log_breaks_down_bins_items_and_confirmations(self):
        self.visit()
        db = self.app.extensions["database"]
        can = str(uuid.uuid4())
        self.assertTrue(db.add_detection(can, 1, "Aluminum can", "recycling", False, 0.8, "browser"))
        self.assertFalse(db.add_detection(can, 1, "Aluminum can", "recycling", False, 0.8, "browser"))
        db.add_detection(str(uuid.uuid4()), 1, "Aluminum can", "recycling", False, 0.6, "server")
        db.add_detection(str(uuid.uuid4()), 1, "Battery", "recycling", True, 0.7, "photo")
        db.add_detection(str(uuid.uuid4()), 1, "Hold an item", "unrecognized", False, 0.1, "photo")
        db.add_collection(1, "recycling", 1, can, "Aluminum can")
        summary = db.detection_summary()
        self.assertEqual((summary["total"], summary["recycling"], summary["drop_off"], summary["unrecognized"]), (4, 2, 1, 1))
        self.assertEqual(summary["confirmed"], 1)
        self.assertAlmostEqual(summary["avg_score"], 0.7)
        top = db.detection_items()[0]
        self.assertEqual((top["label"], top["detections"], top["confirmed"]), ("Aluminum can", 2, 1))
        page = self.client.get("/log?period=week")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Battery", page.data)
        self.assertIn(b"Drop-off", page.data)
        self.assertEqual(self.client.get("/leaderboard").status_code, 404)

    def test_invalid_payloads_and_html_are_handled(self):
        self.visit()
        self.assertEqual(self.drop(item_name="<script>alert(1)</script>").status_code, 201)
        self.assertEqual(self.drop(-1).status_code, 400)
        self.assertEqual(self.drop(True).status_code, 400)
        self.assertEqual(self.drop(category=["recycling"]).status_code, 400)
        self.assertEqual(self.drop(item_name="").status_code, 400)
        page = self.client.get("/")
        self.assertIn(b"&lt;script&gt;alert(1)&lt;/script&gt;", page.data)
        self.assertNotIn(b"<script>alert(1)</script>", page.data)

    def test_pi_bin_event_auth_and_depositor_attribution(self):
        self.visit()
        event = {"user_id": 1, "count": 4, "category": "recycling", "item_name": "Paper", "request_id": str(uuid.uuid4())}
        self.assertEqual(self.client.post("/api/bin-events", json=event).status_code, 401)
        headers = {"Authorization": "Bearer test-bin-secret"}
        response = self.client.post("/api/bin-events", json=event, headers=headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["stats"]["points"], 40)
        self.assertEqual(self.client.post("/api/bin-events", json=event, headers=headers).status_code, 200)
        event["user_id"] = 9999
        self.assertEqual(self.client.post("/api/bin-events", json=event, headers=headers).status_code, 400)
        self.assertEqual(self.app.extensions["database"].recent(1)[0]["item_name"], "Paper")

    def test_rover_api_uses_protocol_and_disconnect_stops_owned_rover(self):
        self.visit()
        hardware = FakeSerial()
        headers = {"X-CSRF-Token": self.csrf()}
        with patch("serial.Serial", return_value=hardware), patch("rover_bridge.find_serial_port", return_value="COM9"):
            connection = self.client.post("/api/rover/connect", json={"transport": "bluetooth"}, headers=headers)
        self.assertEqual(connection.status_code, 200)
        self.assertTrue(connection.get_json()["owned"])
        for sequence, command in enumerate(["w", "z", "x", "c", "x"], 1):
            movement = self.client.post("/api/rover/command", json={"command":command, "epoch":connection.get_json()["epoch"], "sequence":sequence}, headers=headers)
            self.assertEqual(movement.status_code, 200)
            self.assertEqual(hardware.payloads[-1], command.encode("ascii"))
        movement = self.client.post("/api/rover/command", json={"command":"w", "epoch":connection.get_json()["epoch"], "sequence":6}, headers=headers)
        self.assertEqual(movement.status_code, 200)
        self.assertEqual(hardware.payloads[-1], b"w")
        throttle = self.client.post("/api/rover/speed", json={"speed":2500}, headers=headers)
        self.assertEqual(throttle.status_code, 200)
        self.assertEqual(hardware.payloads[-1], b"v2500")
        self.assertEqual(throttle.get_json()["command"], "w")
        self.assertEqual(throttle.get_json()["speed"], 2500)
        self.client.post("/api/rover/disconnect", json={}, headers=headers)
        self.assertEqual(hardware.payloads[-1], b"x")
        self.assertFalse(hardware.closed)  # kept open so the next connect is instant
        self.bridge.close()
        self.assertTrue(hardware.closed)

    def test_bluetooth_open_failure_is_actionable_persists_and_can_retry(self):
        from serial import SerialException

        self.visit()
        headers = {"X-CSRF-Token": self.csrf()}
        with patch.dict("os.environ", {"ROVER_SERIAL_PORT": "COM3"}), patch(
            "serial.Serial", side_effect=SerialException(
                "could not open port 'COM3': OSError(22, 'The remote system is not available.', None, 1256)")):
            response = self.client.post("/api/rover/connect", json={"transport": "bluetooth"}, headers=headers)
        self.assertEqual(response.status_code, 503)
        message = response.get_json()["error"]
        for text in ["COM3", "Pi", "Bluetooth serial service", "outgoing COM port", "BRH_Test/.env"]:
            self.assertIn(text, message)
        state = self.client.get("/api/rover").get_json()
        self.assertEqual(state["error"], message)
        self.assertEqual(state["link"], "offline")
        self.assertFalse(state["connected"])
        self.assertFalse(state["owned"])
        self.assertFalse(state["busy"])
        rejected = self.client.post("/api/rover/command", json={
            "command": "w", "epoch": state["epoch"], "sequence": 1}, headers=headers)
        self.assertEqual(rejected.status_code, 400)
        hardware = FakeSerial()
        with patch("serial.Serial", return_value=hardware):
            response = self.client.post("/api/rover/connect", json={"transport": "bluetooth"}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["error"])
        self.assertTrue(response.get_json()["owned"])
        self.assertEqual(hardware.payloads, [b"x"])


class PortDetectionTests(unittest.TestCase):
    def test_chosen_port_is_used_strictly_and_switching_reopens(self):
        ports = [{"device": "COM3", "kind": "paired Bluetooth", "paired": True},
                 {"device": "COM8", "kind": "paired Bluetooth", "paired": True}]
        bridge = RoverBridge()
        opened = []
        def open_port(port, *args, **kwargs):
            opened.append(FakeSerial())
            opened[-1].port = port
            return opened[-1]
        try:
            with patch("rover_bridge.list_serial_ports", return_value=ports), patch("serial.Serial", side_effect=open_port):
                bridge.connect("pilot", "bluetooth", "COM8")
                self.assertEqual(bridge.status("pilot")["port"], "COM8")
                bridge.disconnect("pilot")
                bridge.connect("pilot", "bluetooth", "com3")
                self.assertEqual([port.port for port in opened], ["COM8", "COM3"])
                self.assertTrue(opened[0].closed)
                bridge.disconnect("pilot")
                with self.assertRaisesRegex(ValueError, "COM5 isn't available"):
                    bridge.connect("pilot", "bluetooth", "COM5")
                with self.assertRaisesRegex(ValueError, "Choose the rover's port"):
                    bridge.connect("pilot", "bluetooth", "auto")  # two paired ports: auto can't guess
        finally:
            bridge.close()

    def test_port_detection_prefers_outgoing_bluetooth_port(self):
        from rover_bridge import find_serial_port
        port = lambda device, hwid: Mock(device=device, description="Serial over Bluetooth", hwid=hwid)
        ports = [port("COM3", r"BTHENUM\{1101}_VID&1D6B\9&20FE&0&2CCF6755D333_C00000000"),
                 port("COM4", r"BTHENUM\{1101}_LOCALMFG\9&20FE&0&000000000000_00000000")]
        with patch("serial.tools.list_ports.comports", return_value=ports):
            self.assertEqual(find_serial_port("COM8"), "COM3")
            self.assertEqual(find_serial_port("COM4"), "COM4")
        with patch("serial.tools.list_ports.comports", return_value=[]):
            with self.assertRaisesRegex(ValueError, "COM8 was not found"):
                find_serial_port("COM8")


class FakeSerial:
    def __init__(self, *args, **kwargs):
        self.payloads = []
        self.closed = False

    def write(self, payload):
        self.payloads.append(payload)

    def close(self):
        self.closed = True


class RoverTests(unittest.TestCase):
    def setUp(self):
        self.bridge = RoverBridge()
        self.hardware = FakeSerial()
        self.serial_patch = patch("serial.Serial", return_value=self.hardware)
        self.serial_patch.start()
        self.port_patch = patch("rover_bridge.find_serial_port", return_value="COM9")
        self.port_patch.start()
        self.bridge.connect("pilot-a", "bluetooth")

    def tearDown(self):
        self.bridge.close()
        self.serial_patch.stop()
        self.port_patch.stop()

    def command(self, value, sequence=1):
        self.bridge.command("pilot-a", value, self.bridge.epoch, sequence)

    def test_existing_protocol_and_single_pilot_ownership(self):
        self.command("w")
        self.assertEqual(self.hardware.payloads[-1], b"w")
        with self.assertRaises(ValueError):
            self.bridge.command("pilot-b", "s", self.bridge.epoch, 2)
        with self.assertRaises(ValueError):
            self.bridge.connect("pilot-b", "bluetooth")
        self.command("x", 2)
        self.assertEqual(self.hardware.payloads[-1], b"x")

    def test_release_and_emergency_stop_reject_late_motion(self):
        epoch = self.bridge.epoch
        self.command("w", 1)
        self.command("x", 3)
        self.command("w", 2)
        self.assertEqual(self.bridge.last_command, "x")
        self.bridge.stop("pilot-a")
        self.bridge.command("pilot-a", "s", epoch, 4)
        self.assertEqual(self.bridge.last_command, "x")

    def test_strafe_commands_use_both_transports_and_release_stops(self):
        for link in ["bluetooth", "wifi"]:
            with self.subTest(link=link), self.bridge.lock:
                self.bridge.link = link
                self.bridge.target = ("127.0.0.1", 5005)
                with patch.object(self.hardware, "sendto", create=True) as sendto:
                    for sequence, command in enumerate(["z", "x", "c", "x"], 1):
                        self.command(command, sequence)
                        self.assertEqual(self.bridge.last_command, command)
                        if link == "wifi":
                            sendto.assert_called_with(command.encode("ascii"), self.bridge.target)
                        else:
                            self.assertEqual(self.hardware.payloads[-1], command.encode("ascii"))
                    self.command("z", 3)
                    self.assertEqual(self.bridge.last_command, "x")
                    self.bridge.sequence = 0
        self.bridge.link = "bluetooth"

    def test_manual_command_times_out_even_with_browser_heartbeat(self):
        for sequence, command in enumerate(["w", "z", "c"], 1):
            with self.subTest(command=command):
                self.command(command, sequence)
                with self.bridge.lock:
                    self.bridge.manual_until = time.monotonic() - 1
                time.sleep(0.2)
                self.assertEqual(self.bridge.last_command, "x")
        self.assertIsNotNone(self.bridge.transport)

    def test_browser_lease_expiry_stops_and_releases(self):
        self.command("w")
        with self.bridge.lock:
            self.bridge.heartbeat_at = time.monotonic() - 2
        time.sleep(0.2)
        self.assertIsNone(self.bridge.transport)
        self.assertEqual(self.hardware.payloads[-1], b"x")
        self.assertFalse(self.hardware.closed)

    def test_reconnect_reuses_open_port_and_reopens_a_stale_one(self):
        opened = []
        def open_port(*args, **kwargs):
            opened.append(FakeSerial())
            return opened[-1]
        self.bridge.disconnect("pilot-a")
        with patch("serial.Serial", side_effect=open_port):
            self.bridge.connect("pilot-b", "bluetooth")
            self.assertEqual(opened, [])  # warm port reused
            self.bridge.disconnect("pilot-b")
            self.hardware.write = Mock(side_effect=OSError("link dropped"))
            self.bridge.connect("pilot-b", "bluetooth")
        self.assertEqual(len(opened), 1)
        self.assertTrue(self.hardware.closed)
        self.assertEqual(opened[0].payloads, [b"x"])

    def test_gesture_angle_and_manual_priority(self):
        self.bridge.mode = "gesture"
        self.bridge._assisted_command("pilot-a", "gesture", "90\n")
        self.assertEqual(self.hardware.payloads[-1], b"90\n")
        self.command("a")
        self.bridge._assisted_command("pilot-a", "gesture", "0\n")
        self.assertEqual(self.hardware.payloads[-1], b"a")

    def test_speed_command_uses_arduino_throttle_protocol(self):
        self.command("w")
        self.bridge.set_speed("pilot-a", 2500)
        self.assertEqual(self.hardware.payloads[-1], b"v2500")
        self.assertEqual(self.bridge.status("pilot-a")["command"], "w")
        self.assertEqual(self.bridge.status("pilot-a")["speed"], 2500)

    def test_invalid_commands_cannot_reach_hardware(self):
        with self.assertRaises(ValueError):
            self.command("run shell")
        with self.assertRaises(ValueError):
            self.bridge.set_speed("pilot-a", 99)
        self.assertEqual(self.hardware.payloads, [b"x"])

    def test_lost_transport_releases_assisted_devices(self):
        class VoiceStub:
            error = None
            def __init__(self):
                self.stopped = False
            def stop(self):
                self.stopped = True

        voice = VoiceStub()
        self.bridge.mode = "voice"
        self.bridge.voice = voice
        with patch.object(self.hardware, "write", side_effect=OSError("link lost")):
            with self.assertRaises(OSError):
                self.command("w")
        time.sleep(0.2)
        self.assertTrue(voice.stopped)
        self.assertIsNone(self.bridge.transport)

    def test_failed_initial_stop_preserves_error_and_releases_connection(self):
        self.bridge.disconnect("pilot-a")
        self.bridge._close_serial()  # A fresh failed link, not the healthy cached port.
        hardware = FakeSerial()
        failure = OSError("Bluetooth link lost during initial STOP")
        with patch("serial.Serial", return_value=hardware), patch.object(
            hardware, "write", side_effect=failure):
            with self.assertRaises(OSError) as caught:
                self.bridge.connect("pilot-a", "bluetooth")
        self.assertIs(caught.exception, failure)
        self.assertTrue(hardware.closed)
        state = self.bridge.status("pilot-a")
        self.assertFalse(state["connected"])
        self.assertFalse(state["owned"])
        self.assertEqual(state["link"], "offline")


if __name__ == "__main__":
    unittest.main()
