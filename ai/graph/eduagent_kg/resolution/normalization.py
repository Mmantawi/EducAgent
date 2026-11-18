import re
import unicodedata

ARABIC_DIACRITICS = re.compile(
    "[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]"
)
PUNCTUATION = re.compile(r"[^\w\s/]+", re.UNICODE)
WHITESPACE = re.compile(r"\s+")

# Curated, auditable terminology variants. Additions should be curriculum-reviewed.
KNOWN_TERMINOLOGY_ALIASES: tuple[frozenset[str], ...] = (
    frozenset({"equivalent fractions", "الكسور المتكافئة"}),
    frozenset({"numerator", "البسط"}),
    frozenset({"denominator", "المقام"}),
    frozenset({"greatest common factor", "greatest common divisor", "gcf", "gcd"}),
)


def normalize_text(value: str, *, strip_arabic_diacritics: bool = True) -> str:
    """Conservative Unicode normalization for English and Arabic identity matching."""
    text = unicodedata.normalize("NFKC", value).casefold().replace("ـ", "")
    if strip_arabic_diacritics:
        text = ARABIC_DIACRITICS.sub("", text)
    text = PUNCTUATION.sub(" ", text)
    return WHITESPACE.sub(" ", text).strip()


_TERMINOLOGY_LOOKUP = {
    normalize_text(alias): normalize_text(sorted(group)[0])
    for group in KNOWN_TERMINOLOGY_ALIASES
    for alias in group
}


def terminology_key(value: str) -> str:
    normalized = normalize_text(value)
    return _TERMINOLOGY_LOOKUP.get(normalized, normalized)


def identity_variants(name: str, aliases: list[str]) -> set[str]:
    return {terminology_key(item) for item in [name, *aliases] if item.strip()}
