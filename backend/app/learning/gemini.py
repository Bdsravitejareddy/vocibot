"""Optional Gemini help for the nightly learning cycle - never during a
consultation, and only at the level the hospital chose (Settings).

Keys live in the macOS Keychain (service "vocibot-gemini", accounts key-1,
key-2, ... in backup order) and are never written to files or logs. Every
request is appended to an audit log on this computer: when, why, the
privacy level, and exactly what was sent.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

import httpx

KEYCHAIN_SERVICE = "vocibot-gemini"
API = "https://generativelanguage.googleapis.com/v1beta"
# Preferred models, best first; the first one the key can use is chosen.
PREFERRED_MODELS = ("gemini-flash-latest", "gemini-3.8-flash", "gemini-3.5-flash", "gemini-2.5-flash")
# Used when the main model's free daily quota is spent (it has its own quota).
FALLBACK_MODEL = "gemini-flash-lite-latest"


class GeminiUnavailable(RuntimeError):
    pass


def keychain_keys(max_keys: int = 8) -> list[str]:
    keys = []
    for index in range(1, max_keys + 1):
        try:
            result = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", f"key-{index}", "-w"], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            break
        if result.returncode != 0:
            continue
        key = "".join(result.stdout.split())  # keys pasted with line breaks
        if key:
            keys.append(key)
    return keys


class GeminiClient:
    def __init__(self, audit_log: Path, keys: list[str] | None = None, timeout: float = 120.0) -> None:
        self.audit_log = audit_log
        self.keys = keys if keys is not None else keychain_keys()
        self.timeout = timeout
        self.model: str | None = None
        self._rejected: set[str] = set()

    def available(self) -> bool:
        return bool(self.keys)

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        """Each key in backup order; a rejected key is skipped from then on.
        When Google is busy (429/500/503) the request is retried with waits."""

        errors = []
        for attempt, wait in enumerate((0, 5, 20, 60)):
            if wait:
                time.sleep(wait)
            busy = False
            for number, key in enumerate(self.keys, 1):
                if key in self._rejected:
                    continue
                try:
                    response = httpx.request(method, f"{API}/{path}", headers={"x-goog-api-key": key, "Content-Type": "application/json"}, json=body, timeout=self.timeout)
                except httpx.HTTPError as error:
                    errors.append(f"key {number}: {type(error).__name__}")
                    busy = True
                    continue
                if response.status_code == 200:
                    return response.json()
                errors.append(f"key {number}: HTTP {response.status_code}")
                if response.status_code in (401, 403):
                    self._rejected.add(key)
                elif response.status_code in (429, 500, 503):
                    busy = True
                elif response.status_code == 404:
                    raise GeminiUnavailable("; ".join(errors))
            if not busy:
                break
        raise GeminiUnavailable("; ".join(errors[-6:]) or "no Gemini keys configured")

    def choose_model(self) -> str:
        if self.model:
            return self.model
        listed = self._call("GET", "models?pageSize=200").get("models", [])
        names = {item["name"].split("/", 1)[-1] for item in listed if "generateContent" in item.get("supportedGenerationMethods", [])}
        self.model = next((name for name in PREFERRED_MODELS if name in names), None) or next((name for name in sorted(names) if "flash" in name), None)
        if not self.model:
            raise GeminiUnavailable(f"no suitable model among {sorted(names)[:10]}")
        return self.model

    def generate(self, prompt: str, *, purpose: str, level: str, json_output: bool = True) -> str:
        try:
            return self._generate(self.choose_model(), prompt, purpose, level, json_output)
        except GeminiUnavailable as error:
            if "HTTP 429" not in str(error) or self.model == FALLBACK_MODEL:
                raise
            self.model = FALLBACK_MODEL
            return self._generate(FALLBACK_MODEL, prompt, purpose, level, json_output)

    def _generate(self, model: str, prompt: str, purpose: str, level: str, json_output: bool) -> str:
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2, **({"responseMimeType": "application/json"} if json_output else {})}}
        entry = {"time": datetime.now(timezone.utc).isoformat(), "purpose": purpose, "level": level, "model": model, "sent": prompt}
        try:
            answer = self._call("POST", f"models/{model}:generateContent", body)
            text = "".join(part.get("text", "") for part in answer.get("candidates", [{}])[0].get("content", {}).get("parts", []))
            entry["received_chars"] = len(text)
            return text
        except GeminiUnavailable as error:
            entry["error"] = str(error)[:300]
            raise
        finally:
            self.audit_log.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_log.open("a", encoding="utf-8") as log:
                log.write(json.dumps(entry, ensure_ascii=False) + "\n")
