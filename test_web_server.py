import io
import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

import numpy as np

from PIL import Image
from lid import CENTER_PULSE, LED0, SERVO1_CHANNEL, Lid, set_servo1_angle
from web_server import CameraStream, Service, make_handler


class WebTests(unittest.TestCase):
    def setUp(self):
        self.service = Service()
        self.service.model = Mock()
        self.service.model.predict.return_value = ('plastic cup', .7)
        self.service.model.alternatives = [('plastic cup', .7)]
        self.service.model.category = 'Trash'
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.service))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = HTTPConnection(*self.server.server_address)

    def tearDown(self):
        self.service.capture.close()
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, body=b'', method='POST', headers=None):
        self.client.request(method, path, body, headers or {'X-Trash-UI': '1'})
        response = self.client.getresponse()
        return response.status, response.read()

    def test_image_round_trip(self):
        buf = io.BytesIO()
        Image.new('RGB', (32, 32), 'red').save(buf, format='PNG')
        status, body = self.request('/api/predict', buf.getvalue())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['label'], 'plastic cup')
        self.assertEqual(json.loads(body)['category'], 'Trash')
        frame = self.service.model.predict.call_args.args[0]
        self.assertEqual(frame[0, 0].tolist(), [0, 0, 255])

    def test_invalid_image_and_busy_model(self):
        self.assertEqual(self.request('/api/predict', b'invalid')[0], 400)
        with self.service.lock:
            self.assertEqual(self.request('/api/predict', b'invalid')[0], 429)

    def test_loading_and_cross_site_request(self):
        self.service.model = None
        self.assertEqual(self.request('/api/predict', b'x')[0], 503)
        self.assertEqual(self.request('/api/camera', headers={'Content-Type': 'text/plain'})[0], 403)

    def camera_reading(self):
        status, body = self.request('/api/camera')
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_live_item_locks_until_removed(self):
        self.service.lid = Mock()
        self.service.capture.latest = Mock(return_value=(1, np.zeros((8, 8, 3), np.uint8), b''))
        scores = iter([.5, .8, .6])
        self.service.model.predict.side_effect = lambda frame: ('plastic cup', next(scores))
        self.assertEqual([self.camera_reading()['state'] for _ in range(2)], ['checking', 'checking'])
        self.service.lid.open.assert_not_called()
        locked = self.camera_reading()
        self.assertEqual((locked['state'], locked['score']), ('locked', .8))
        # A different reading while the item stays in view keeps the locked label.
        self.service.model.predict.side_effect = None
        self.service.model.predict.return_value = ('paper cup', .9)
        self.service.model.category = 'Recyclable'
        self.assertEqual(self.camera_reading()['label'], 'plastic cup')
        self.assertEqual(self.service.lid.open.call_count, 2)
        # Two empty readings clear the lock and stop opening the lid.
        self.service.model.predict.return_value = ('No trash item detected', .9)
        self.service.model.category = None
        self.assertEqual(self.camera_reading()['state'], 'locked')
        self.assertEqual(self.camera_reading()['state'], 'empty')
        self.service.model.predict.return_value = ('paper cup', .9)
        self.service.model.category = 'Recyclable'
        self.assertEqual([self.camera_reading()['state'] for _ in range(3)], ['checking', 'checking', 'locked'])
        self.assertEqual(self.service.lid.open.call_count, 3)

    def test_lid_closes_after_hold(self):
        bus = Mock()
        with patch.dict('sys.modules', smbus=Mock(SMBus=Mock(return_value=bus))):
            lid = Lid(hold_seconds=0.05)
        self.assertNotIn(LED0 + 4 * SERVO1_CHANNEL, [c.args[1] for c in bus.write_byte_data.call_args_list])
        lid.open()
        self.assertEqual(bus.write_byte_data.call_args_list[-2].args[2], int(1533.63 * 4096 / 20000) & 0xFF)
        threading.Event().wait(0.2)
        self.assertFalse(lid.is_open)
        writes = bus.write_byte_data.call_args_list[-4:]
        self.assertEqual(writes[0].args[1], LED0 + 4 * SERVO1_CHANNEL)
        self.assertEqual(writes[2].args[2], int(533.73 * 4096 / 20000) & 0xFF)

    def test_servo_angle_is_clamped(self):
        with patch('lid._bus', Mock()):
            self.assertAlmostEqual(set_servo1_angle(80), CENTER_PULSE + 33 * 11.11)
            self.assertAlmostEqual(set_servo1_angle(-90), CENTER_PULSE - 57 * 11.11)

    def test_home_and_unknown_path(self):
        status, body = self.request('/', method='GET')
        self.assertEqual(status, 200)
        self.assertIn(b'Trash Lens', body)
        self.assertEqual(self.request('/../classifier.py', method='GET')[0], 404)

    def test_camera_stream_requires_token(self):
        self.assertEqual(self.request('/api/stream', method='GET')[0], 403)
        status, body = self.request('/api/camera/start')
        self.assertEqual(status, 200)
        self.assertIn(self.service.stream_token, json.loads(body)['url'])

    @patch('web_server.cv2.VideoCapture')
    def test_camera_keeps_capturing_during_inference(self, video_capture):
        cap = video_capture.return_value
        cap.read.return_value = (True, np.zeros((48, 64, 3), dtype=np.uint8))
        camera = self.service.capture
        camera.subscribe()
        try:
            first, frame, jpeg = camera.latest()
            self.assertEqual(frame.shape, (48, 64, 3))  # The entire camera frame reaches inference.
            self.assertTrue(jpeg.startswith(b'\xff\xd8'))
            with Image.open(io.BytesIO(jpeg)) as preview:
                self.assertEqual(preview.size, (64, 48))
            # A prediction holds this lock, but preview must keep advancing.
            with self.service.lock:
                second, _, _ = camera.latest(after=first)
                third, _, _ = camera.latest(after=second)
            self.assertGreater(third, second)
            video_capture.assert_called_once()
            cap.release.assert_not_called()
        finally:
            camera.unsubscribe()
            camera.close()
        cap.release.assert_called_once()

    @patch('web_server.cv2.VideoCapture')
    def test_camera_failure_releases_device(self, video_capture):
        cap = video_capture.return_value
        cap.read.return_value = (False, None)
        camera = CameraStream(0)
        camera.subscribe()
        try:
            with self.assertRaisesRegex(ValueError, 'Cannot read connected camera'):
                camera.latest()
        finally:
            camera.unsubscribe()
            camera.close()
        cap.release.assert_called_once()


if __name__ == '__main__':
    unittest.main()
