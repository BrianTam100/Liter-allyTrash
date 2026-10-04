# Demo runbook

**Goal: a demo that doesn't break.** Run through this checklist before judging.

## The demo story (about 3 minutes)

1. **The problem:** people hesitate at the bin and sort wrong. SortRover brings the bins to you.
2. **Drive:** on **Rover controls**, connect and drive the rover to the "person" with
   WASD. Optionally show voice ("go forward", "stop") or hand gestures.
3. **Scan:** on the **Dashboard**, start the scanner and hold up a **plastic water bottle**.
   Show it lock on and the **recycling lid open**. Then a **chip bag** → trash lid.
4. **Honesty beat:** hold up something unsupported (a phone). It says "No sorted item detected"
   instead of guessing.
5. **Confirm the drop:** **Use recognized item → Record drop**, and the points go up.
6. **Impact:** open the **Detection log**: by-bin breakdown, by-item table, confirmed drops.

**Demo items:** only these 4 are recognized: plastic water bottle, cardboard
(box or tube), paper towel, chip bag. Bring two of each, and a plain background helps.

## Startup order

1. **Rover power on** (Arduino and Pi). Put the rover on blocks for the first test.
2. **On the Pi (separate terminals):**
   - `sudo rfcomm watch hci0`
   - `sudo python3 motor_control_bluetooth_camera.py` → wait for "Waiting for Windows Bluetooth connection..."
   - `python3 lid_server.py` → "Listening for lid commands on UDP port 5006"
   - (if using the Pi camera) `python3 pi_camera.py`
3. **On the laptop**, from the repository root:
   ```powershell
   .\BRH_Test\.venv\Scripts\python.exe web_server.py --host 127.0.0.1 --http --enable-lid --lid-host <pi-ip>
   # add: --camera http://<pi-ip>:8080/stream.mjpg   to scan with the Pi camera
   ```
   Wait for "Model ready." in the terminal (first run downloads weights).
4. Open **http://localhost:8000**. On **Rover controls**, pick the **Port** (Auto, or your
   COM number) and press **Connect rover**. The first connect takes a few seconds.

## Pre-demo checklist

- [ ] Scanner status says **Scanner ready** (not "Preparing").
- [ ] Each lid opens and closes (hold each demo item up once).
- [ ] Drive each direction for 1 s; **Stop all motion** works; Space/Esc stops.
- [ ] Detection log shows the test scans.
- [ ] Using TigerData? Ran `web_server.py --init-db` once after the latest pull.
- [ ] Laptop on power, sleep disabled; Pi and laptop on the same Wi-Fi (for lids and camera).
- [ ] Close other apps that use the webcam (Zoom, Teams, Camera).
- [ ] Only **one** server is running (`web_server.py`), and no old desktop drive scripts.

## When something breaks

### Bluetooth won't connect
- **Read the message under the Connect button;** it names the port and the problem.
- **"COMx isn't available":** pick a different port in the **Port** menu. You want the
  outgoing **paired Bluetooth** port, not "incoming".
- **"Could not open COMx":** the Pi side isn't listening. Restart `rfcomm watch hci0`
  and `motor_control_bluetooth_camera.py` on the Pi, then connect again.
- **"Someone else is driving":** another browser or device holds control. Disconnect
  there, or close that tab; it releases within about 2 s.
- **Still stuck:** in Windows Bluetooth settings, remove and re-pair the Pi.
- **Fallback:** switch Connection to **Wi-Fi** (run `motor_control.py` on the Pi instead).
  Keyboard and voice work; gestures don't.

### Pi camera stream fails
- **Check the stream directly:** open `http://<pi-ip>:8080/stream.mjpg` in a browser.
  If it doesn't load, restart `pi_camera.py` and check the Pi's IP.
- **"Turn off hand tracking before using the same connected camera":** gesture mode and
  the server scanner both want laptop webcam 0. Switch the drive mode back to manual.
- **Fallback:** set the scanner source to **This device's camera** (the laptop webcam in
  the browser) or **Upload a photo**. These don't depend on the Pi at all.

### Lids don't move
- The scanner footer says "**Bin lids are controlled manually**": the website was started
  without `--enable-lid`, so restart it with `--enable-lid --lid-host <pi-ip>`.
- `lid_server.py` exits with "Cannot reach the PCA9685": check I2C is enabled and the
  servo board's wiring and power.
- **Lid opens to the wrong spot:** re-run `calibrate_lids.py` on the Pi.
- Lids only open for **live** scans of the 4 demo items, never for photos.
- **Fallback:** open the lid by hand and still confirm the drop on the dashboard.

### Scanner is slow or says "Scanner unavailable"
- On CPU each reading takes about 1.5 s; hold the item still for about 3 readings.
- Use the GPU build of PyTorch, or `TRASH_MODEL=openai/clip-vit-base-patch16` for speed.
- **"Scanner unavailable":** press **Retry scanner**. Check the terminal for the model error.

### Website looks wrong or won't load
- Make sure exactly one server is running on port 8000, then restart it.
- Press Ctrl+F5 once after pulling changes.
