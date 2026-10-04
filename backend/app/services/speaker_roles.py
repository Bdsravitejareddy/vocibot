"""Who said each line: doctor or patient, recognised from what is said.

The note's checks depend on it: symptoms and history are the patient's
account, while assessment, plan and follow-up must be the doctor's words.
Speech recognition does not separate voices, and one person may voice both
parts, so the local note model reads the whole conversation (in English:
the translation for Telugu or Hindi) and labels each line from its content:
doctors ask, examine, read measurements, give impressions and prescribe;
patients, or relatives speaking for them, describe the illness and answer.
"""

from __future__ import annotations

import json
import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

ROLES = {"D": "DOCTOR", "P": "PATIENT"}


EXAMPLE = (
    "Example:\n0: Good morning, what brings you in?\n1: I have had a headache for two days.\n2: Any vomiting?\n3: No.\n"
    "4: Your blood pressure is 130 over 85.\n5: This looks like a tension headache.\n6: Take paracetamol and come back in a week.\n"
    'Answer: {"0": "D", "1": "P", "2": "D", "3": "P", "4": "D", "5": "D", "6": "D"}\n\n'
)


def _prompt(lines: list[str]) -> str:
    numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(lines))
    return (
        "This is a doctor-patient consultation transcribed by speech recognition. Lines are not labelled with the speaker "
        "and a sentence may be split across lines. Say who speaks each line:\n"
        "D = the doctor: greets and asks what the problem is, asks about symptoms, examines, reads out measurements "
        "(temperature, BP, pulse), gives an impression or diagnosis (\"this looks like\", \"most likely\"), prescribes, orders tests, "
        "gives advice, or arranges follow-up (\"see you again\", \"review in\").\n"
        "P = the patient, or a relative speaking for them: describes complaints and how long, answers the doctor's questions "
        "(\"yes\", \"no\"), mentions past illnesses and medicines already taken, asks what to do.\n"
        "M = the line clearly contains both a question and its answer.\n"
        "An answer follows a question, so the roles usually alternate while the doctor is asking about symptoms.\n"
        + EXAMPLE
        + f"Now answer for these {len(lines)} lines with a JSON object mapping every line number to D, P or M:\n" + numbered
    )


class SpeakerRoleLabeler:
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model

    def label(self, lines: list[str], num_ctx: int | None = None) -> list[str]:
        """DOCTOR, PATIENT or UNKNOWN for each line (all UNKNOWN on failure).

        Pass the note's context size: a different one makes Ollama reload
        the model between the two requests (labelling took 5.5 s, not 3 s).
        """

        if not lines:
            return []
        unknown = ["UNKNOWN"] * len(lines)
        prompt = _prompt(lines)
        own = max(2048, min(settings.ollama_max_context, -(-(len(prompt) // 3 + 12 * len(lines) + 512) // 1024) * 1024))
        options = {"temperature": 0, "num_predict": 12 * len(lines) + 64, "num_ctx": max(own, num_ctx or 0)}
        if settings.ollama_num_gpu >= 0:
            options["num_gpu"] = settings.ollama_num_gpu
        try:
            response = httpx.post(f"{self.base_url}/api/generate", json={"model": self.model, "prompt": prompt, "format": "json", "stream": False, "keep_alive": settings.ollama_keep_alive, "options": options}, timeout=settings.ollama_timeout_seconds)
            response.raise_for_status()
            answer = json.loads(response.json().get("response", "{}"))
        except (httpx.HTTPError, ValueError, AttributeError):
            logger.exception("Speaker role recognition failed; lines stay unlabelled")
            return unknown
        if isinstance(answer, dict) and isinstance(answer.get("roles"), (list, dict)):
            answer = answer["roles"]
        if isinstance(answer, list):
            answer = {str(index): role for index, role in enumerate(answer)} if len(answer) == len(lines) else {}
        if not isinstance(answer, dict):
            return unknown
        return [ROLES.get(str(answer.get(str(index), "")).strip().upper()[:1], "UNKNOWN") for index in range(len(lines))]
