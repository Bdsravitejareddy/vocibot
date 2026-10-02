"""End-to-end benchmark of a running VociBot Enterprise server.

Streams each clinical case (spoken by make_tts_audio.ps1, or any per-line WAV
folder) in real time through the authenticated audio websocket, presses Stop
and waits for the final transcript and note. Measures live delay, transcript
accuracy, time to transcript/note, note quality and peak memory.

    python backend/benchmarks/server_e2e.py --api https://localhost:8443 --ca <ca.crt> \
        --audio backend/benchmarks/tts --label windows-16gb [--concurrency 3] --out results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import platform
import re
import ssl
import statistics
import threading
import time

import httpx
import numpy as np
import soundfile as sf
import websockets

HERE = Path(__file__).parent
CASES = json.loads((HERE / "clinical_note_cases.json").read_text())
GAP_SECONDS = 0.5


def words(text: str) -> list[str]:
    text = re.sub(r"\d+(?:\.\d+)?", lambda m: f" {m.group()} ", text.lower().replace("’", "'"))
    return [w.strip("'.") for w in re.findall(r"[a-z0-9.']+", text) if w.strip("'.")]


def wer(ref: list[str], hyp: list[str]) -> float:
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[len(hyp)] / max(1, len(ref))


def load_case_audio(folder: Path) -> tuple[np.ndarray, list[float]]:
    pieces, ends, offset = [], [], 0.0
    gap = np.zeros(int(16_000 * GAP_SECONDS), dtype=np.float32)
    for wav in sorted(folder.glob("*.wav")):
        audio, rate = sf.read(str(wav), dtype="float32", always_2d=True)
        audio = audio.mean(axis=1)
        if rate != 16_000:
            audio = np.interp(np.arange(0, len(audio), rate / 16_000), np.arange(len(audio)), audio).astype(np.float32)
        pieces += [audio, gap]
        offset += len(audio) / 16_000
        ends.append(offset)
        offset += GAP_SECONDS
    return np.concatenate(pieces), ends


class MemorySampler(threading.Thread):
    """Peak resident memory of the VociBot server and Ollama processes."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak = {"server_mb": 0.0, "ollama_mb": 0.0}
        self.stop_event = threading.Event()

    def run(self) -> None:
        import psutil

        while not self.stop_event.is_set():
            totals = {"server_mb": 0.0, "ollama_mb": 0.0}
            for process in psutil.process_iter(["name", "cmdline", "memory_info"]):
                try:
                    name = (process.info["name"] or "").lower()
                    cmd = " ".join(process.info["cmdline"] or []).lower()
                    rss = process.info["memory_info"].rss / 2**20
                except (psutil.Error, AttributeError, TypeError):
                    continue
                if "vocibot-server" in name or "vocibot_server" in cmd or "uvicorn" in cmd:
                    totals["server_mb"] += rss
                elif name.startswith("ollama"):
                    totals["ollama_mb"] += rss
            for key, value in totals.items():
                self.peak[key] = max(self.peak[key], value)
            self.stop_event.wait(1.0)


def sign_in(api: str, verify, user: str) -> httpx.Client:
    admin = httpx.Client(base_url=api, verify=verify, timeout=60)
    admin.post("/api/auth/setup", json={"username": "admin", "display_name": "Benchmark admin", "password": "benchmark-admin-1"})
    assert admin.post("/api/auth/login", json={"username": "admin", "password": "benchmark-admin-1"}).status_code == 200
    admin.post("/api/admin/users", json={"username": user, "display_name": user, "password": "benchmark-user-1", "role": "clinician", "must_change_password": False})
    client = httpx.Client(base_url=api, verify=verify, timeout=60)
    response = client.post("/api/auth/login", json={"username": user, "password": "benchmark-user-1"})
    assert response.status_code == 200, response.text
    return client


async def run_case(api: str, verify, ssl_context, case: dict, audio_dir: Path, user: str) -> dict:
    from note_quality import score

    client = sign_in(api, verify, user)
    audio, ends = load_case_audio(audio_dir / case["id"])
    consultation = client.post("/api/consultations", json={"patient_id": f"{case['id']}-{time.time_ns()}", "age": 40, "sex": "Female"}).json()
    cookie = f"vocibot_session={client.cookies['vocibot_session']}"
    events: list[tuple[float, str]] = []
    committed: list[str] = []
    ws_url = api.replace("http", "ws", 1) + f"/api/consultations/{consultation['id']}/audio"
    async with websockets.connect(ws_url, additional_headers={"Cookie": cookie, "Origin": api}, ssl=ssl_context, max_size=None, ping_interval=None) as ws:
        await ws.send(json.dumps({"sample_rate": 16_000, "channels": 1, "encoding": "pcm_f32le", "language": "en"}))
        ready = json.loads(await ws.recv())
        started = time.perf_counter()

        async def reader() -> None:
            async for message in ws:
                event = json.loads(message)
                now = time.perf_counter() - started
                if event["type"] == "transcript":
                    committed.append(event["text"])
                    events.append((now, " ".join(committed)))
                elif event["type"] == "partial":
                    events.append((now, " ".join(committed) + " " + event["text"]))
                elif event["type"] == "stopped":
                    return

        listener = asyncio.create_task(reader())
        frame = 1365  # ~85 ms, like a browser's audio callback
        for index in range(0, len(audio), frame):
            await asyncio.sleep(max(0.0, started + (index + frame) / 16_000 - time.perf_counter()))
            await ws.send(audio[index:index + frame].tobytes())
        await ws.send('{"type":"stop"}')
        await asyncio.wait_for(listener, 300)
    stop_at = time.perf_counter()
    client.post(f"/api/consultations/{consultation['id']}/stop")
    transcript_ready = None
    while True:
        state = client.get(f"/api/consultations/{consultation['id']}").json()
        status = state["processing"]["status"]
        if status == "writing_note" and transcript_ready is None:
            transcript_ready = time.perf_counter() - stop_at
        if status not in ("queued", "transcribing", "writing_note"):
            break
        await asyncio.sleep(0.5)
    note_ready = time.perf_counter() - stop_at

    # Live delay per spoken line: when its last three words first appear.
    delays = []
    for line, end in zip(case["lines"], ends):
        tail = " ".join(words(line)[-3:])
        seen = next((t for t, shown in events if tail and tail in " ".join(words(shown))), None)
        if seen is not None:
            delays.append(max(0.0, seen - end))
    reference = words(" ".join(case["lines"]))
    note = score(case, _record(state["record"]))
    return {
        "case": case["id"], "user": user, "audio_s": round(len(audio) / 16_000, 1), "live_preview": ready.get("live_preview"),
        "live_accuracy": round(1 - wer(reference, words(events[-1][1] if events else "")), 4),
        "final_accuracy": round(1 - wer(reference, words(" ".join(s["text"] for s in state["transcript"]))), 4),
        "line_delay_median_s": round(statistics.median(delays), 2) if delays else None,
        "line_delay_max_s": round(max(delays), 2) if delays else None,
        "lines_shown_live": f"{len(delays)}/{len(case['lines'])}",
        "transcript_ready_s": round(transcript_ready, 1) if transcript_ready else None,
        "note_ready_s": round(note_ready, 1), "processing": status,
        "note_facts": f"{note['hits']}/{note['total']}", "note_mistakes": note["violations"],
    }


def _record(data: dict):
    from app.domain.types import ClinicalRecord

    return ClinicalRecord.model_validate(data)


def machine() -> dict:
    import psutil

    info = {"os": platform.platform(), "cpu": platform.processor(), "logical_cpus": os.cpu_count(), "physical_cpus": psutil.cpu_count(logical=False), "ram_gb": round(psutil.virtual_memory().total / 2**30, 1)}
    if os.name == "nt":
        import subprocess

        query = "Get-CimInstance Win32_Processor | Select -First 1 -Expand Name; (Get-CimInstance Win32_PhysicalMemory | Select -First 1 SMBIOSMemoryType,Speed | ConvertTo-Json -Compress)"
        output = subprocess.run(["powershell", "-NoProfile", "-Command", query], capture_output=True, text=True).stdout.strip().splitlines()
        if output:
            info["cpu"] = output[0].strip()
        if len(output) > 1:
            memory = json.loads(output[1])
            info["memory_type"] = {26: "DDR4", 34: "DDR5", 24: "DDR3"}.get(memory.get("SMBIOSMemoryType"), f"type {memory.get('SMBIOSMemoryType')}")
            info["memory_speed_mts"] = memory.get("Speed")
    return info


async def main_async(args) -> dict:
    verify = args.ca if args.ca else True
    ssl_context = ssl.create_default_context(cafile=args.ca) if args.api.startswith("https") else None
    sampler = MemorySampler()
    sampler.start()
    results = []
    cases = [case for case in CASES if (Path(args.audio) / case["id"]).is_dir()]
    if args.concurrency > 1:
        batch = cases[: args.concurrency]
        results = await asyncio.gather(*(run_case(args.api, verify, ssl_context, case, Path(args.audio), f"doctor{index}") for index, case in enumerate(batch, 1)))
    else:
        for case in cases:
            results.append(await run_case(args.api, verify, ssl_context, case, Path(args.audio), "doctor1"))
            print(json.dumps(results[-1]), flush=True)
    sampler.stop_event.set()
    delays = [r["line_delay_median_s"] for r in results if r["line_delay_median_s"] is not None]
    summary = {
        "label": args.label, "concurrency": args.concurrency, "machine": machine(),
        "live_accuracy_mean": round(statistics.mean(r["live_accuracy"] for r in results), 4),
        "final_accuracy_mean": round(statistics.mean(r["final_accuracy"] for r in results), 4),
        "line_delay_median_s": round(statistics.median(delays), 2) if delays else None,
        "line_delay_worst_s": max((r["line_delay_max_s"] or 0) for r in results),
        "transcript_ready_mean_s": round(statistics.mean(r["transcript_ready_s"] or 0 for r in results), 1),
        "note_ready_mean_s": round(statistics.mean(r["note_ready_s"] for r in results), 1),
        "note_ready_max_s": max(r["note_ready_s"] for r in results),
        "note_facts": f"{sum(int(r['note_facts'].split('/')[0]) for r in results)}/{sum(int(r['note_facts'].split('/')[1]) for r in results)}",
        "note_mistakes": sum(len(r["note_mistakes"]) for r in results),
        "peak_server_mb": round(sampler.peak["server_mb"]), "peak_ollama_mb": round(sampler.peak["ollama_mb"]),
    }
    return {"summary": summary, "cases": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--ca")
    parser.add_argument("--audio", default=str(HERE / "tts"))
    parser.add_argument("--label", default="")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--out")
    args = parser.parse_args()
    report = asyncio.run(main_async(args))
    print("SUMMARY " + json.dumps(report["summary"]), flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
