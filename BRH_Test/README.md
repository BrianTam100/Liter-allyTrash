# Setting up bluetooth to send commands:
## Liter-ally Trash dashboard

The unified dashboard combines the `web` camera/photo classifier with login,
personal bin history, recycling rewards, a TigerData leaderboard, and rover
controls. See [the main README](../README.md) for startup and
[WEBSITE.md](WEBSITE.md) for configuration. Run `python web_server.py` from the
repository root; `python website.py` here serves the same dashboard over HTTP.

Our project has the capability to run on wifi and bluetooth to control the motors for our drivebase. In this guide we go through how to set up bluetooth first* If you were to do just wifi, ensure you have both your pc and the pi on the same network:

## Set up Raspberry PI
* Note when you connect on bluetooth be sure to check settings on what com port is used*.
* Download commands are not included for libraries.
1. First to set up bluetooth we need to enable serial port profile (spp) on the pi so it can be registered as a serial device. To do that we need to open a terminal and run ``sudo nano /etc/systemd/system/dbus-org.bluez.service``. This opens the bluetooth settings and then we need to find this line: ``ExecStart=/usr/lib/bluetooth/bluetoothd`` and add ``-C`` with a space. Right below it also add ``ExecStartPost=/usr/bin/sdptool add SP``. Save the file you opened (ctrl-o, enter, cntrl-X)
2. Afterwards, you run ``sudo systemctl daemon-reload`` and ``sudo systemctl restart bluetooth`` this allows us to connect to the pi.
3. To pair device we type ``bluetoothctl`` and type ``power on``, ``discoverable on`` and ``pairable on``. We can then search for pi on laptop and connect accordingly. Once paired you can exit.
4. To get our raspberry pi to receive data from our laptop/device we run ``sudo rfcomm watch hc0``. This command tells our bluetooth adapter (hci0) to listen for a radio frequency communication (RFCOMM) connection and then make a port when device connects.
5. We then run our python file that takes the data received and tells arduino to power specific motors in specified direction to move ``sudo python3 motor_control_bluetooth_camera.py``

## Set up laptop
1. Open a terminal in the BRH_Test folder and run ``conda create -n rover python=3.11 -y`` and ``conda activate rover``, this is to activate a virtual environment named rover to avoid library issues.
2. Install laptop-side libraries with ``pip install -r requirements.txt``.
3. Once all downloads for libraries are good, running ``python command_bluetooth_camera.py`` should set up interface nicely.
4. Hand signs for angles are set in unit circle format (90 = forward, 0 = right, 180 = left, 270 = back) and you can use wasd or the arrow keys to move forward, backward, left and right (type z or c to turn left and right respectively).
5. After changing `driveController/driveController.ino`, re-upload it to the Arduino. Left/right spins use a different wheel mix than forward/back; the old mix drove the front pair against the rear pair and stalled the X-axis motor.

## Grok Voice drive commands
The laptop scripts can talk to Grok over the xAI Voice (speech-to-speech) API. Grok listens on your microphone, confirms briefly, and calls a local tool that sends the same ``w`` / ``a`` / ``s`` / ``d`` / ``x`` bytes the Pi already forwards to the Arduino.

1. Get an API key from https://console.x.ai and set it in PowerShell before you run a command script:

   ``$env:XAI_API_KEY = "xai-..."``

2. Bluetooth + camera + voice (same COM port as before):

   ``python command_bluetooth_camera.py --port COM8``

3. Wi-Fi keyboard + voice (Pi must already be running ``motor_control.py``):

   ``python command.py --pi-ip 172.20.8.62``

4. Say things like **go forward**, **back up**, **turn left**, **turn right**, **stop**, or **go forward for two seconds**. Keyboard WASD still overrides voice. Pass ``--no-voice`` if you want the old keyboard/camera-only behavior.

Voice motion keeps going until you say stop (or give a duration). That matches the Arduino, which holds the last motor speeds until a new command arrives.
