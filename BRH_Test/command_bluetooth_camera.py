import argparse
import math
import threading
import time

import cv2
import keyboard
import mediapipe as mp
import serial

from voice_control import VoiceDrive

voice_lock = threading.Lock()
voice_hold = None


def set_voice_command(cmd: str) -> None:
    global voice_hold
    with voice_lock:
        voice_hold = None if cmd == "x" else cmd


def current_voice_command():
    with voice_lock:
        return voice_hold


def main():
    parser = argparse.ArgumentParser(
        description="Drive SortRover over Bluetooth with keyboard, hand angle, and Grok Voice."
    )
    parser.add_argument("--port", default="COM8", help="Outgoing Bluetooth COM port")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--no-voice", action="store_true", help="Skip Grok Voice")
    parser.add_argument("--no-camera", action="store_true", help="Skip MediaPipe hand joystick")
    args = parser.parse_args()

    try:
        print(f"Connecting to Raspberry Pi on {args.port}...")
        bt = serial.Serial(args.port, args.baud, timeout=1)
        print("Connected successfully!")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    cap = None
    hands = None
    mp_draw = None
    mp_hands = None
    if not args.no_camera:
        print("Initializing Camera...")
        mp_hands = mp.solutions.hands
        hands = mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7)
        mp_draw = mp.solutions.drawing_utils
        cap = cv2.VideoCapture(0)

    print("Ready. Priority: keyboard, then voice, then hand angle.")
    print("Say go forward / back up / left / right / stop. Press Q to quit.")

    voice = None
    if not args.no_voice:
        try:
            voice = VoiceDrive(on_command=set_voice_command)
            voice.start()
        except Exception as exc:
            print(f"Voice disabled: {exc}")
            voice = None

    last_state = "x"

    try:
        while True:
            img = None
            if cap is not None:
                success, img = cap.read()
                if not success:
                    continue
                img = cv2.flip(img, 1)

            current_state = "x"

            if keyboard.is_pressed("w") or keyboard.is_pressed("up"):
                current_state = "w"
            elif keyboard.is_pressed("a") or keyboard.is_pressed("left"):
                current_state = "a"
            elif keyboard.is_pressed("d") or keyboard.is_pressed("right"):
                current_state = "d"
            elif keyboard.is_pressed("s") or keyboard.is_pressed("down"):
                current_state = "s"
            elif keyboard.is_pressed("q"):
                bt.write(b"x")
                print("Exiting...")
                break
            else:
                held = current_voice_command()
                if held:
                    current_state = held
                elif cap is not None and img is not None:
                    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    results = hands.process(img_rgb)

                    if results.multi_hand_landmarks:
                        for hand_landmarks in results.multi_hand_landmarks:
                            mp_draw.draw_landmarks(img, hand_landmarks, mp_hands.HAND_CONNECTIONS)

                            wrist = hand_landmarks.landmark[0]
                            index_tip = hand_landmarks.landmark[8]

                            dx = index_tip.x - wrist.x
                            dy = index_tip.y - wrist.y

                            angle_rad = math.atan2(-dy, dx)
                            angle_deg = math.degrees(angle_rad)

                            if angle_deg < 0:
                                angle_deg += 360

                            final_angle = int(round(angle_deg / 5.0) * 5)
                            if final_angle == 360:
                                final_angle = 0

                            current_state = f"{final_angle}\n"

                            cv2.putText(
                                img,
                                f"Angle: {final_angle}",
                                (50, 50),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                1,
                                (0, 255, 0),
                                2,
                            )
                    else:
                        cv2.putText(
                            img,
                            "STOP",
                            (50, 50),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            1,
                            (0, 0, 255),
                            2,
                        )

            if current_state != last_state:
                bt.write(current_state.encode("utf-8"))
                print(f"Sent: {current_state.strip()}")
                last_state = current_state

            if img is not None:
                overlay = current_voice_command() or last_state.strip()
                cv2.putText(
                    img,
                    f"Cmd: {overlay}",
                    (50, 100),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (255, 255, 0),
                    2,
                )
                cv2.imshow("Hand Joystick", img)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    bt.write(b"x")
                    break

            time.sleep(0.01)

    except KeyboardInterrupt:
        bt.write(b"x")
    finally:
        try:
            bt.write(b"x")
        except Exception:
            pass
        if voice:
            voice.stop()
        if cap is not None:
            cap.release()
            cv2.destroyAllWindows()
        bt.close()


if __name__ == "__main__":
    main()
