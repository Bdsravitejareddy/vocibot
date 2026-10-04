"""The nightly learning cycle.

1. Local, always: language mix of the last 30 days; medicine values in recent
   notes that could not be resolved.
2. Cloud, only at the level the hospital chose in Settings:
   - "knowledge": Gemini lists common Indian medicine brands and how they are
     said and misheard (no patient data);
   - "snippets": also a de-identified snippet around each unresolved value
     ("... any medicines? $650 since [date] ...") asking which medicine it was.
3. Gate: the changed tips are tested against the current ones (gate.py, plus
   re-checking the unresolved values) and switched on only if something got
   meaningfully better and nothing got worse.
4. A report of every step and number is kept in <learning dir>/reports.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import traceback

from ..config import settings
from .medicines import BARE_STRENGTH, CATEGORIES, WORD, MedicineDictionary, knowledge_prompt, resolve_bare_strength
from .tips import learning_dir

logger = logging.getLogger(__name__)

SEED = Path(__file__).parent / "seed_medicines.json"
LEVELS = ("off", "knowledge", "snippets")
CATEGORIES_PER_NIGHT = 2
MAX_SNIPPETS = 10
TIP_FILES = ("medicines.json", "active.json")


# --- settings ---------------------------------------------------------------

def _setting(key: str, default):
    from ..db import SessionLocal
    from ..models import AppSetting

    with SessionLocal() as session:
        stored = session.get(AppSetting, key)
        return default if stored is None else stored.value


def _store(key: str, value) -> None:
    from ..db import SessionLocal
    from ..models import AppSetting

    with SessionLocal() as session:
        stored = session.get(AppSetting, key)
        if stored is None:
            session.add(AppSetting(key=key, value=value))
        else:
            stored.value = value
        session.commit()


def learning_enabled() -> bool:
    return bool(_setting("learning_enabled", True))


def cloud_level() -> str:
    level = _setting("cloud_learning", settings.cloud_learning)
    return level if level in LEVELS else "off"


def cycle_level() -> str:
    return "disabled" if not learning_enabled() else cloud_level()


def set_preferences(enabled: bool | None = None, level: str | None = None) -> None:
    if level is not None:
        if level not in LEVELS:
            raise ValueError(f"cloud level must be one of {LEVELS}")
        _store("cloud_learning", level)
    if enabled is not None:
        _store("learning_enabled", bool(enabled))


# --- reports ----------------------------------------------------------------

def reports_dir() -> Path:
    return learning_dir() / "reports"


def reports(limit: int = 20) -> list[dict]:
    found = []
    for path in sorted(reports_dir().glob("*.json"), reverse=True)[:limit]:
        try:
            found.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return found


def last_run_time() -> datetime | None:
    latest = reports(1)
    return datetime.fromisoformat(latest[0]["started"]).astimezone().replace(tzinfo=None) if latest else None


def audit(limit: int = 200) -> list[dict]:
    path = learning_dir() / "gemini-audit.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    return [json.loads(line) for line in reversed(lines) if line.strip()]


# --- local steps ------------------------------------------------------------

def _recent_consultations(days: int):
    from ..db import SessionLocal
    from ..models import Consultation

    since = datetime.now(timezone.utc) - timedelta(days=days)
    session = SessionLocal()
    rows = [row for row in session.query(Consultation).all() if row.created_at and row.created_at.replace(tzinfo=row.created_at.tzinfo or timezone.utc) >= since]
    return session, rows


def language_mix(days: int = 30) -> dict:
    session, rows = _recent_consultations(days)
    try:
        counts: dict[str, int] = {}
        for consultation in rows:
            for line in consultation.transcript_segments:
                code = line.language_code or "unknown"
                counts[code] = counts.get(code, 0) + 1
        return {"consultations": len(rows), "lines_by_language": dict(sorted(counts.items(), key=lambda item: -item[1]))}
    finally:
        session.close()


def _known(item: str, dictionary: MedicineDictionary, context: str) -> bool:
    """Whether a medication value names a medicine the dictionary knows."""

    if BARE_STRENGTH.match(item):
        return resolve_bare_strength(item, dictionary, context) is not None
    generics = {str(entry.get("generic", "")).lower() for entry in dictionary.entries}
    for word in WORD.findall(item):
        if dictionary.match(word) or any(word.lower() in generic for generic in generics if len(word) >= 5):
            return True
    return False


def unresolved_values(dictionary: MedicineDictionary, days: int = 7) -> list[dict]:
    """Medication values in recent notes that name no known medicine, with the
    English lines around them (for de-identified snippets)."""

    session, rows = _recent_consultations(days)
    try:
        found = []
        for consultation in rows:
            record = consultation.clinical_record.structured_data_json if consultation.clinical_record else {}
            lines = [line.text for line in getattr(consultation, "translation_segments", None) or []] or [line.text for line in consultation.transcript_segments if (line.language_code or "en") == "en"]
            context = " ".join(lines)
            for item in record.get("medications") or []:
                if isinstance(item, str) and item.strip() and not _known(item, dictionary, context):
                    found.append({"value": item.strip(), "lines": lines})
        return found
    finally:
        session.close()


# --- cloud steps ------------------------------------------------------------

def _json_answer(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
    return json.loads(text)


def knowledge_step(client, dictionary: MedicineDictionary, night: int) -> dict:
    categories = [CATEGORIES[(night * CATEGORIES_PER_NIGHT + index) % len(CATEGORIES)] for index in range(CATEGORIES_PER_NIGHT)]
    added, errors = 0, []
    for category in categories:
        try:
            answer = _json_answer(client.generate(knowledge_prompt(category), purpose=f"medicine list: {category}", level="knowledge"))
            entries = [dict(entry, category=category) for entry in answer.get("medicines", []) if isinstance(entry, dict)]
            added += dictionary.merge(entries)
        except Exception as error:  # noqa: BLE001 - one category failing must not stop the night
            errors.append(f"{category}: {str(error)[:160]}")
    return {"categories": categories, "brands_added": added, "errors": errors}


SNIPPET_PROMPT = (
    "Speech recognition in an Indian clinic wrote \"{value}\" where a medicine was named. De-identified context: \"{snippet}\". "
    "Which medicine brand sold in India was most likely said? Return JSON {{\"brand\": \"...\", \"generic\": \"...\", \"strengths\": [\"...\"], \"confident\": true|false}}; "
    "confident only if the sound and context clearly point to one brand."
)


def snippets_step(client, dictionary: MedicineDictionary, unresolved: list[dict]) -> dict:
    from .deidentify import snippet

    learned, asked, errors = [], 0, []
    for item in unresolved[:MAX_SNIPPETS]:
        value = item["value"]
        if BARE_STRENGTH.match(value):
            continue  # a strength alone is not a way of saying a brand
        text = snippet(item["lines"], value, dictionary) or value
        try:
            asked += 1
            answer = _json_answer(client.generate(SNIPPET_PROMPT.format(value=value, snippet=text), purpose="which medicine was this", level="snippets"))
        except Exception as error:  # noqa: BLE001
            errors.append(str(error)[:160])
            continue
        brand = str(answer.get("brand") or "").strip()
        if not answer.get("confident") or not brand:
            continue
        heard = WORD.findall(value)[:1]
        existing = next((entry for entry in dictionary.entries if entry["brand"].lower() == brand.lower()), None)
        if existing is not None:
            existing.setdefault("spoken", []).extend(word for word in heard if word not in existing["spoken"])
            dictionary.__init__(dictionary.entries)
        else:
            dictionary.merge([{"brand": brand, "generic": answer.get("generic", ""), "strengths": answer.get("strengths") or [], "spoken": heard, "category": "learned from snippets"}])
        learned.append(f"{value} -> {brand}")
    return {"asked": asked, "learned": learned, "errors": errors}


# --- the cycle --------------------------------------------------------------

def _fingerprint(folder: Path) -> str:
    digest = hashlib.sha256()
    for name in TIP_FILES:
        path = folder / name
        digest.update(path.read_bytes() if path.exists() else b"-")
    return digest.hexdigest()


def _pipeline():
    from ..api.audio import build_local_pipeline, restrict_languages

    pipeline = build_local_pipeline()
    restrict_languages(pipeline.stt, {"en", "te", "hi", "ta"})
    return pipeline


def _evaluate(folder: Path, pipeline, cache: dict) -> dict:
    from .gate import evaluate

    key = _fingerprint(folder)
    if cache.get("fingerprint") == key and cache.get("result"):
        return cache["result"]
    return evaluate(folder, pipeline)


def run_cycle(reason: str = "manual") -> dict:
    started = datetime.now().astimezone()
    report: dict = {"started": started.isoformat(timespec="seconds"), "reason": reason, "cloud_level": cloud_level(), "steps": [], "decision": "no change"}
    folder = learning_dir()
    candidate = folder / "candidate"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(candidate, ignore_errors=True)
        candidate.mkdir(parents=True)
        for name in TIP_FILES:
            if (folder / name).exists():
                shutil.copy2(folder / name, candidate / name)
        dictionary = MedicineDictionary.load(candidate / "medicines.json")
        if not dictionary.entries:
            dictionary = MedicineDictionary.load(SEED)
            report["steps"].append({"step": "starting dictionary", "brands": len(dictionary.entries)})

        report["steps"].append({"step": "language mix (30 days)", **language_mix()})
        unresolved = unresolved_values(dictionary)
        report["steps"].append({"step": "unresolved medicine values (7 days)", "count": len(unresolved), "values": [item["value"] for item in unresolved][:20]})

        level = report["cloud_level"]
        if level in ("knowledge", "snippets"):
            from .gemini import GeminiClient

            client = GeminiClient(folder / "gemini-audit.jsonl")
            if not client.available():
                report["steps"].append({"step": "Gemini", "skipped": "no keys in the Keychain"})
            else:
                report["steps"].append({"step": "Gemini knowledge", **knowledge_step(client, dictionary, started.toordinal())})
                if level == "snippets":
                    report["steps"].append({"step": "Gemini de-identified snippets", **snippets_step(client, dictionary, unresolved)})
                report["steps"].append({"step": "Gemini keys", "working": len(client.keys) - len(client._rejected), "configured": len(client.keys)})
        else:
            report["steps"].append({"step": "Gemini", "skipped": "cloud learning is off"})

        dictionary.save(candidate / "medicines.json")
        active = json.loads((candidate / "active.json").read_text(encoding="utf-8")) if (candidate / "active.json").exists() else {}
        active["medicine_corrections"] = True
        (candidate / "active.json").write_text(json.dumps(active, indent=1), encoding="utf-8")

        if _fingerprint(candidate) == _fingerprint(folder):
            report["steps"].append({"step": "gate", "skipped": "nothing new to test"})
        else:
            cache = json.loads((folder / "last-evaluation.json").read_text(encoding="utf-8")) if (folder / "last-evaluation.json").exists() else {}
            pipeline = _pipeline()
            before = _evaluate(folder, pipeline, cache)
            after = _evaluate(candidate, pipeline, {})
            current_on = (folder / "active.json").exists() and json.loads((folder / "active.json").read_text(encoding="utf-8")).get("medicine_corrections")
            before["unresolved_recent"] = len(unresolved_values(MedicineDictionary.load(folder / "medicines.json") if current_on else MedicineDictionary([])))
            after["unresolved_recent"] = len(unresolved_values(dictionary))
            from .gate import meaningful_improvement

            accepted, summary = meaningful_improvement(before, after)
            report.update(before=before, after=after, summary=summary)
            if accepted:
                previous = folder / "previous"
                shutil.rmtree(previous, ignore_errors=True)
                previous.mkdir()
                for name in TIP_FILES:
                    if (folder / name).exists():
                        shutil.copy2(folder / name, previous / name)
                    shutil.copy2(candidate / name, folder / name)
                (folder / "last-evaluation.json").write_text(json.dumps({"fingerprint": _fingerprint(folder), "result": after}), encoding="utf-8")
                report["decision"] = "accepted"
            else:
                (folder / "last-evaluation.json").write_text(json.dumps({"fingerprint": _fingerprint(folder), "result": before}), encoding="utf-8")
                report["decision"] = "rejected"
    except Exception as error:  # noqa: BLE001 - the report records the failure
        logger.exception("Learning cycle failed")
        report["decision"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"[:300]
        report["trace"] = traceback.format_exc()[-1500:]
    finally:
        shutil.rmtree(candidate, ignore_errors=True)
        report["finished"] = datetime.now().astimezone().isoformat(timespec="seconds")
        reports_dir().mkdir(parents=True, exist_ok=True)
        (reports_dir() / f"{started.strftime('%Y-%m-%d-%H%M%S')}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report
