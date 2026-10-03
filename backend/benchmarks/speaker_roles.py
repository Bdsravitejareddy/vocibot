"""Doctor/patient line labelling against hand labels (English benchmark consultations).

    PYTHONPATH=backend .venv/bin/python backend/benchmarks/speaker_roles.py
"""

import json
from pathlib import Path
import time

from app.services.speaker_roles import SpeakerRoleLabeler

HERE = Path(__file__).parent
STANDARD = list("DPDPDPDPDDD")  # fever_uri; the others add a follow-up line by the doctor
LABELS = {
    "fever_uri": STANDARD,
    "diabetes_review": STANDARD + ["D"],
    "child_diarrhoea": STANDARD + ["D"],
    "back_pain": STANDARD + ["D"],
    "asthma": STANDARD + ["D"],
    # Real recognition output; "-" = ambiguous or both speakers, not scored.
    "test13_dizziness_real_asr": list("PPPPPPPPPPP-DPDPDPDPPPPDDPDPPDDPPDDDDD--DD---"),
}


def main() -> None:
    import sys

    cases = {case["id"]: case["lines"] for case in json.loads((HERE / "clinical_note_cases.json").read_text())}
    labeler = SpeakerRoleLabeler(model=sys.argv[1] if len(sys.argv) > 1 else None)
    right = total = 0
    for case_id, truth in LABELS.items():
        lines = cases[case_id]
        assert len(truth) == len(lines), (case_id, len(truth), len(lines))
        started = time.perf_counter()
        predicted = labeler.label(lines)
        scored = [(t, p) for t, p in zip(truth, predicted) if t != "-"]
        hits = sum(("DOCTOR" if t == "D" else "PATIENT") == p for t, p in scored)
        right, total = right + hits, total + len(scored)
        wrong = [(i, lines[i][:50], p) for i, (t, p) in enumerate(zip(truth, predicted)) if t != "-" and ("DOCTOR" if t == "D" else "PATIENT") != p]
        print(f"{case_id:28} {hits}/{len(scored)}  {time.perf_counter() - started:.1f}s  wrong: {wrong}", flush=True)
    print(f"TOTAL {right}/{total} = {right / total:.1%}")


if __name__ == "__main__":
    main()
