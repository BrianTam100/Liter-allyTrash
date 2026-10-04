"""Server-only conversation providers. No model has tools or write access."""
import json
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AdviceClient:
    def __init__(self, config):
        self.config = config
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(4)
        self.health = {}

    def status(self):
        with self.lock:
            return {name: {"configured": bool(self.config.get(name.upper() + "_API_KEY")),
                           "last_result": self.health.get(name, {}).get("result", "unverified"),
                           "cooldown": self.health.get(name, {}).get("until", 0) > time.monotonic()}
                    for name in ("gemini", "xai")}

    def generate(self, prompt, history, text, *, providers=("gemini", "xai"), image=None):
        if not self.slots.acquire(blocking=False):
            return None
        try:
            for provider in providers:
                if image and provider != "gemini":
                    continue
                if not self.config.get(provider.upper() + "_API_KEY"):
                    continue
                with self.lock:
                    if self.health.get(provider, {}).get("until", 0) > time.monotonic():
                        continue
                answer = self._generate(provider, prompt, history, text, image=image)
                if answer:
                    return answer
            return None
        finally:
            self.slots.release()

    def _record(self, provider, result, cooldown=0):
        with self.lock:
            old = self.health.get(provider, {})
            failures = 0 if result == "ok" else old.get("failures", 0) + 1
            self.health[provider] = {"result": result, "failures": failures,
                                     "until": time.monotonic() + (cooldown or (60 if failures >= 3 else 0))}

    def _generate(self, provider, prompt, history, text, image=None):
        turns = [{"role": p["role"], "content": p["content"][:3000]} for p in history[-12:]
                 if p.get("role") in {"user", "assistant"} and isinstance(p.get("content"), str)]
        turns.append({"role": "user", "content": text})
        key = self.config[provider.upper() + "_API_KEY"]
        if provider == "gemini":
            url = "https://generativelanguage.googleapis.com/v1/interactions"
            headers = {"x-goog-api-key": key}
            payload = {"model": self.config.get("GEMINI_CHAT_MODEL", "gemini-3.7-flash"),
                       "store": False, "system_instruction": prompt,
                       "input": [{"type": "user_input" if p["role"] == "user" else "model_output",
                                  "content": [{"type": "text", "text": p["content"]}]} for p in turns],
                       "generation_config": {"max_output_tokens": 1200, "thinking_level": "low",
                                             "thinking_summaries": "none"}}
            if image:
                payload["input"][-1]["content"].append(image)
        else:
            url = "https://api.x.ai/v1/responses"
            headers = {"Authorization": "Bearer " + key}
            payload = {"model": self.config.get("XAI_CHAT_MODEL", "grok-4.7"), "store": False,
                       "max_output_tokens": 500, "input": [{"role": "system", "content": prompt}, *turns]}
        req = Request(url, data=json.dumps(payload).encode(),
                      headers={**headers, "Content-Type": "application/json"}, method="POST")
        # At most two Gemini attempts and one fallback; socket timeouts are not a wall-clock deadline.
        for attempt in range(2 if provider == "gemini" else 1):
            try:
                with urlopen(req, timeout=8 if provider == "gemini" else 6) as response:
                    raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ValueError("oversize")
                body = json.loads(raw)
                if body.get("status") != "completed":
                    raise ValueError("incomplete")
                outputs = body.get("steps" if provider == "gemini" else "output", [])
                answer = "\n".join(part["text"] for output in outputs
                                   if output.get("type") == ("model_output" if provider == "gemini" else "message")
                                   for part in output.get("content", [])
                                   if part.get("type") == ("text" if provider == "gemini" else "output_text")
                                   and isinstance(part.get("text"), str)).strip()
                if not answer:
                    raise ValueError("empty")
                self._record(provider, "ok")
                return answer[:3000]
            except HTTPError as exc:
                code = exc.code
                exc.close()
                # A quota/auth/configuration error needs time or operator action, not a retry storm.
                if code == 429 or code in {400, 401, 403, 404}:
                    self._record(provider, "http_" + str(code), 60 if code == 429 else 300)
                    return None
                retry = code in {408, 500, 502, 503, 504}
                reason = "http_" + str(code)
            except (URLError, TimeoutError, OSError):
                retry, reason = True, "network_error"
            except (ValueError, TypeError, KeyError, AttributeError):
                retry, reason = False, "invalid_response"
            if not retry or attempt == (1 if provider == "gemini" else 0):
                self._record(provider, reason)
                return None
            time.sleep(0.25)
        return None
