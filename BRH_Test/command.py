import argparse
import os
import socket
import threading
import time

import keyboard

from voice_control import VoiceDrive

DEFAULT_PI_IP = "172.20.8.62"
UDP_PORT = 5005

voice_lock = threading.Lock()
voice_hold = None  # 'w','a','s','d' while Grok wants motion to continue


def set_voice_command(cmd: str) -> None:
    global voice_hold
    with voice_lock:
        voice_hold = None if cmd == "x" else cmd


def current_voice_command():
    with voice_lock:
        return voice_hold


def main():
    parser = argparse.ArgumentParser(description="Drive SortRover over Wi-Fi with keyboard and Grok Voice.")
    parser.add_argument("--pi-ip", default=os.environ.get("PI_IP", DEFAULT_PI_IP))
    parser.add_argument("--no-voice", action="store_true", help="Keyboard only; skip Grok Voice.")
    args = parser.parse_args()

    print(f"Targeting Raspberry Pi at {args.pi_ip}:{UDP_PORT}")
    print("Hold W/A/S/D (or arrows) to drive. Keyboard always wins over voice.")
    print("Press Q to quit.")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    last_state = "x"
    voice = None

    if not args.no_voice:
        try:
            voice = VoiceDrive(on_command=set_voice_command)
            voice.start()
        except Exception as exc:
            print(f"Voice disabled: {exc}")
            voice = None

    try:
        while True:
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
                print("Exiting...")
                sock.sendto(b"x", (args.pi_ip, UDP_PORT))
                break
            else:
                held = current_voice_command()
                if held:
                    current_state = held

            if current_state != last_state:
                sock.sendto(current_state.encode("utf-8"), (args.pi_ip, UDP_PORT))
                print(f"Sent over Wi-Fi: {current_state}")
                last_state = current_state

            time.sleep(0.05)

    except KeyboardInterrupt:
        pass
    finally:
        try:
            sock.sendto(b"x", (args.pi_ip, UDP_PORT))
        except OSError:
            pass
        if voice:
            voice.stop()
        sock.close()


if __name__ == "__main__":
    main()
