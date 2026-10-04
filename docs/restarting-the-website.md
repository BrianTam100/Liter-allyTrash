# Restarting the website

The website is one Python process, `web_server.py`, running on the laptop that is
paired with the rover. "Restarting" means stopping that process and starting it again.

## When you need to restart

| You changed... | What to do |
|----------------|------------|
| Any `.py` file (server, rover bridge, classifier, database) | **Restart** |
| `BRH_Test/.env` (database, ports, API keys) | **Restart** |
| Page templates (`web/index.html`, `web/scanner.html`, `BRH_Test/website/templates/*.html`) | **Restart**; the server caches templates |
| `web/style.css` or `web/app.js` only | **No restart**; just refresh the page |
| You pulled code that adds a database table, and you use TigerData | Run `--init-db` once (see below), then restart |

## Quick way: `restart-website.bat`

Double-click `docs\restart-website.bat`, or run it from any terminal. It finds the
repository from where the script sits, so it works on any teammate's laptop. It stops every
running `web_server.py` and waits for port 8000 to free up. Then it starts the server in
that window with the `.venv` Python, or with `python` on PATH if there's no `.venv`.
By default it serves HTTPS on the local Wi-Fi (`--host 0.0.0.0`), so phones and other
laptops on the same network can open `https://<this laptop's Wi-Fi IP>:8000`.

```powershell
docs\restart-website.bat                     # defaults: --host 0.0.0.0 --no-lid (Wi-Fi, HTTPS)
docs\restart-website.bat --host 127.0.0.1 --http --no-lid   # this laptop only
docs\restart-website.bat --host 0.0.0.0 --enable-lid --lid-host <pi-ip> --camera http://<pi-ip>:8080/stream.mjpg
```

Any options you pass replace the defaults. The manual steps are below.

## 1. Stop the running server

In the terminal where it's running, press **Ctrl+C**.

**Lost that terminal?** Stop every copy from PowerShell:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object CommandLine -like '*web_server.py*' |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

Check that nothing is using port 8000 anymore (no output means it's free):

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
```

Each server shows up as **two** `python.exe` processes. That's normal: the `.venv`
launcher starts the real Python underneath it.

## 2. Start it again

From the repository root (`SortRover`):

```powershell
.\BRH_Test\.venv\Scripts\python.exe web_server.py --host 127.0.0.1 --http --no-lid
```

Common variations:

| Goal | Add or change |
|------|---------------|
| Open the lids on the rover | replace `--no-lid` with `--enable-lid --lid-host <pi-ip>` |
| Scan with the Pi camera | `--camera http://<pi-ip>:8080/stream.mjpg` |
| Start fast, load the AI model later | `--no-model-load` (then press **Prepare scanner**) |
| Let phones and other laptops on the Wi-Fi use it | replace `--host 127.0.0.1 --http` with `--host 0.0.0.0` (serves HTTPS, which phones need for their cameras) |

## 3. Check it came back

The terminal should print:

```
Litter-ally Trash: http://localhost:8000
Accounts: local development     (or: TigerData)
Model ready.                    (after the model loads; can take a while on first run)
```

Then open **http://localhost:8000**.

## After a restart

- **The rover is disconnected.** A restart releases the Bluetooth link and the rover stops.
  Press **Connect rover** again; the first connect takes a few seconds. If it fails with
  "remote system is not available", restart the Pi side; see
  [demo-runbook.md](demo-runbook.md#bluetooth-wont-connect).
- **The scanner stops.** Press **Start camera** again once it says **Scanner ready**.
- Open pages keep working; refresh them if anything looks stale.

## Database setup (TigerData only)

If the startup line says `Accounts: TigerData`, new tables aren't created automatically.
After pulling code that adds one (for example the detection log's `lt_detections`),
stop the server and run this once:

```powershell
.\BRH_Test\.venv\Scripts\python.exe web_server.py --init-db
```

It prints `Litter-ally Trash database initialized.` and exits. Then start the server as usual.
The local database (`Accounts: local development`) sets itself up on every start.

## Problems

| Message | Fix |
|---------|-----|
| `Port 8000 is already in use; stop the other server or pass --port.` | Another copy is still running; do step 1 again |
| Page won't load at http://localhost:8000 | The server isn't running, or it crashed; check its terminal for an error |
| Detection log page errors on TigerData | Run `--init-db` (above) |
| Changes don't show up | Restart for `.py` or template changes; for CSS/JS a normal refresh is enough |
