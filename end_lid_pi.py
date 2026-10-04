#!/usr/bin/env python3
"""Run on the lid Pi: stops start_lid_pi.py, lid_server.py, pi_camera.py (even copies started by hand)
and closes both lids.

    python3 end_lid_pi.py
"""
from start_lid_pi import stop_everything

if __name__ == "__main__":
    stop_everything()
