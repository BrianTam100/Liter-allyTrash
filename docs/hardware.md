# Hardware

## The rover

- **Drive base:** four **mecanum wheels**, each driven by a stepper motor through a
  CNC shield on an **Arduino**. Mecanum wheels can drive forward and back, spin in
  place, and strafe at any angle.
- **On top:** a **trash can** and a **recycling can**, each with a lid moved by a servo.
- **Raspberry Pi:** relays drive commands to the Arduino over USB, moves the lid servos
  through a PCA9685 board, and can stream its camera to the laptop.

## Arduino drive firmware

`BRH_Test/driveController/driveController.ino` (AccelStepper library). Re-upload it
after any change.

- **Motor axes:** X = front-left, Y = front-right, Z = back-left, A = back-right.
  The `DIR_*` constants flip a motor so that "forward" is consistent.
- **Commands** arrive on serial at 115200 baud:

| Input | Motion |
|-------|--------|
| `w` / `s` | forward / backward |
| `a` / `d` | spin left / spin right (in place) |
| `x` | stop |
| a number, e.g. `90` | drive toward that angle: 90 forward, 0 strafe right, 180 strafe left, 270 back |

- **The Arduino keeps the last speed until it gets a new command.** The stop safety
  therefore lives in the laptop's `rover_bridge.py` (it always sends `x`), not in the
  firmware.
- Spin uses a different wheel mix than forward/back. An older mix fought front
  against back and stalled the X motor.

## Link from laptop to rover

**Bluetooth (preferred; it supports every mode, including hand angles).**
1. On the Pi, enable the serial port profile and run `sudo rfcomm watch hci0`, then
   `sudo python3 motor_control_bluetooth_camera.py`. It forwards `/dev/rfcomm0` to the
   Arduino on `/dev/ttyACM0`. The full steps are in `BRH_Test/README.md`.
2. On Windows, pairing creates two COM ports. The **outgoing** one (linked to the Pi's
   address) is the right one; the incoming one won't work.
3. **COM numbers differ per laptop** (COM3 on one teammate's laptop, COM8 on another's).
   Choose it in the **Port** menu on Rover controls; **Auto** picks the single paired
   outgoing port. Each browser remembers its choice.
4. The website keeps the port open after Disconnect, so reconnecting is instant.
   While the website runs, the desktop `command_bluetooth_camera.py` can't use the port.

**Wi-Fi (fallback; keyboard and voice only).** Run `motor_control.py` on the Pi
(listens on UDP 5005), and set `PI_IP` in `BRH_Test/.env`. UDP gives no delivery
confirmation, and hand angles aren't supported.

## Lids

- **Board:** PCA9685 servo board on the Pi's I2C bus 1, address `0x40`.
- **Channels:** **0 = trash**, **3 = recycling** (`CANS` in `lid.py`).
- **Calibration:** `calibrate_lids.py` (run on the Pi) saves open/closed pulse widths to
  `servo_calibration.json`. Current values: trash 534 µs closed / 1611 µs open;
  recycling 823 µs closed / 1722 µs open.
- **Timing:** a lid stays open `HOLD_SECONDS = 5` after the last matching reading.
- **Running it:** run `lid_server.py` on the Pi (UDP 5006). Start the website with
  `--enable-lid --lid-host <pi-ip>`. Lids are **off by default** (`--no-lid`).
- Only live scans open lids. Photo uploads and drop-off items (batteries,
  electronics) never do.

## Cameras

| Camera | Used for | How |
|--------|----------|-----|
| Browser camera (laptop or phone) | Scanner | "This device's camera"; phones need HTTPS |
| Laptop webcam 0 on the server | Scanner ("Connected / Pi camera") **and** hand-gesture driving | Only one can use it at a time; the site blocks the conflict |
| Pi camera module or USB webcam | Scanner | `python3 pi_camera.py` on the Pi; website `--camera http://<pi-ip>:8080/stream.mjpg` |

The Pi stream has no password, so keep it on the team's own network.

## AI model

- **Model:** CLIP (`openai/clip-vit-large-patch14` by default; set
  `TRASH_MODEL=openai/clip-vit-base-patch16` for a faster, smaller one). Weights cache
  in `.model-cache/`.
- **Speed:** about 50 ms per reading on an RTX 4070 GPU versus about 1.5 s on CPU. Install
  the CUDA build of PyTorch to use the GPU (see the root README).
- **What it reports:** only the 4 `TARGETS` in `classifier.py` (plastic water bottle,
  cardboard → recycling; paper towel, chip bag → trash). Everything else in
  `trash_items.json` is compared too, so other objects come out as "No sorted item detected".
- **The match percentage is a relative score** between candidates, not a probability.
