"""Symptoms said in Telugu or Hindi that the English translation lost.

The note is written from Whisper's English translation, which drops or merges
symptoms ("దగ్గు జలుబు ... చలి" came out as "a lot of cold and cold": cough and
chills lost).  This scans the original-language transcript for common symptom
words and adds the ones the note does not already mention, flagged for the
doctor's review and cited to the original lines.

Deliberately conservative:
- a clause that is a question ("జ్వరం ఉందా?", "क्या बुखार है?") is the doctor
  asking, not the patient reporting, and is skipped;
- a symptom followed by a negation in its clause ("దగ్గు అయితే లేదు") becomes
  a relevant negative ("no cough"), except where the negation is the symptom
  ("ఆకలి వేయడం లేదు": loss of appetite);
- nothing is added that the note already covers in any field.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from ..domain.types import ClinicalRecord, TranscriptSegmentInput


@dataclass(frozen=True)
class Term:
    english: str
    # Native-script stems; matched as substrings (Telugu and Hindi inflect by suffix).
    stems: tuple[str, ...]
    # Words that show the note already covers it.
    covered_by: tuple[str, ...]
    # "Not X" is itself a symptom (no appetite = loss of appetite).
    negated_is_symptom: bool = False


TERMS: tuple[Term, ...] = (
    Term("fever", ("జ్వర", "జువర", "జొరం", "ఫీవర్", "बुखार", "बुख़ार", "ज्वर"), ("fever", "temperature", "pyrexia", "febrile")),
    Term("cold", ("జలుబు", "జల్బు", "జలబు", "కోల్డ్", "जुकाम", "जुखाम", "ज़ुकाम", "सर्दी"), ("cold", "coryza", "runny nose")),
    Term("cough", ("దగ్గు", "డగ్గు", "కఫ్", "खांसी", "खाँसी", "खासी"), ("cough",)),
    Term("headache", ("తలనొప్పి", "తల నొప్పి", "తలనొప్", "హెడేక్", "హెడ్డేక్", "हेडेक", "सिरदर्द", "सिर दर्द", "सर दर्द", "सरदर्द", "सिर में दर्द"), ("headache", "head ache", "head pain")),
    Term("body aches", ("ఒళ్లు నొప్పు", "ఒళ్ళు నొప్పు", "ఒల్లు నొప్పు", "ఒళ్లునొప్పు", "బాడీ పెయిన్", "बदन दर्द", "शरीर में दर्द", "शरीर दर्द"), ("body ache", "body pain", "aches", "myalgia")),
    Term("stomach pain", ("కడుపు నొప్పి", "కడుపులో నొప్పి", "కడుపునొప్పి", "స్టమక్ పెయిన్", "పొట్ట నొప్పి", "पेट दर्द", "पेट में दर्द"), ("stomach", "abdominal", "abdomen", "belly")),
    Term("back pain", ("వీపు నొప్పి", "నడుము నొప్పి", "నడుం నొప్పి", "బ్యాక్ పెయిన్", "బాక్ పేన్", "कमर दर्द", "पीठ दर्द", "कमर में दर्द"), ("back pain", "backache", "lower back")),
    Term("chills", ("చలి", "చలిగా", "చిలిగా", "చలుగుడా", "చలుగూడా", "చలు గుడా", "వణుకు", "వనుకు", "ठंड लग", "कंपकंपी", "कपकपी"), ("chill", "shiver", "rigor")),
    Term("vomiting", ("వాంతు", "వాంతి", "उल्टी", "उलटी"), ("vomit",)),
    Term("nausea", ("వికార", "जी मिचला", "मतली"), ("nause",)),
    Term("diarrhoea", ("విరేచన", "లూజ్ మోషన్", "दस्त", "लूज मोशन"), ("diarr", "loose")),
    Term("sore throat", ("గొంతు నొప్పి", "గొంతునొప్పి", "గొంతులో నొప్పి", "गले में दर्द", "गला दर्द", "गले में खराश"), ("throat",)),
    Term("chest pain", ("ఛాతీ నొప్పి", "ఛాతి నొప్పి", "చాతి నొప్పి", "सीने में दर्द", "छाती में दर्द", "सीने का दर्द"), ("chest",)),
    Term("dizziness", ("కళ్ళు తిరుగు", "కళ్లు తిరుగు", "తల తిరుగు", "తలతిరుగు", "चक्कर"), ("dizz", "giddi", "vertigo", "spinning")),
    Term("breathlessness", ("ఆయాసం", "ఊపిరి ఆడ", "सांस फूल", "साँस फूल", "सांस लेने में", "साँस लेने में"), ("breath", "dyspn")),
    Term("weakness", ("నీరసం", "నీరసంగా", "कमजोरी", "कमज़ोरी"), ("weak", "fatigue", "tired", "lethargy")),
    Term("tiredness", ("అలసట", "थकान", "थकावट"), ("tired", "fatigue", "exhaust", "weak")),
    Term("loss of appetite", ("ఆకలి", "भूख"), ("appetite",), negated_is_symptom=True),
)

# A clause is a question when it contains one of these (yes/no question verbs,
# "any ...?" and "things like ...?" in Telugu; "kya" in Hindi).
QUESTION_MARKERS = (
    "?", "ఉందా", "ఉన్నాయా", "ఉన్నదా", "వస్తోందా", "వస్తుందా", "వస్తున్నాయా", "అవుతోందా", "అవుతుందా", "అనిపిస్తోందా",
    "ఏమైనా", "ఎమైనా", "ఏమయినా", "ఎమయినా", "ఏమయన", "యమాయన", "ఏమన్నా", "లాంటివి", "క్యా", "क्या", "कोई तकलीफ",
)
# Speech recognition rarely punctuates: a sentence also ends after a Telugu
# yes/no question verb (ఉందా, ఉన్నాయా, వస్తుందా, తీసుకోవాలా ...), so a
# patient's answer on the same line is not mistaken for the question.
QUESTION_VERB = re.compile(r"(\S*(?:ందా|న్నాయా|న్నదా|ోందా|ుందా|ాలా|ారా))(?=\s|$)")
NEGATIONS = ("లేదు", "లేవు", "లేదండి", "లేవండి", "नहीं", "नही")
# Words from the start of a symptom within which its negation must come
# ("కడుపు నొప్పి లేదు", "ఆకలి కూడా వేయడం లేదు").
NEGATION_REACH_WORDS = 5
# Questions are judged per sentence ("గొంతు నొప్పి, దగ్గు లాంటివి ఉన్నాయా?" asks
# about both); negation per clause, which also ends at "but".
SENTENCE_BREAK = re.compile(r"[.!?।]")
CLAUSE_BREAK = re.compile(r"[,;]|\sకానీ\s|\sకాని\s|\sलेकिन\s|\sपर\s|\sमगर\s")


@dataclass(frozen=True)
class Finding:
    english: str
    negative: bool
    segment_id: str


# Speech recognition misspells Telugu and Hindi: vowel signs dropped or
# changed (తలనొప్పి -> త్లనొప్పి), dental/retroflex and aspirated letters
# swapped (దగ్గు -> డగ్గు, ఒళ్లు -> ఒల్లు).  Words with at least three
# consonants are also matched on their consonants alone; shorter ones only
# exactly (చలి "chills" and చాలా "very" share their consonants).
_DROP = {*range(0x0C3E, 0x0C57), 0x0C4D, 0x0C00, 0x0C01, 0x0C02, 0x0C03, 0x0C62, 0x0C63,
         *range(0x093A, 0x0950), 0x0900, 0x0901, 0x0902, 0x0903, 0x093C, 0x0962, 0x0963, 0x200C, 0x200D}
_SAME = {**dict.fromkeys("అఆఇఈఉఊఋఎఏఐఒఓఔ", "అ"), "ఖ": "క", "ఘ": "గ", "ఛ": "చ", "ఝ": "జ", "ట": "త", "ఠ": "త", "థ": "త", "డ": "ద", "ఢ": "ద", "ధ": "ద", "ణ": "న", "ఫ": "ప", "భ": "బ", "ళ": "ల", "శ": "స", "ష": "స", "ఱ": "ర",
         **dict.fromkeys("अआइईउऊऋएऐओऔ", "अ"), "ख": "क", "घ": "ग", "छ": "च", "झ": "ज", "ट": "त", "ठ": "त", "थ": "त", "ड": "द", "ढ": "द", "ध": "द", "ण": "न", "फ": "प", "भ": "ब", "श": "स", "ष": "स", "क़": "क", "ख़": "क", "ज़": "ज", "फ़": "प", "ड़": "द", "ढ़": "द"}
MIN_SKELETON = 3


def _skeleton(text: str) -> tuple[str, list[int]]:
    """Consonants only (spaces dropped), with each one's position in ``text``."""

    letters, positions = [], []
    for index, character in enumerate(text):
        if ord(character) in _DROP or character.isspace() or not character.isalpha():
            continue
        letters.append(_SAME.get(character, character))
        positions.append(index)
    return "".join(letters), positions


def _find(clause: str, term: Term) -> int:
    """Where ``term`` starts in ``clause`` (exactly, or by its consonants), or -1."""

    exact = [clause.find(stem) for stem in term.stems if stem in clause]
    if exact:
        return min(exact)
    skeleton, positions = _skeleton(clause)
    for stem in term.stems:
        stem_skeleton, _ = _skeleton(stem)
        if len(stem_skeleton) >= MIN_SKELETON and (at := skeleton.find(stem_skeleton)) >= 0:
            return positions[at]
    return -1


# A line ending like this continues on the next ("any stomach pain, or" |
# "vomiting?"): recognition splits one question over two lines.
CONTINUES = re.compile(r"(,|గాని|గానీ|లేదా|లేక|या|और|,\s*)\s*$")


def _sentences(transcript: list[TranscriptSegmentInput]) -> list[tuple[str, str]]:
    """(sentence, segment id) pairs; a sentence runs on into the next line
    when the line ends mid-sentence, and is cited to the line it starts on."""

    pending, pending_id, out = "", None, []
    for segment in sorted(transcript, key=lambda item: item.sequence_number):
        text = f"{pending} {segment.text}" if pending else segment.text
        segment_id = pending_id or segment.id
        if CONTINUES.search(segment.text):
            pending, pending_id = text, segment_id
            continue
        pending, pending_id = "", None
        marked = QUESTION_VERB.sub(lambda match: match.group(1) + "?", text)
        out += [(sentence + mark, segment_id) for sentence, mark in zip(SENTENCE_BREAK.split(marked), [*SENTENCE_BREAK.findall(marked), ""])]
    if pending:
        out.append((pending, pending_id))
    return out


def find_native_terms(transcript: list[TranscriptSegmentInput]) -> list[Finding]:
    """Symptoms reported (or denied) in the original-language transcript."""

    findings: list[Finding] = []
    seen: set[tuple[str, bool]] = set()
    for sentence, segment_id in _sentences(transcript):
        if any(marker in sentence for marker in QUESTION_MARKERS):
            continue
        for clause in CLAUSE_BREAK.split(f" {sentence} "):
            starts = {term.english: _find(clause, term) for term in TERMS}
            for term in TERMS:
                position = starts[term.english]
                if position < 0:
                    continue
                # A negation belongs to the nearest symptom before it, within
                # a few words: "చలిగా అనిపిస్తుంది, దగ్గు అయితే లేదు" denies the
                # cough, not the chills.
                following = [start for start in starts.values() if start > position]
                scope = clause[position:min(following, default=len(clause))].split()[:NEGATION_REACH_WORDS]
                negated = any(word.startswith(negation) for word in scope for negation in NEGATIONS)
                negative = negated and not term.negated_is_symptom
                key = (term.english, negative)
                if key in seen or (term.negated_is_symptom and not negated):
                    continue
                seen.add(key)
                findings.append(Finding(term.english, negative, segment_id))
    # A symptom both reported and denied (e.g. "fever earlier, no fever now"):
    # keep the report; the doctor reviews the field.
    reported = {finding.english for finding in findings if not finding.negative}
    return [finding for finding in findings if not (finding.negative and finding.english in reported)]


def _covered(record: ClinicalRecord, term: Term) -> bool:
    text = " ".join(str(value) for value in record.model_dump().values() if value).lower()
    return any(word in text for word in term.covered_by)


def add_terms_lost_in_translation(record: ClinicalRecord, evidence: dict[str, list[str]], needs_review: set[str], original: list[TranscriptSegmentInput]) -> ClinicalRecord:
    """The note plus symptoms only the original-language transcript has.

    Added items go to presenting symptoms or relevant negatives, the field is
    flagged for review, and the original lines are cited.
    """

    terms = {term.english: term for term in TERMS}
    data = record.model_dump()
    for finding in find_native_terms(original):
        if _covered(ClinicalRecord.model_validate(data), terms[finding.english]):
            continue
        field_name = "relevant_negatives" if finding.negative else "presenting_symptoms"
        data[field_name] = [*data[field_name], f"no {finding.english}" if finding.negative else finding.english]
        evidence[field_name] = [*evidence.get(field_name, []), *([finding.segment_id] if finding.segment_id not in evidence.get(field_name, []) else [])]
        needs_review.add(field_name)
    return ClinicalRecord.model_validate(data)
