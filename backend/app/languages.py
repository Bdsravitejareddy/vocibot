"""Languages the speech models know, and the clinic's chosen subset.

Auto-detect only chooses among the enabled languages, so short or noisy
stretches of Telugu are not mistaken for, say, Kannada or Arabic.
"""

from sqlalchemy.orm import Session

# Every language Whisper supports; languages of India first.
LANGUAGES: list[tuple[str, str]] = [
    ("en", "English (incl. Indian English)"),
    ("hi", "Hindi"),
    ("te", "Telugu"),
    ("ta", "Tamil"),
    ("kn", "Kannada"),
    ("ml", "Malayalam"),
    ("mr", "Marathi"),
    ("gu", "Gujarati"),
    ("bn", "Bengali"),
    ("pa", "Punjabi"),
    ("ur", "Urdu"),
    ("ne", "Nepali"),
    ("as", "Assamese"),
    ("si", "Sinhala"),
    ("af", "Afrikaans"),
    ("sq", "Albanian"),
    ("am", "Amharic"),
    ("ar", "Arabic"),
    ("hy", "Armenian"),
    ("az", "Azerbaijani"),
    ("ba", "Bashkir"),
    ("eu", "Basque"),
    ("be", "Belarusian"),
    ("bs", "Bosnian"),
    ("br", "Breton"),
    ("bg", "Bulgarian"),
    ("yue", "Cantonese"),
    ("ca", "Catalan"),
    ("zh", "Chinese"),
    ("hr", "Croatian"),
    ("cs", "Czech"),
    ("da", "Danish"),
    ("nl", "Dutch"),
    ("et", "Estonian"),
    ("fo", "Faroese"),
    ("fi", "Finnish"),
    ("fr", "French"),
    ("gl", "Galician"),
    ("ka", "Georgian"),
    ("de", "German"),
    ("el", "Greek"),
    ("ht", "Haitian Creole"),
    ("ha", "Hausa"),
    ("haw", "Hawaiian"),
    ("he", "Hebrew"),
    ("hu", "Hungarian"),
    ("is", "Icelandic"),
    ("id", "Indonesian"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("jw", "Javanese"),
    ("kk", "Kazakh"),
    ("km", "Khmer"),
    ("ko", "Korean"),
    ("lo", "Lao"),
    ("la", "Latin"),
    ("lv", "Latvian"),
    ("ln", "Lingala"),
    ("lt", "Lithuanian"),
    ("lb", "Luxembourgish"),
    ("mk", "Macedonian"),
    ("mg", "Malagasy"),
    ("ms", "Malay"),
    ("mt", "Maltese"),
    ("mi", "Maori"),
    ("mn", "Mongolian"),
    ("my", "Myanmar"),
    ("no", "Norwegian"),
    ("nn", "Nynorsk"),
    ("oc", "Occitan"),
    ("ps", "Pashto"),
    ("fa", "Persian"),
    ("pl", "Polish"),
    ("pt", "Portuguese"),
    ("ro", "Romanian"),
    ("ru", "Russian"),
    ("sa", "Sanskrit"),
    ("sr", "Serbian"),
    ("sn", "Shona"),
    ("sd", "Sindhi"),
    ("sk", "Slovak"),
    ("sl", "Slovenian"),
    ("so", "Somali"),
    ("es", "Spanish"),
    ("su", "Sundanese"),
    ("sw", "Swahili"),
    ("sv", "Swedish"),
    ("tl", "Tagalog"),
    ("tg", "Tajik"),
    ("tt", "Tatar"),
    ("th", "Thai"),
    ("bo", "Tibetan"),
    ("tr", "Turkish"),
    ("tk", "Turkmen"),
    ("uk", "Ukrainian"),
    ("uz", "Uzbek"),
    ("vi", "Vietnamese"),
    ("cy", "Welsh"),
    ("yi", "Yiddish"),
    ("yo", "Yoruba"),
]
LANGUAGE_NAMES = dict(LANGUAGES)
DEFAULT_ENABLED = ["en", "te", "hi", "mr", "gu"]
SETTING_KEY = "enabled_languages"


def enabled_languages(session: Session) -> list[str]:
    from .models import AppSetting

    stored = session.get(AppSetting, SETTING_KEY)
    codes = [code for code in (stored.value if stored else DEFAULT_ENABLED) if code in LANGUAGE_NAMES]
    return codes or list(DEFAULT_ENABLED)


PRIMARY_KEY = "primary_language"


def primary_language(session: Session) -> str | None:
    """The clinic's usual language: detection leans towards it (it wins near
    ties) without excluding the other enabled languages."""

    from .models import AppSetting

    stored = session.get(AppSetting, PRIMARY_KEY)
    code = stored.value if stored else None
    return code if isinstance(code, str) and code in enabled_languages(session) else None


def set_primary_language(session: Session, code: str | None) -> str | None:
    from .models import AppSetting

    if code is not None and code not in enabled_languages(session):
        raise ValueError("The primary language must be one of the enabled languages.")
    stored = session.get(AppSetting, PRIMARY_KEY)
    if code is None:
        if stored is not None:
            session.delete(stored)
    elif stored is None:
        session.add(AppSetting(key=PRIMARY_KEY, value=code))
    else:
        stored.value = code
    session.commit()
    return code


def set_enabled_languages(session: Session, codes: list[str]) -> list[str]:
    from .models import AppSetting

    chosen = list(dict.fromkeys(code for code in codes if code in LANGUAGE_NAMES))
    if not chosen:
        raise ValueError("Choose at least one language.")
    stored = session.get(AppSetting, SETTING_KEY)
    if stored is None:
        session.add(AppSetting(key=SETTING_KEY, value=chosen))
    else:
        stored.value = chosen
    session.commit()
    return chosen
