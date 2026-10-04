"""Integration tests use isolated databases; never message real contacts or move motors."""
import re
import tempfile
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from BRH_Test.companion import Companion, digest
from BRH_Test.website import create_app


class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test", "DATABASE_URL": "",
            "SQLITE_PATH": str(Path(self.temp.name) / "test.db"), "XAI_API_KEY": "", "GEMINI_API_KEY": "",
            "SPECTRUM_BRIDGE_KEY": "bridge-test", "SPECTRUM_ALLOWED_SENDERS": "+15551111111"})
        self.client = self.app.test_client()
        self.client.get("/")
        self.agent = self.app.extensions["companion"]
        self.db = self.app.extensions["database"]

    def tearDown(self):
        self.app.extensions["classifier"].close()
        self.app.extensions["rover"].close()
        self.temp.cleanup()

    def message(self, text, sender="+15551111111", message_id=None, space="demo", group=False):
        return self.agent.respond("imessage", space, sender, message_id or str(uuid.uuid4()), text, 1, group)

    def post(self, text="progress", **changes):
        payload = {"platform": "imessage", "space_id": "demo", "sender_id": "+15551111111",
                   "message_id": str(uuid.uuid4()), "text": text, **changes}
        return self.client.post("/api/integrations/spectrum/message", json=payload,
                                headers={"Authorization": "Bearer bridge-test"})

    def code(self, reply):
        return re.search(r"confirm ([A-F0-9]{6})", reply["reply"])[1]

    def test_confirmation_and_replay_never_duplicate_points(self):
        proposal = self.message("log 2 plastic bottles in recycling", message_id="proposal")
        self.assertEqual(self.db.stats(1)["points"], 0)
        self.assertEqual(self.message("log 2 plastic bottles in recycling", message_id="proposal"), proposal)
        code = self.code(proposal)
        self.message("yes")
        self.assertEqual(self.db.stats(1)["points"], 0)
        self.message("confirm " + code, sender="someone-else")
        self.assertEqual(self.db.stats(1)["points"], 0)
        recorded = self.message("confirm " + code, message_id="confirmation")
        self.assertEqual(self.db.stats(1)["points"], 20)
        self.assertEqual(self.message("confirm " + code, message_id="confirmation"), recorded)
        self.message("confirm " + code)
        self.assertEqual(self.db.stats(1)["points"], 20)
        self.assertIn("20 points", self.message("progress")["reply"])

    def test_concurrent_confirmation_serializes_across_instances(self):
        code = self.code(self.message("log 3 cardboard boxes in recycling"))
        other = Companion(self.db, self.app.extensions["rover"], self.app.config)
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(agent.respond, "imessage", "demo", "+15551111111", "simultaneous", "confirm " + code, 1)
                       for agent in [self.agent, other]]
            results = [future.result() for future in futures]
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.db.stats(1)["points"], 30)

    def test_expired_or_cancelled_proposals_do_not_record(self):
        code = self.code(self.message("log 1 chip bag in trash"))
        with patch("BRH_Test.companion.time.time", return_value=time.time() + 301):
            self.assertIn("expired", self.message("confirm " + code)["reply"])
        self.assertEqual(self.db.stats(1)["collections"], 0)
        code = self.code(self.message("log 1 bottle in recycling"))
        self.message("cancel")
        self.message("confirm " + code)
        self.assertEqual(self.db.stats(1)["collections"], 0)

    def test_group_participation_requires_address(self):
        self.assertIsNone(self.message("log 2 bottles in recycling", group=True)["reply"])
        self.assertTrue(self.message("Rover, log 2 bottles in recycling", group=True)["pending"])
        self.assertEqual(self.db.stats(1)["points"], 0)

    def test_bridge_auth_sender_filter_validation_and_csrf(self):
        self.assertEqual(self.client.post("/api/integrations/spectrum/message", json={}).status_code, 401)
        self.assertEqual(self.post(sender_id="unauthorized").status_code, 403)
        self.assertEqual(self.post(is_group="false").status_code, 400)
        self.assertEqual(self.post(text="x" * 2001).status_code, 400)
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.client.post("/api/companion/message", json={}).status_code, 403)

    def test_web_and_spectrum_share_records_but_isolate_memory(self):
        with self.client.session_transaction() as state:
            token = state["csrf_token"]
        response = self.client.post("/api/companion/message", json={"text": "log 2 bottles in recycling", "message_id": "web"},
                                    headers={"X-CSRF-Token": token})
        code = self.code(response.get_json())
        self.message("confirm " + code)
        self.assertEqual(self.db.stats(1)["points"], 0)
        self.client.post("/api/companion/message", json={"text": "confirm " + code, "message_id": "web-confirm"},
                         headers={"X-CSRF-Token": token})
        self.assertIn("20 points", self.message("progress")["reply"])
        fresh_browser = self.app.test_client()
        self.assertEqual(fresh_browser.get("/api/companion/history").get_json()["messages"], [])

    def test_memory_survives_restart_and_forget_preserves_records(self):
        proposal = self.message("log 1 bottle in recycling")
        restarted = Companion(self.db, self.app.extensions["rover"], self.app.config)
        restarted.respond("imessage", "demo", "+15551111111", "restart", "confirm " + self.code(proposal), 1)
        self.message("forget")
        self.assertEqual(self.agent.history(digest("imessage", "demo", "+15551111111")), {})
        self.assertEqual(self.db.stats(1)["points"], 10)

    def test_chat_cannot_command_hardware(self):
        with patch.object(self.app.extensions["rover"], "command") as command:
            self.assertIn("cannot move", self.message("drive forward")["reply"])
            self.message("stop")
            command.assert_not_called()

    def test_model_failure_falls_back_and_has_no_write_tools(self):
        self.app.config["XAI_API_KEY"] = "test-key"
        with patch("BRH_Test.ai_client.urlopen", side_effect=TimeoutError):
            self.assertIn("designated", self.message("where do batteries go?")["reply"])
        self.assertEqual(self.db.stats(1)["collections"], 0)

    def test_companion_uses_xai_separately_from_gemini(self):
        self.app.config["GEMINI_API_KEY"] = "test-gemini"
        self.app.config["XAI_API_KEY"] = "test-xai"
        with patch.object(self.agent.ai, "generate", return_value="Use a designated collection point.") as generate:
            self.message("progress")
            self.message("rover status")
            proposal = self.message("log 1 bottle in recycling")
            self.message("confirm " + self.code(proposal))
            generate.assert_not_called()
            self.assertIn("designated", self.message("Where should batteries go?")["reply"])
            generate.assert_called_once()
            self.assertEqual(generate.call_args.kwargs["providers"], ("xai",))
        self.assertEqual(self.db.stats(1)["collections"], 1)
        status = self.client.get("/api/companion/status").get_json()
        self.assertTrue(status["conversation_ready"])
        self.assertTrue(status["ai"]["gemini"]["configured"])

    def test_connection_health_expires_and_never_exposes_credentials(self):
        response = self.client.post("/api/integrations/spectrum/heartbeat", json={"state":"connected", "providers":["imessage"]},
                                    headers={"Authorization":"Bearer bridge-test"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.get("/api/companion/status").get_json()["connected"])
        with patch("BRH_Test.companion.time.time", return_value=time.time() + 46):
            self.assertFalse(self.client.get("/api/companion/status").get_json()["connected"])
        self.assertNotIn("bridge-test", self.client.get("/api/companion/status").get_data(as_text=True))

    def test_rate_limit_does_not_block_replay_receipts(self):
        first = self.post(message_id="first")
        for i in range(19):
            self.assertEqual(self.post(message_id=f"next-{i}").status_code, 200)
        self.assertEqual(self.post().status_code, 429)
        self.assertEqual(self.post(message_id="first").get_json(), first.get_json())

    def test_telegram_uses_separate_allowlist_and_confirms_shared_drop(self):
        self.app.config['SPECTRUM_TELEGRAM_ALLOWED_SENDERS'] = '12345'
        self.assertEqual(self.post(platform='telegram').status_code, 403)
        self.assertEqual(self.post(platform='imessage',sender_id='12345').status_code, 403)
        proposal = self.post('log 2 bottles in recycling',platform='telegram',sender_id='12345').get_json()
        code = self.code(proposal)
        self.assertEqual(self.db.stats(1)['points'],0)
        confirmed = self.post('confirm '+code,platform='telegram',sender_id='12345',message_id='tg-confirm')
        self.assertEqual(confirmed.status_code,200)
        self.post('confirm '+code,platform='telegram',sender_id='12345',message_id='tg-confirm')
        self.assertEqual(self.db.stats(1)['points'],20)

    def test_telegram_heartbeat_is_supported(self):
        response=self.client.post('/api/integrations/spectrum/heartbeat',json={'state':'connected','providers':['telegram']},
                                  headers={'Authorization':'Bearer bridge-test'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/api/companion/status').get_json()['providers'],['telegram'])


if __name__ == "__main__":
    unittest.main()
