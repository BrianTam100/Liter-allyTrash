"""Grok Voice (speech-to-speech) driver for SortRover.

Talk to Grok over the xAI realtime WebSocket. When you say forward / back /
left / right / stop, Grok calls a local tool that emits the same WASD bytes
the Pi and Arduino already understand.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
import websockets

SAMPLE_RATE = 24000
VOICE_MODEL = "grok-voice-latest"
REALTIME_URL = f"wss://api.x.ai/v1/realtime?model={VOICE_MODEL}"

DIRECTION_TO_CMD = {
    "forward": "w",
    "backward": "s",
    "left": "a",
    "right": "d",
    "stop": "x",
}

DRIVE_TOOL = {
    "type": "function",
    "name": "drive_rover",
    "description": (
        "Drive SortRover immediately. Call this whenever the user wants the "
        "robot to move, turn, or stop. Do not only talk about moving — call "
        "this tool."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["forward", "backward", "left", "right", "stop"],
                "description": (
                    "forward/backward translate. left/right spin in place. "
                    "stop zeros the motors."
                ),
            },
            "duration_seconds": {
                "type": "number",
                "description": (
                    "Optional seconds to keep moving before auto-stop. "
                    "Omit to keep the current motion until another command."
                ),
            },
        },
        "required": ["direction"],
    },
}

INSTRUCTIONS = """# Personality
You are SortRover's voice copilot. You are extremely fast, brief, and action-first.

# Environment
The user talks through a laptop microphone. SortRover is a mecanum-wheel robot.

# Tools
Use drive_rover as soon as the user wants motion. Map everyday phrasing:
- go, go ahead, drive, move forward -> forward
- back up, reverse, go back -> backward
- turn left, rotate left, spin left -> left
- turn right, rotate right, spin right -> right
- stop, halt, freeze, wait, brake -> stop

# Safety
CRITICAL: When the user gives a valid drive command, call the drive_rover tool IMMEDIATELY. Do not speak any confirmation words like "Moving", "Got it", or "Stopped". Only speak out loud if you need to ask a clarifying question (e.g., "Which way?").
# Safety
If the request is ambiguous, ask a short clarifying question. 
When you call drive_rover, verbally confirm the action with a very short phrase like "Moving" or "Done".
"""


class VoiceDrive:
    """Background Grok Voice session. `on_command` receives 'w','a','s','d','z','c', 'x'."""

    def __init__(self, on_command: Callable[[str], None], api_key: Optional[str] = None):
        self.on_command = on_command
        self.api_key = api_key or os.environ.get("XAI_API_KEY", "").strip()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws = None
        self._stop = threading.Event()
        self._play = bytearray()
        self._play_lock = threading.Lock()
        self._hold_timer: Optional[threading.Timer] = None
        self._awaiting_tool_followup = False
        self.ready = threading.Event()
        self.error: Optional[str] = None

    def start(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "Missing XAI_API_KEY. Set it in the environment, then rerun."
            )
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._cancel_hold()
        self._stop.set()
        if self._loop and self._loop.is_running() and self._ws is not None:
            def _close():
                asyncio.create_task(self._ws.close())

            self._loop.call_soon_threadsafe(_close)
        if self._thread:
            self._thread.join(timeout=3)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._session())
        except Exception as exc:
            self.error = str(exc)
            print(f"Grok Voice error: {exc}")
        finally:
            self._loop.close()

    def _cancel_hold(self) -> None:
        if self._hold_timer:
            self._hold_timer.cancel()
            self._hold_timer = None

    def _apply_drive(self, direction: str, duration_seconds: Optional[float]) -> dict:
        cmd = DIRECTION_TO_CMD.get(direction)
        if not cmd:
            return {"ok": False, "error": f"Unknown direction: {direction}"}

        self._cancel_hold()
        self.on_command(cmd)

        hold = None
        if duration_seconds is not None:
            try:
                hold = max(0.1, float(duration_seconds))
            except (TypeError, ValueError):
                hold = None

        if cmd != "x" and hold:
            self._hold_timer = threading.Timer(hold, lambda: self.on_command("x"))
            self._hold_timer.daemon = True
            self._hold_timer.start()

        return {
            "ok": True,
            "direction": direction,
            "command": cmd,
            "duration_seconds": hold,
        }

    async def _session(self) -> None:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        connect_kwargs = {"ssl": True}
        try:
            ws_cm = websockets.connect(
                REALTIME_URL, additional_headers=headers, **connect_kwargs
            )
        except TypeError:
            ws_cm = websockets.connect(
                REALTIME_URL, extra_headers=headers, **connect_kwargs
            )

        async with ws_cm as ws:
            self._ws = ws
            await ws.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {
                            "modalities": ["text", "audio"], # <-- 1. Explicitly request audio back
                            "voice": "eve",
                            "instructions": INSTRUCTIONS,
                            "turn_detection": {"type": "server_vad"},
                            "tools": [DRIVE_TOOL],
                            "input_audio_format": "pcm16",   # <-- 2. Correct format key
                            "output_audio_format": "pcm16",  # <-- 3. Correct format key
                            
                            # REMOVE the entire nested "audio": { ... } block you had before!
                        },
                    }
                )
            )

            mic_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
            loop = asyncio.get_running_loop()

            def on_mic(indata, frames, time_info, status):
                if status:
                    return
                pcm = bytes(indata)

                def enqueue():
                    try:
                        mic_q.put_nowait(pcm)
                    except asyncio.QueueFull:
                        pass

                try:
                    loop.call_soon_threadsafe(enqueue)
                except Exception:
                    pass

            def on_speaker(outdata, frames, time_info, status):
                needed = frames * 2
                with self._play_lock:
                    chunk = self._play[:needed]
                    del self._play[: len(chunk)]
                if len(chunk) < needed:
                    chunk += b"\x00" * (needed - len(chunk))
                outdata[:] = np.frombuffer(chunk, dtype=np.int16).reshape(-1, 1)

            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=int(SAMPLE_RATE * 0.04),
                callback=on_mic,
            ), sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=int(SAMPLE_RATE * 0.04),
                callback=on_speaker,
            ):
                self.ready.set()
                print("Grok Voice is live. Say: go forward, back up, left, right, or stop.")
                sender = asyncio.create_task(self._send_mic(ws, mic_q))
                try:
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        if isinstance(raw, bytes):
                            continue
                        await self._handle_event(ws, json.loads(raw))
                finally:
                    sender.cancel()

    async def _send_mic(self, ws, mic_q: asyncio.Queue[bytes]) -> None:
        while not self._stop.is_set():
            pcm = await mic_q.get()
            await ws.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(pcm).decode("ascii"),
                    }
                )
            )

    def _clear_playback(self) -> None:
        with self._play_lock:
            self._play.clear()

    async def _handle_event(self, ws, event: dict) -> None:
        kind = event.get("type", "")

        if kind == "error":
            print(f"Grok Voice API error: {event.get('error') or event}")
            return

        if kind == "input_audio_buffer.speech_started":
            self._clear_playback()
            return

        if kind == "conversation.item.input_audio_transcription.completed":
            text = event.get("transcript") or event.get("item", {}).get("transcript")
            if text:
                print(f"You: {text}")
            return

        if kind == "response.output_audio_transcript.delta":
            delta = event.get("delta") or ""
            if delta:
                print(delta, end="", flush=True)
            return

        if kind == "response.output_audio_transcript.done":
            print()
            return

        if kind in ("response.output_audio.delta", "response.audio.delta"):
            audio_b64 = event.get("delta") or event.get("audio") or ""
            if not audio_b64:
                return
            pcm = base64.b64decode(audio_b64)
            with self._play_lock:
                self._play.extend(pcm)
            return

        if kind == "response.function_call_arguments.done":
            await self._run_tool(ws, event)
            return

        if kind == "response.done" and self._awaiting_tool_followup:
            self._awaiting_tool_followup = False
            await ws.send(json.dumps({"type": "response.create"}))

    async def _run_tool(self, ws, event: dict) -> None:
        name = event.get("name")
        call_id = event.get("call_id")
        try:
            arguments = json.loads(event.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}

        if name != "drive_rover":
            result = {"ok": False, "error": f"Unknown tool {name}"}
        else:
            direction = str(arguments.get("direction", "")).lower()
            duration = arguments.get("duration_seconds")
            result = self._apply_drive(direction, duration)
            print(f"Voice drive: {result}")

        await ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result),
                    },
                }
            )
        )
        self._awaiting_tool_followup = True
