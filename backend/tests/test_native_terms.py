from app.domain.types import ClinicalRecord, Speaker, TranscriptSegmentInput
from app.services.native_terms import add_terms_lost_in_translation, find_native_terms


def lines(*texts: str) -> list[TranscriptSegmentInput]:
    return [TranscriptSegmentInput(id=f"c-final-{index}", speaker=Speaker.UNKNOWN, text=text, timestamp="00:00:00", sequence_number=index) for index, text in enumerate(texts)]


def found(*texts: str) -> list[tuple[str, bool]]:
    return [(finding.english, finding.negative) for finding in find_native_terms(lines(*texts))]


def test_the_reference_telugu_consultation() -> None:
    """Doctor's questions are not findings; denials become negatives."""

    assert found(
        "నమస్కారం డాక్టర్ గారు. గత నాలుగు రోజులుగా నాకు విపరీతమైన తలనొప్పి, ఒళ్లు నొప్పులు ఉంటున్నాయి. నిన్న రాత్రి నుంచి జ్వరం కూడా కాస్త ఎక్కువగానే ఉంది.",
        "సరే... జ్వరంతో పాటు చలి లేదా వణుకు ఏమైనా వస్తోందా? గొంతు నొప్పి, దగ్గు లాంటివి ఉన్నాయా?",
        "అవును డాక్టర్. సాయంత్రం వేళల్లో కొంచెం చలిగా అనిపిస్తోంది. దగ్గు అయితే లేదు కానీ... శరీరం మొత్తం బాగా నీరసంగా, అలసటగా అనిపిస్తోంది.",
        "కడుపులో నొప్పి గానీ, వాంతులు అయ్యే భావన గానీ ఏమైనా ఉందా?",
        "కడుపు నొప్పి లేదు కానీ, తిన్న వెంటనే కొంచెం వికారంగా ఉంటోంది డాక్టర్. అసలు ఆకలి కూడా వేయడం లేదు.",
    ) == [("headache", False), ("body aches", False), ("fever", False), ("chills", False), ("cough", True), ("weakness", False), ("tiredness", False), ("stomach pain", True), ("nausea", False), ("loss of appetite", False)]


def test_unpunctuated_speech_recognition_output() -> None:
    # The doctor's question and the patient's answer on one line.
    assert found("గొంతు నోప్పి డగ్గుల ఆంటి వియి ఉన్నాయా పేశంత అవను డాక్టర సాయంత్రం దగ్గు అయితే లేదు కాని") == [("cough", True)]
    assert found("కడుపులో నొప్పి గాని వాంతులు అయే భావం గాని ఎమయినా ఉ") == []
    assert found("నాకు దగ్గు జల్బు చలా ఏక్కు ఉంది అలానే జ్వరము అలానే చలుగుడా బాగ వేస్తుంది") == [("fever", False), ("cold", False), ("cough", False), ("chills", False)]


def test_hindi() -> None:
    assert found("मुझे तीन दिन से बुखार है और खांसी भी है", "क्या उल्टी हो रही है?", "उल्टी नहीं हो रही") == [("fever", False), ("cough", False), ("vomiting", True)]


def test_only_what_the_note_lacks_is_added_and_flagged() -> None:
    record = ClinicalRecord(chief_complaint="cold, fever", presenting_symptoms=["cold", "fever"])
    evidence = {"presenting_symptoms": ["c-en-1"]}
    needs_review: set[str] = set()
    updated = add_terms_lost_in_translation(record, evidence, needs_review, lines("నాకు దగ్గు జలుబు ఉంది, జ్వరం కూడా", "దగ్గు అయితే లేదు", "కడుపు నొప్పి లేదు"))
    assert updated.presenting_symptoms == ["cold", "fever", "cough"]
    assert updated.relevant_negatives == ["no stomach pain"]
    assert evidence["presenting_symptoms"] == ["c-en-1", "c-final-0"]
    assert needs_review == {"presenting_symptoms", "relevant_negatives"}


def test_recognition_misspellings_and_a_question_split_over_two_lines() -> None:
    # The reference consultation as the speech engine actually wrote it.
    assert found(
        "గతనాలుగు రోజులుగా నాకు విప్రీత్మేన త్లనొప్పి ఒల్లు నొప్పులు ఉంటునాయి.",
        "నిన్న రాత్రి నుంచి జవరం కూడా కాస్ తేక్చువగానే ఉంది",
        "గొంతు నొప్పి డగ్గుల ఆంటివి ఉన్నాయా పేశంత అవును డాక్టర సాయంత్రం వేల్లో కొంచించిలిగా అనిపిస్తుంది డగ్గు ఆయితే లేదు కాని",
        "స్రీరణ మొత్తం బాగా నీర్సంగా అలస్తగా అనిపిస్తుంది",
        "కడుపులో నొప్పి గాని,",
        "వాంతులు అయే భావం గాని ఎమయినా ఉందా.",
        "పేసంతా కడుపు నొప్పి లేదు కాని,",
        "తిన్న వెంతనే కొంచేన వికారంగా ఉంతోంది దాక్తర్.",
        "అసలు ఆక్లి చుడా వేడం లేదు.",
    ) == [("headache", False), ("body aches", False), ("fever", False), ("cough", True), ("chills", False), ("weakness", False), ("tiredness", False), ("stomach pain", True), ("nausea", False), ("loss of appetite", False)]


def test_short_words_are_matched_exactly_only() -> None:
    # చాలా ("very") has the consonants of చలి ("chills").
    assert found("నాకు చాలా బాగుంది") == []


def test_hindi_is_matched_exactly_and_translated_contradictions_are_dropped() -> None:
    # मतलब ("meaning") has the consonants of मतली ("nausea").
    assert found("इसका मतलब यह है कि काशी समय की धारा है") == []
    record = ClinicalRecord(presenting_symptoms=["fever"], relevant_negatives=["no fever", "no cough"])
    needs_review: set[str] = set()
    updated = add_terms_lost_in_translation(record, {}, needs_review, lines("నిన్న రాత్రి నుంచి జ్వరం కూడా ఎక్కువగానే ఉంది", "దగ్గు అయితే లేదు"))
    assert updated.relevant_negatives == ["no cough"]
    assert "relevant_negatives" in needs_review


def test_hindi_everyday_head_hurts() -> None:
    # "सर" is both "head" and "sir"; the translation said "Sir, I'm very sad".
    assert found("थोड़ी इशूज़ हो रहे हैं सर में", "सर दुख रहा है मेरा काफ़ी") == [("headache", False)]
    assert found("मोस्टली सर ही दुखता है वो भी") == [("headache", False)]
