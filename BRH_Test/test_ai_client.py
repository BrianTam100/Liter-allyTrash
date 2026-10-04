import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from BRH_Test.ai_client import AdviceClient


def response(provider="gemini", text="Use a battery collection point."):
    return io.BytesIO(json.dumps({"status": "completed",
        "steps" if provider == "gemini" else "output": [
            {"type": "thought", "content": [{"type": "text", "text": "private thought"}]},
            {"type": "model_output" if provider == "gemini" else "message", "content": [
                {"type": "text" if provider == "gemini" else "output_text", "text": text}]}]}).encode())


class AdviceTests(unittest.TestCase):
    def setUp(self):
        self.ai = AdviceClient({"GEMINI_API_KEY": "secret-g", "XAI_API_KEY": "secret-x"})

    def test_gemini_history_and_no_tools_or_remote_storage(self):
        with patch("BRH_Test.ai_client.urlopen", return_value=response()) as send:
            result = self.ai.generate("trusted instructions", [{"role": "assistant", "content": "hello"}], "batteries?")
        self.assertEqual(result, "Use a battery collection point.")
        self.assertEqual(send.call_count, 1)
        req = send.call_args.args[0]
        body = json.loads(req.data)
        self.assertFalse(body["store"])
        self.assertNotIn("tools", body)
        self.assertNotIn("secret-g", req.full_url)
        self.assertEqual(body["input"][0]["type"], "model_output")
        self.assertEqual(body["input"][1]["type"], "user_input")

    def test_transient_retry_then_success(self):
        with patch("BRH_Test.ai_client.time.sleep"), patch("BRH_Test.ai_client.urlopen", side_effect=[TimeoutError(), response()]) as send:
            self.assertIsNotNone(self.ai.generate("", [], "question"))
        self.assertEqual(send.call_count, 2)

    def test_photo_request_is_gemini_only(self):
        photo = {"type": "image", "mime_type": "image/jpeg", "data": "encoded"}
        with patch("BRH_Test.ai_client.urlopen", return_value=response()) as send:
            self.ai.generate("", [], "What is this?", providers=("gemini",), image=photo)
        self.assertEqual(json.loads(send.call_args.args[0].data)["input"][-1]["content"][-1], photo)
        with patch("BRH_Test.ai_client.time.sleep"), patch("BRH_Test.ai_client.urlopen", side_effect=TimeoutError()) as send:
            self.assertIsNone(self.ai.generate("", [], "What is this?", providers=("gemini",), image=photo))
        self.assertEqual(send.call_count, 2)

    def test_quota_and_auth_skip_retry_and_cool_down(self):
        for code in (400, 401, 403, 404, 429):
            self.setUp()
            error = HTTPError("https://example.test", code, "private error", {}, None)
            with patch("BRH_Test.ai_client.urlopen", side_effect=[error, response("xai"), response("xai")]) as send:
                self.assertIsNotNone(self.ai.generate("", [], "question"))
                self.assertIsNotNone(self.ai.generate("", [], "question"))
            self.assertEqual(send.call_count, 3)
            self.assertTrue(self.ai.status()["gemini"]["cooldown"])
            self.assertNotIn("secret", json.dumps(self.ai.status()))

    def test_malformed_and_incomplete_responses_use_fallback(self):
        for raw in (b'null', b'{}', b'not json', b'{"status":"incomplete","steps":[]}'):
            self.setUp()
            with patch("BRH_Test.ai_client.urlopen", side_effect=[io.BytesIO(raw), response("xai")]):
                self.assertIsNotNone(self.ai.generate("", [], "question"))
            self.assertEqual(self.ai.status()["gemini"]["last_result"], "invalid_response")

    def test_outage_opens_circuit_then_recovers(self):
        self.ai.config["XAI_API_KEY"] = ""
        with patch("BRH_Test.ai_client.time.sleep"), patch("BRH_Test.ai_client.urlopen", side_effect=TimeoutError()) as send:
            for _ in range(4):
                self.assertIsNone(self.ai.generate("", [], "question"))
            self.assertEqual(send.call_count, 6)
        self.ai.health["gemini"]["until"] = 0
        with patch("BRH_Test.ai_client.urlopen", return_value=response()):
            self.assertIsNotNone(self.ai.generate("", [], "question"))
        self.assertFalse(self.ai.status()["gemini"]["cooldown"])

    def test_overload_returns_local_fallback_without_network(self):
        for _ in range(4):
            self.ai.slots.acquire()
        with patch("BRH_Test.ai_client.urlopen") as send:
            self.assertIsNone(self.ai.generate("", [], "question"))
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
