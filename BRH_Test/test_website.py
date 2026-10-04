"""Run with: python -m unittest discover -s BRH_Test -p 'test_website.py'."""
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

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

    def register(self, email="alex@example.com", name="Alex", client=None):
        client = client or self.client
        client.get("/register")
        return client.post("/register", data={"csrf_token": self.csrf(client), "email": email,
            "display_name": name, "password": "a-good-password-123"})

    def drop(self, count=1, category="recycling", request_id=None, item_name="Plastic bottle"):
        return self.client.post("/api/collections", json={"count": count, "category": category,
            "request_id": request_id or str(uuid.uuid4()), "item_name": item_name},
            headers={"X-CSRF-Token": self.csrf()})

    def test_public_pages_render_and_have_accessible_landmarks(self):
        for route in ["/", "/controls", "/leaderboard", "/login", "/register"]:
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200, route)
            self.assertIn(b'lang="en"', response.data)
            self.assertIn(b'id="main"', response.data)
            self.assertIn(b"Liter-ally Trash", response.data)
        self.assertEqual(self.client.get("/unknown").status_code, 404)

    def test_login_session_csrf_and_logout(self):
        self.assertEqual(self.register().status_code, 302)
        self.assertNotIn("password_hash", self.app.extensions["database"].user(1))
        self.assertNotEqual(self.app.extensions["database"].user_by_email("alex@example.com")["password_hash"], "a-good-password-123")
        self.assertEqual(self.client.post("/api/collections", json={}).status_code, 403)
        self.assertEqual(self.client.post("/logout", data={"csrf_token": self.csrf()}).status_code, 302)
        self.assertEqual(self.client.get("/api/rover").status_code, 401)
        self.client.get("/login")
        response = self.client.post("/login", data={"csrf_token": self.csrf(), "email": "ALEX@example.com", "password": "a-good-password-123"})
        self.assertEqual(response.status_code, 302)

    def test_recycling_rewards_and_personal_item_history(self):
        self.register()
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
        self.register()
        request_id = str(uuid.uuid4())
        self.assertEqual(self.drop(2, request_id=request_id).status_code, 201)
        response = self.drop(2, request_id=request_id)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["saved"])
        self.assertEqual(response.get_json()["stats"]["points"], 20)

    def test_rank_uses_recycling_not_trash_and_handles_ties(self):
        self.register()
        self.drop(500, "trash")
        self.drop(2)
        other = self.app.test_client()
        self.register("sam@example.com", "Sam", other)
        with other.session_transaction() as state:
            sam_id = state["user_id"]
        db = self.app.extensions["database"]
        db.add_collection(sam_id, "recycling", 3, str(uuid.uuid4()), "Aluminum can")
        leaders = db.leaderboard()
        self.assertEqual([row["display_name"] for row in leaders], ["Sam", "Alex"])
        self.assertEqual(leaders[0]["points"], 30)
        self.drop(1)
        self.assertEqual([row["rank"] for row in db.leaderboard()], [1, 1])
        self.assertEqual(self.client.get("/leaderboard?period=week").status_code, 200)

    def test_invalid_payloads_and_html_are_handled(self):
        self.register(name="<script>alert(1)</script>")
        self.assertEqual(self.drop(-1).status_code, 400)
        self.assertEqual(self.drop(True).status_code, 400)
        self.assertEqual(self.drop(category=["recycling"]).status_code, 400)
        self.assertEqual(self.drop(item_name="").status_code, 400)
        page = self.client.get("/")
        self.assertIn(b"&lt;script&gt;alert(1)&lt;/script&gt;", page.data)
        self.assertNotIn(b"<script>alert(1)</script>", page.data)

    def test_pi_bin_event_auth_and_depositor_attribution(self):
        self.register()
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

    def test_password_and_duplicate_account_validation(self):
        self.register()
        second = self.app.test_client()
        response = self.register("alex@example.com", "Another Alex", second)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"already registered", response.data)

    def test_rover_api_uses_protocol_and_logout_stops_owned_rover(self):
        self.register()
        hardware = FakeSerial()
        headers = {"X-CSRF-Token": self.csrf()}
        with patch("serial.Serial", return_value=hardware):
            connection = self.client.post("/api/rover/connect", json={"transport": "bluetooth"}, headers=headers)
        self.assertEqual(connection.status_code, 200)
        self.assertTrue(connection.get_json()["owned"])
        movement = self.client.post("/api/rover/command", json={"command":"w", "epoch":connection.get_json()["epoch"], "sequence":1}, headers=headers)
        self.assertEqual(movement.status_code, 200)
        self.assertEqual(hardware.payloads[-1], b"w")
        self.client.post("/logout", data={"csrf_token": self.csrf()})
        self.assertEqual(hardware.payloads[-1], b"x")
        self.assertTrue(hardware.closed)


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
        self.bridge.connect("pilot-a", "bluetooth")

    def tearDown(self):
        self.bridge.close()
        self.serial_patch.stop()

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

    def test_manual_command_times_out_even_with_browser_heartbeat(self):
        self.command("w")
        with self.bridge.lock:
            self.bridge.manual_until = time.monotonic() - 1
        time.sleep(0.2)
        self.assertEqual(self.bridge.last_command, "x")
        self.assertIsNotNone(self.bridge.transport)

    def test_browser_lease_expiry_stops_and_closes(self):
        self.command("w")
        with self.bridge.lock:
            self.bridge.heartbeat_at = time.monotonic() - 2
        time.sleep(0.2)
        self.assertIsNone(self.bridge.transport)
        self.assertEqual(self.hardware.payloads[-1], b"x")
        self.assertTrue(self.hardware.closed)

    def test_gesture_angle_and_manual_priority(self):
        self.bridge.mode = "gesture"
        self.bridge._assisted_command("pilot-a", "gesture", "90\n")
        self.assertEqual(self.hardware.payloads[-1], b"90\n")
        self.command("a")
        self.bridge._assisted_command("pilot-a", "gesture", "0\n")
        self.assertEqual(self.hardware.payloads[-1], b"a")

    def test_invalid_commands_cannot_reach_hardware(self):
        with self.assertRaises(ValueError):
            self.command("run shell")
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


if __name__ == "__main__":
    unittest.main()
