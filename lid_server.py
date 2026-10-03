"""Run on the Pi: moves the lid servo when web_server.py on another computer detects trash."""
import argparse
import socket

from lid import Lid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    # Channels, calibrated positions and timing are set at the top of lid.py.
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
            # "open Trash" / "open Recyclable"; a bare "open" means the trash can.
            command, _, can = sock.recvfrom(64)[0].decode(errors="replace").strip().partition(" ")
            if command == "open":
                lid.open(can or "Trash")
            elif command == "close":
                lid.close(can or None)
    except KeyboardInterrupt:
        pass
    finally:
        lid.close()
        sock.close()


if __name__ == "__main__":
    main()
