"""Run on the Pi: moves the lid servo when web_server.py on another computer detects trash."""
import argparse
import socket

from lid import Lid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    # Channel, angles and timing are set at the top of lid.py.
    parser.add_argument("--port", type=int, default=5006)
    args = parser.parse_args()
    lid = Lid()
    if not lid.ready:
        raise SystemExit("Cannot reach the PCA9685. Check that I2C is enabled and the board is wired.")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.port))
    print(f"Listening for lid commands on UDP port {args.port}...", flush=True)
    try:
        while True:
            command = sock.recvfrom(64)[0].strip()
            if command == b"open":
                lid.open()
            elif command == b"close":
                lid.close()
    except KeyboardInterrupt:
        pass
    finally:
        lid.close()
        sock.close()


if __name__ == "__main__":
    main()
