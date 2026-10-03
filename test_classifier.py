import unittest
from unittest.mock import patch, Mock

import numpy as np
from classifier import StablePrediction, TrashClassifier, common_family, run_camera


class RecognitionBehaviorTests(unittest.TestCase):
    def test_family_fallback_does_not_merge_different_materials(self):
        self.assertEqual(common_family("cardboard box", "cardboard shoe box"), "cardboard box")
        self.assertIsNone(common_family("plastic cup", "glass drinking cup"))

    def test_item_change_never_keeps_old_name(self):
        stable = StablePrediction()
        self.assertEqual(stable.update("plastic cup"), "Hold still - checking item")
        self.assertEqual(stable.update("plastic cup"), "plastic cup")
        self.assertEqual(stable.update("glass bottle"), "Hold still - checking item")
        self.assertEqual(stable.update("glass bottle"), "glass bottle")

    def test_uncertainty_resets_confirmation(self):
        stable = StablePrediction()
        stable.update("paper plate")
        self.assertEqual(stable.update("Unsure - show another angle"), "Unsure - show another angle")
        self.assertEqual(stable.update("paper plate"), "Hold still - checking item")

    def test_empty_image_does_not_guess(self):
        model = TrashClassifier.__new__(TrashClassifier)
        label, score = model.predict(np.zeros((224, 224, 3), dtype=np.uint8))
        self.assertEqual(label, "Image has too little detail")
        self.assertEqual(score, 0)
        self.assertEqual(model.alternatives, [])

    @patch("classifier.cv2.destroyAllWindows")
    @patch("classifier.cv2.VideoCapture")
    def test_camera_failure_releases_device(self, video_capture, destroy):
        cap = Mock()
        cap.isOpened.return_value = False
        video_capture.return_value = cap
        with self.assertRaisesRegex(RuntimeError, "Cannot open camera"):
            run_camera(Mock(), 0)
        cap.release.assert_called_once()
        destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
