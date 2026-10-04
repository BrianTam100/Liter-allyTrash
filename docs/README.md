# SortRover: what we're building

**SortRover** (the website is called **Liter-ally Trash**) is a hackathon project: a
small robot that drives around **carrying a trash can and a recycling can**. You
hold up an item, an AI model running on a laptop works out which bin it belongs in,
and the matching lid opens. A website ties it together: you drive the rover, scan
items, confirm drops, and see what the AI detected.

**Status (2026-10-03):** the live demo and judging are **within a day**. The priority
is a **reliable demo**, not new features. See [demo-runbook.md](demo-runbook.md).

## The pitch in one paragraph

Most people hesitate at the bin. SortRover brings the bins to you: drive it over,
show it your item, and it opens the right lid. It only claims to know four items
(plastic water bottle and cardboard go to recycling; paper towel and chip bag go
to trash), and it labels anything else "No sorted item detected" instead of guessing.
Every reading is logged, so the detection log shows what was scanned, how sure
the model was, and which detections became real drops.

## Team

Two or three people, and **everyone works on everything**; nobody owns one area.
A GitHub contributor is `BrianTam100`.

## Docs in this folder

| File | What it covers |
|------|----------------|
| [architecture.md](architecture.md) | The pieces (laptop, Pi, Arduino, website, database), how they talk, ports, and code map |
| [hardware.md](hardware.md) | Drive base, wheels, Bluetooth/Wi-Fi link, lid servos, cameras |
| [demo-runbook.md](demo-runbook.md) | Demo script, startup order, pre-demo checklist, and fixes for the parts most likely to break |
| [restarting-the-website.md](restarting-the-website.md) | Stopping and starting the server, when a restart is needed, TigerData `--init-db` |

Setup details that already exist elsewhere:

- [../README.md](../README.md): installing and running the website, cameras, HTTPS, lids
- [../BRH_Test/WEBSITE.md](../BRH_Test/WEBSITE.md): website configuration, database, rover controls
- [../BRH_Test/README.md](../BRH_Test/README.md): Raspberry Pi Bluetooth (RFCOMM) setup and voice control

## Known weak spots

These are the most likely to break during a demo:

1. **Pi camera stream:** network stream from `pi_camera.py`; laptop camera conflicts.
2. **Bluetooth connecting:** pairing, `rfcomm watch` on the Pi, and the COM port
   differing per laptop (one teammate's laptop uses COM3, another COM8). Pick it
   in the **Port** menu on Rover controls.
3. **Lid servos:** calibration and the Pi `lid_server.py` being reachable.

Each has a "what to check" section in [demo-runbook.md](demo-runbook.md).
