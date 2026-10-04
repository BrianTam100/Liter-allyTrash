"""Check keyboard senders and the Pi relay without opening any hardware."""
import runpy
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parent


class DriveCommandTests(unittest.TestCase):
    def test_desktop_senders_send_strafe_and_stop_on_release(self):
        for filename in ["command.py", "command_bluetooth_camera.py"]:
            with self.subTest(filename=filename):
                hardware = MagicMock()
                keyboard = MagicMock()
                # One loop for each key, including a release after each strafe.
                keys = iter([None, "c", None, "q"])
                active = "z"

                def is_pressed(key):
                    return key == active

                def next_frame(_):
                    nonlocal active
                    active = next(keys)

                keyboard.is_pressed.side_effect = is_pressed
                serial = MagicMock()
                serial.Serial.return_value = hardware
                socket = MagicMock()
                socket.AF_INET, socket.SOCK_DGRAM = 2, 2
                socket.socket.return_value = hardware
                modules = {"keyboard": keyboard, "serial": serial, "socket": socket,
                           "cv2": MagicMock(), "mediapipe": MagicMock(), "voice_control": MagicMock()}
                args = [filename, "--no-voice"]
                if filename == "command_bluetooth_camera.py":
                    args.append("--no-camera")
                with patch.dict(sys.modules, modules), patch.object(sys, "argv", args), \
                     patch("time.sleep", side_effect=next_frame), patch("builtins.print"):
                    runpy.run_path(str(ROOT / filename), run_name="__main__")
                calls = hardware.sendto.call_args_list if filename == "command.py" else hardware.write.call_args_list
                self.assertEqual([call.args[0] for call in calls], [b"z", b"x", b"c", b"x", b"x", b"x"])
                hardware.close.assert_called_once()

    def test_wifi_receiver_forwards_strafe_and_filters_invalid_packets(self):
        hardware, network = MagicMock(), MagicMock()
        network.recvfrom.side_effect = [(command, ("127.0.0.1", 1234))
                                       for command in [b"z", b"z", b"x", b"c", b"bad", b"x"]] + [KeyboardInterrupt()]
        with patch("serial.Serial", return_value=hardware), \
             patch("socket.socket", return_value=network), patch("time.sleep"), patch("builtins.print"):
            runpy.run_path(str(ROOT / "motor_control.py"), run_name="__main__")
        self.assertEqual([call.args[0] for call in hardware.write.call_args_list],
                         [b"z", b"x", b"c", b"x", b"x"])
        hardware.close.assert_called_once()
        network.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
