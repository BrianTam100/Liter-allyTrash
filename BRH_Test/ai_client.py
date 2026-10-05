"""Server-only conversation providers. No model has tools or write access."""
import json
import threading
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GEMINI_MODELS = ("gemini-3.7-flash", "gemini-3.8-flash", "gemini-3.1-flash-lite")


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
                           "model": self.health.get(name, {}).get("model"),
                           "attempted_models": self.health.get(name, {}).get("attempted_models", []),
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

    def _record(self, provider, result, cooldown=0, *, model=None, attempted_models=()):
        with self.lock:
            old = self.health.get(provider, {})
            failures = 0 if result == "ok" else old.get("failures", 0) + 1
            self.health[provider] = {"result": result, "failures": failures,
                                     "model": model, "attempted_models": list(attempted_models),
                                     "until": time.monotonic() + (cooldown or (60 if failures >= 3 else 0))}

    def gemini_models(self):
        primary = self.config.get("GEMINI_CHAT_MODEL") or GEMINI_MODELS[0]
        configured = self.config.get("GEMINI_FALLBACK_MODELS", GEMINI_MODELS)
        fallbacks = configured.split(",") if isinstance(configured, str) else configured
        # Normalize and deduplicate so a model is tried only once per request.
        return list(dict.fromkeys(model.strip().removeprefix("models/")
                                  for model in (primary, *fallbacks) if model.strip()))

    def _generate(self, provider, prompt, history, text, image=None):
        turns = [{"role": p["role"], "content": p["content"][:3000]} for p in history[-12:]
                 if p.get("role") in {"user", "assistant"} and isinstance(p.get("content"), str)]
        turns.append({"role": "user", "content": text})
        key = self.config[provider.upper() + "_API_KEY"]
        if provider == "gemini":
            url = "https://generativelanguage.googleapis.com/v1/interactions"
            headers = {"x-goog-api-key": key}
            payload = {"model": self.gemini_models()[0],
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
        models = self.gemini_models() if provider == "gemini" else [payload["model"]]
        attempted_models = []
        # Try each Gemini model once, including after HTTP and response-format errors.
        # Socket timeouts are not a wall-clock deadline.
        for model in models:
            attempted_models.append(model)
            payload["model"] = model
            # 3.8 is listed by Google's v1beta reference, but not the v1 reference.
            model_url = "https://generativelanguage.googleapis.com/v1beta/interactions" if (
                provider == "gemini" and model == "gemini-3.8-flash") else url
            req = Request(model_url, data=json.dumps(payload).encode(),
                          headers={**headers, "Content-Type": "application/json"}, method="POST")
            cooldown = 0
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
                self._record(provider, "ok", model=model, attempted_models=attempted_models)
                return answer[:3000]
            except HTTPError as exc:
                code = exc.code
                exc.close()
                cooldown = 60 if code == 429 else 300 if code in {400, 401, 403, 404} else 0
                reason = "http_" + str(code)
            except (URLError, TimeoutError, OSError, HTTPException):
                reason = "network_error"
            except (ValueError, TypeError, KeyError, AttributeError):
                reason = "invalid_response"
        # A failure pauses Gemini only after the whole model chain was exhausted.
        self._record(provider, reason, cooldown, model=model, attempted_models=attempted_models)
        return None
