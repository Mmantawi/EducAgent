"""Read a child's numeric answer in Egyptian Arabic or English as an exact value.

parse_number expects the whole answer to be one number. Anything it cannot read
with confidence returns None, so callers can report "cannot check" instead of
marking a child wrong because of a guess.

Not handled yet: units ("5 cm"), numbers from one hundred up written as words, and
answers inside a sentence ("the answer is 5").

Known ambiguity: without diacritics, words such as "خمس" can mean 5 or one fifth.
They are read as whole numbers.
"""
from __future__ import annotations

import re
import unicodedata
from fractions import Fraction
from typing import List, Optional

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_SYMBOLS = str.maketrans({"٫": ".", "٬": ",", "،": ",", "−": "-", "⁄": "/"})
_ARABIC_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})
_BIDI_MARKS = re.compile("[‎‏؜‪-‮⁦-⁩]")
_DIACRITICS = re.compile("[ً-ٰٟـ]")
_VULGAR_FRACTION = re.compile("([¼½¾⅓⅔⅛])")

_DECIMAL = re.compile(r"^-?(?:[1-9]\d{0,2}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)$")
_FRACTION = re.compile(r"^(-?)(?:(\d+) )?(\d+)/(\d+)$")

# Keys are in normalize_text form, for example ة is written as ه.
_ARABIC_WHOLE = {
    "صفر": 0,
    "واحد": 1, "واحده": 1,
    "اتنين": 2, "اثنين": 2,
    "تلاته": 3, "تلات": 3, "ثلاثه": 3, "ثلاث": 3,
    "اربعه": 4, "اربع": 4,
    "خمسه": 5, "خمس": 5,
    "سته": 6, "ست": 6,
    "سبعه": 7, "سبع": 7,
    "تمانيه": 8, "تمان": 8, "ثمانيه": 8,
    "تسعه": 9, "تسع": 9,
    "عشره": 10, "عشر": 10,
    "حداشر": 11, "اتناشر": 12, "تلتاشر": 13, "اربعتاشر": 14, "خمستاشر": 15,
    "ستاشر": 16, "سبعتاشر": 17, "تمنتاشر": 18, "تسعتاشر": 19,
    "عشرين": 20, "تلاتين": 30, "ثلاثين": 30, "اربعين": 40, "خمسين": 50,
    "ستين": 60, "سبعين": 70, "تمانين": 80, "ثمانين": 80, "تسعين": 90,
}
_ENGLISH_WHOLE = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_UNIT_FRACTIONS = {
    "نص": Fraction(1, 2), "نصف": Fraction(1, 2),
    "تلت": Fraction(1, 3), "ثلث": Fraction(1, 3),
    "ربع": Fraction(1, 4),
    "half": Fraction(1, 2), "third": Fraction(1, 3),
    "quarter": Fraction(1, 4), "fourth": Fraction(1, 4),
}
_OTHER_FRACTIONS = {"تلتين": Fraction(2, 3), "ثلثين": Fraction(2, 3)}
_PLURAL_DENOMINATORS = {
    "تربع": Fraction(1, 4), "ارباع": Fraction(1, 4),
    "halves": Fraction(1, 2), "thirds": Fraction(1, 3),
    "quarters": Fraction(1, 4), "fourths": Fraction(1, 4),
}
_SINGLE_WORD_VALUES = {
    **{word: Fraction(value) for word, value in _ARABIC_WHOLE.items()},
    **{word: Fraction(value) for word, value in _ENGLISH_WHOLE.items()},
    **_UNIT_FRACTIONS,
    **_OTHER_FRACTIONS,
}
_KNOWN_WORDS = set(_SINGLE_WORD_VALUES) | set(_PLURAL_DENOMINATORS)


def normalize_text(text: str) -> str:
    """Unify digits, symbols and Arabic spelling variants, and tidy whitespace."""
    text = _VULGAR_FRACTION.sub(r" \1", text)
    text = unicodedata.normalize("NFKC", text)
    text = _BIDI_MARKS.sub("", text)
    text = _DIACRITICS.sub("", text)
    text = text.translate(_DIGITS).translate(_SYMBOLS).translate(_ARABIC_LETTERS)
    text = re.sub(r"\s*/\s*", "/", text)
    return " ".join(text.casefold().split())


def parse_number(text: str) -> Optional[Fraction]:
    """Return the exact value of an answer, or None if it cannot be read with confidence."""
    normalized = normalize_text(text)
    if not normalized:
        return None
    value = _parse_numeric(normalized)
    return value if value is not None else _parse_words(normalized)


def _parse_numeric(text: str) -> Optional[Fraction]:
    if _DECIMAL.match(text):
        # A comma before exactly three digits groups thousands; any other comma is a decimal mark.
        is_thousands = re.search(r"^-?[1-9]\d{0,2},\d{3}(?:,|\.|$)", text) is not None
        return Fraction(text.replace(",", "") if is_thousands else text.replace(",", "."))
    match = _FRACTION.match(text)
    if match is None or int(match.group(4)) == 0:
        return None
    sign, whole, numerator, denominator = match.groups()
    value = int(whole or 0) + Fraction(int(numerator), int(denominator))
    return -value if sign else value


def _split_terms(text: str) -> List[List[str]]:
    """Split on "and" or the Arabic "و", which is often attached to the next word."""
    terms: List[List[str]] = [[]]
    for token in text.replace("-", " ").split():
        if token in ("a", "an"):
            continue
        if token in ("and", "و"):
            terms.append([])
        elif token.startswith("و") and token not in _KNOWN_WORDS and token[1:] in _KNOWN_WORDS:
            terms.append([token[1:]])
        else:
            terms[-1].append(token)
    return terms


def _parse_term(tokens: List[str]) -> Optional[Fraction]:
    if len(tokens) == 1:
        token = tokens[0]
        return _SINGLE_WORD_VALUES.get(token, _parse_numeric(token))
    if len(tokens) != 2:
        return None

    first, second = tokens
    # English compounds such as "twenty five".
    tens, unit = _ENGLISH_WHOLE.get(first), _ENGLISH_WHOLE.get(second)
    if tens is not None and unit is not None:
        return Fraction(tens + unit) if tens >= 20 and tens % 10 == 0 and 1 <= unit <= 9 else None

    count = _parse_term([first])
    if count is None or count.denominator != 1 or count <= 0:
        return None
    # "three quarters", "تلات تربع".
    if second in _PLURAL_DENOMINATORS:
        return count * _PLURAL_DENOMINATORS[second]
    # "one half" is fine, but "two half" is not clear enough to guess.
    if second in _UNIT_FRACTIONS and count == 1:
        return _UNIT_FRACTIONS[second]
    return None


def _parse_words(text: str) -> Optional[Fraction]:
    terms = _split_terms(text)
    if any(not term for term in terms) or len(terms) > 2:
        return None
    values = [_parse_term(term) for term in terms]
    if any(value is None for value in values):
        return None
    if len(values) == 1:
        return values[0]

    first, second = values
    # Whole number plus fraction: "two and a half", "اتنين ونص".
    if first.denominator == 1 and first >= 0 and 0 < second < 1:
        return first + second
    # Arabic says units before tens: "خمسة وعشرين" is 25.
    both_arabic = all(len(term) == 1 and term[0] in _ARABIC_WHOLE for term in terms)
    if both_arabic and 1 <= first <= 9 and second >= 20 and second % 10 == 0:
        return first + second
    return None
