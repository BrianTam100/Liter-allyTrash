"""Integration checks for recognizing, attributing, and rewarding an item."""
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from BRH_Test.website import create_app
from classifier_service import ItemLock, Service


class DashboardIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Service()
        self.service.model = Mock()
        self.service.model.predict.return_value = ('plastic water bottle', 0.82)
        self.service.model.category = 'Recyclable'
        self.service.model.alternatives = [('plastic water bottle', 0.82)]
        self.service.capture.subscribe = Mock()
        self.service.capture.unsubscribe = Mock()
        self.service.capture.latest = Mock(return_value=(1, np.zeros((16,16,3), np.uint8), b'jpeg'))
        self.service.lid = Mock()
        self.app = create_app({'TESTING':True, 'SECRET_KEY':'unified-test-key', 'DATABASE_URL':'',
            'SQLITE_PATH':str(Path(self.temp.name)/'test.db')}, classifier_service=self.service)
        self.client = self.app.test_client()
        self.client.get('/')
        self.detector = self.app.extensions['classifier']

    def tearDown(self):
        self.detector.close()
        self.app.extensions['rover'].close()
        self.temp.cleanup()

    def post(self, path, data=None, client=None, live=False):
        client = client or self.client
        with client.session_transaction() as state:
            csrf = state['csrf_token']
        headers = {'X-CSRF-Token':csrf}
        if live:
            headers.update({'X-Trash-Live':'1','X-Trash-Session':str(self.detector.generation)})
        return client.post(path,json=data or {},headers=headers)

    def photo(self):
        picture = io.BytesIO()
        Image.new('RGB',(32,32),'green').save(picture,format='PNG')
        with self.client.session_transaction() as state:
            csrf = state['csrf_token']
        return self.client.post('/api/classifier/predict',data=picture.getvalue(),headers={'X-CSRF-Token':csrf})

    def test_photo_to_account_history_and_reward_without_opening_lid(self):
        scan = self.photo().get_json()
        self.service.lid.open.assert_not_called()
        self.assertEqual(self.app.extensions['database'].stats(1)['points'],0)
        response = self.post('/api/classifier/confirm',{'scan_id':scan['scan_id'],'count':1})
        self.assertEqual(response.status_code,201)
        self.assertEqual(response.get_json()['stats']['points'],10)
        history = self.app.extensions['database'].recent(1)
        self.assertEqual((history[0]['item_name'],history[0]['category']),('plastic water bottle','recycling'))
        log = self.app.extensions['database'].detections()
        self.assertEqual([(row['label'],row['source'],row['confirmed']) for row in log],[('plastic water bottle','photo',1)])

    @patch.object(ItemLock, 'LOCK_SECONDS', 0)
    def test_live_frames_share_one_scan_id_and_confirmation_is_idempotent(self):
        self.post('/api/classifier/start',{'source':'server'})
        readings = [self.post('/api/classifier/camera',live=True).get_json() for _ in range(5)]
        self.assertEqual([row['state'] for row in readings[:3]],['checking','checking','locked'])
        self.assertEqual(readings[2]['scan_id'],readings[4]['scan_id'])
        self.assertEqual(len(self.app.extensions['database'].detections()),1)  # one row per locked item, not per frame
        self.assertEqual(self.app.extensions['database'].stats(1)['points'],0)
        event = {'scan_id':readings[2]['scan_id'],'count':1}
        self.assertEqual(self.post('/api/classifier/confirm',event).status_code,201)
        self.assertEqual(self.post('/api/classifier/confirm',event).status_code,200)
        self.assertEqual(self.app.extensions['database'].stats(1)['points'],10)

    def test_slow_model_readings_can_still_lock_one_live_item(self):
        item = ItemLock()
        result = {'label':'plastic water bottle', 'category':'Recyclable', 'score':0.8, 'seconds':4.0}
        with patch('classifier_service.time.monotonic', side_effect=[100,104.3,108.6]):
            states = [item.update(result)['state'] for _ in range(3)]
        self.assertEqual(states, ['checking','checking','locked'])

    def test_brief_gap_or_misreading_does_not_start_a_second_scan(self):
        item = ItemLock()
        bottle = {'label':'plastic water bottle', 'category':'Recyclable', 'score':0.8, 'seconds':0.05}
        bag = {**bottle, 'label':'chip bag', 'category':'Trash'}
        empty = {**bottle, 'label':'No sorted item detected', 'category':None}
        readings = [bottle]*5 + [empty]*4 + [bottle] + [bag]*6 + [bottle] + [empty]*8
        with patch('classifier_service.time.monotonic', side_effect=[100 + 0.15*i for i in range(len(readings))]):
            results = [item.update(reading) for reading in readings]
        states = [result['state'] for result in results]
        self.assertEqual(states[:5], ['checking']*4 + ['locked'])  # locks after 0.5 s, not 3 fast readings
        self.assertEqual(states[5:17], ['locked']*12)  # a 0.6 s gap or 0.9 s misreading keeps the lock
        self.assertEqual({result['scan_id'] for result in results[4:17]}, {results[4]['scan_id']})
        self.assertEqual(states[-1], 'empty')  # gone for over a second clears it

    def test_trash_recognition_never_earns_recycling_points(self):
        self.service.model.category = 'Trash'
        self.service.model.predict.return_value = ('paper towel',0.9)
        scan = self.photo().get_json()
        self.post('/api/classifier/confirm',{'scan_id':scan['scan_id'],'count':2,'category':'recycling'})
        stats = self.app.extensions['database'].stats(1)
        self.assertEqual((stats['items'],stats['points']),(2,0))

    def test_another_browser_cannot_use_someone_elses_result_or_live_camera(self):
        scan = self.photo().get_json()
        self.post('/api/classifier/start',{'source':'server'})
        other = self.app.test_client()
        other.get('/')
        self.assertEqual(self.post('/api/classifier/confirm',{'scan_id':scan['scan_id']},client=other).status_code,400)
        self.assertEqual(self.post('/api/classifier/start',{'source':'server'},client=other).status_code,400)
        self.assertEqual(other.get(f'/api/classifier/stream?generation={self.detector.generation}').status_code,403)

    def test_empty_or_checking_result_cannot_be_confirmed(self):
        self.service.model.category = None
        scan = self.photo().get_json()
        self.assertNotIn('scan_id',scan)
        self.assertEqual(self.post('/api/classifier/confirm',{'scan_id':'not-a-scan'}).status_code,400)

    def test_camera_lease_expiry_stops_capture_and_closes_lid(self):
        self.post('/api/classifier/start',{'source':'server'})
        with self.detector.lock:
            self.detector.heartbeat_at = time.monotonic()-4
        time.sleep(0.35)
        self.assertIsNone(self.detector.owner)
        self.service.capture.unsubscribe.assert_called_once()
        self.service.lid.close.assert_called()

    def test_late_inference_and_late_stop_cannot_affect_a_new_camera_session(self):
        first = self.post('/api/classifier/start',{'source':'server'}).get_json()
        with self.client.session_transaction() as state:
            owner = state['pilot_token']
        original_predict = self.service.predict
        def restart_during_prediction(frame):
            self.detector.stop(owner)
            self.detector.start(owner,'server')
            return original_predict(frame)
        self.service.predict = restart_during_prediction
        response = self.post('/api/classifier/camera',live=True)
        self.assertEqual(response.status_code,400)
        self.service.lid.open.assert_not_called()
        self.post('/api/classifier/stop',{'generation':first['generation']})
        self.assertEqual(self.detector.owner,owner)

    def test_gesture_mode_and_connected_scanner_share_camera_explicitly(self):
        self.post('/api/classifier/start',{'source':'server'})
        with self.client.session_transaction() as state:
            owner = state['pilot_token']
        self.detector.prepare_gesture(owner)
        self.assertIsNone(self.detector.owner)
        self.service.capture.unsubscribe.assert_called_once()

    def test_assets_and_dashboard_use_the_one_web_directory(self):
        self.assertTrue(self.app.static_folder.endswith('web'))
        page = self.client.get('/').data
        self.assertIn(b'id="scanner"',page)
        self.assertIn(b'id="collection-form"',page)
        self.assertNotIn(b'{%',page)
        for asset in ('app.js', 'style.css'):
            with self.client.get('/static/' + asset) as response:
                self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
    unittest.main()
