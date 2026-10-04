import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from BRH_Test.website import create_app


class GeminiGuideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test", "DATABASE_URL": "",
            "SQLITE_PATH": str(Path(self.temp.name) / "test.db"), "GEMINI_API_KEY": "test-key", "XAI_API_KEY": ""})
        self.client = self.app.test_client()
        self.client.get("/gemini")
        with self.client.session_transaction() as state:
            self.headers = {"X-CSRF-Token": state["csrf_token"]}
        self.ai = self.app.extensions["gemini_guide"]

    def tearDown(self):
        self.app.extensions["classifier"].close()
        self.app.extensions["rover"].close()
        self.temp.cleanup()

    def post(self, data):
        return self.client.post("/api/gemini/analyze", data=data, headers=self.headers)

    def test_visible_separate_page_and_text_analysis_without_writes(self):
        home = self.client.get("/").get_data(as_text=True)
        self.assertNotIn('gemini-feature', home)
        self.assertLess(home.index('sidebar-bottom'), home.index('Gemini Sort Guide'))
        self.assertLess(home.index('Gemini Sort Guide'), home.index('Settings'))
        self.assertIn('Gemini Sort Guide', self.client.get('/gemini').get_data(as_text=True))
        with patch.object(self.ai, "generate", return_value="Separate clean cardboard from the plastic window.") as generate:
            response = self.post({"description": "Mixed packaging", "location": "New York"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["provider"], "gemini")
        self.assertEqual(generate.call_args.kwargs["providers"], ("gemini",))
        self.assertEqual(generate.call_args.args[1], [])
        self.assertEqual(self.app.extensions["database"].stats(1)["collections"], 0)
        self.assertEqual(self.client.get('/api/companion/history').json['messages'], [])

    def test_photo_is_decoded_resized_and_stripped_of_metadata(self):
        photo = io.BytesIO()
        original = Image.new("RGB", (1600, 900), "green")
        exif = Image.Exif(); exif[270] = "private metadata"
        original.save(photo, format="JPEG", exif=exif)
        photo.seek(0)
        with patch.object(self.ai, "generate", return_value="Please show the label.") as generate:
            response = self.post({"photo": (photo, "item.jpg")})
        self.assertEqual(response.status_code, 200)
        sent = generate.call_args.kwargs["image"]
        self.assertEqual(sent["mime_type"], "image/jpeg")
        with Image.open(io.BytesIO(base64.b64decode(sent["data"]))) as normalized:
            self.assertLessEqual(max(normalized.size), 1280)
            self.assertFalse(normalized.getexif())

    def test_rejects_invalid_input_before_provider(self):
        with patch.object(self.ai, "generate") as generate:
            for data in ({}, {"description": "x" * 2001}, {"description": "box", "location": "x" * 121},
                         {"photo": (io.BytesIO(b"not an image"), "fake.jpg")},
                         {"photo": (io.BytesIO(b"x" * (5 * 1024 * 1024 + 1)), "huge.jpg")}):
                self.assertEqual(self.post(data).status_code, 400)
            generate.assert_not_called()
        self.assertEqual(self.client.post('/api/gemini/analyze', data={"description":"box"}).status_code, 403)

    def test_missing_key_and_outage_are_explicit(self):
        with patch.object(self.ai, "generate", return_value=None):
            self.assertEqual(self.post({"description":"box"}).status_code, 503)
        self.app.config["GEMINI_API_KEY"] = ""
        with patch.object(self.ai, "generate") as generate:
            self.assertEqual(self.post({"description":"box"}).status_code, 503)
            generate.assert_not_called()

    def test_rate_limit(self):
        with patch.object(self.ai, "generate", return_value="Check local rules."):
            for _ in range(20):
                self.assertEqual(self.post({"description":"box"}).status_code, 200)
            self.assertEqual(self.post({"description":"box"}).status_code, 429)


if __name__ == "__main__":
    unittest.main()
