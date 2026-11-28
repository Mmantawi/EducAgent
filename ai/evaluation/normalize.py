"""Read a child's answer in Egyptian Arabic or English as an exact value.

parse_number reads one bare number. parse_answer also accepts a short lead-in such as
"the answer is" or "الإجابة", a unit ("5 سم"), or multiple-choice letters ("أ، جـ").
Anything that cannot be read with confidence returns None, so callers can report
"cannot check" instead of marking a child wrong because of a guess.

Decisions:
- A comma before exactly three digits groups thousands ("5,328"). Any other comma
  between digits returns None, because "2,4" could be a list or the decimal 2.4.
  The textbooks write decimals with "." and the Arabic decimal mark is "٫".
- Without diacritics, "خمس" can mean 5 or one fifth. It is read as 5.
- "كيلو" alone can mean kilogram or kilometre, so it is not read as a unit.
- In a list of choices, "و" is both a letter and the word "and", so lists that
  contain it need commas.

Not handled yet: clock times ("3:15"), remainders ("11 الباقي 8"), and units
written before the number.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_SYMBOLS = str.maketrans({"٫": ".", "٬": ",", "،": ",", "−": "-", "⁄": "/"})
_ARABIC_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})
_BIDI_MARKS = re.compile("[‎‏؜‪-‮⁦-⁩]")
_DIACRITICS = re.compile("[ً-ٰٟـ]")
_VULGAR_FRACTION = re.compile("([¼½¾⅓⅔⅛])")

_DECIMAL = re.compile(r"^-?(?:[1-9]\d{0,2}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)$")
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
_ARABIC_HUNDREDS = {
    "ميه": 100, "مائه": 100, "مايه": 100, "مئه": 100,
    "ميتين": 200, "مئتين": 200, "مائتين": 200, "مايتين": 200,
    "تلتميه": 300, "تلاتميه": 300, "ثلاثميه": 300, "ثلاثمائه": 300,
    "ربعميه": 400, "اربعميه": 400, "اربعمائه": 400,
    "خمسميه": 500, "خمسمائه": 500,
    "ستميه": 600, "ستمائه": 600,
    "سبعميه": 700, "سبعمائه": 700,
    "تمنميه": 800, "تمانميه": 800, "ثمانمائه": 800, "ثمنمائه": 800,
    "تسعميه": 900, "تسعمائه": 900,
}
_ARABIC_THOUSANDS = {"الف": 1000, "الفين": 2000, "الفان": 2000}
# "تلات تلاف" is 3,000 and "تلات ميه" is 300: (smallest count, largest count, value).
_ARABIC_SCALES = {
    "الاف": (3, 10, 1000), "تلاف": (3, 10, 1000),
    "ميه": (3, 9, 100), "مائه": (3, 9, 100), "مئه": (3, 9, 100), "مايه": (3, 9, 100),
}
_ENGLISH_WHOLE = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_ENGLISH_SCALES = {"hundred": 100, "thousand": 1000}
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
_ARABIC_NUMBER_WORDS = set(_ARABIC_WHOLE) | set(_ARABIC_HUNDREDS) | set(_ARABIC_THOUSANDS)
_ENGLISH_NUMBER_WORDS = set(_ENGLISH_WHOLE) | set(_ENGLISH_SCALES)
_SINGLE_WORD_VALUES = {
    **{word: Fraction(value) for word, value in _ARABIC_WHOLE.items()},
    **{word: Fraction(value) for word, value in _ARABIC_HUNDREDS.items()},
    **{word: Fraction(value) for word, value in _ARABIC_THOUSANDS.items()},
    **{word: Fraction(value) for word, value in _ENGLISH_WHOLE.items()},
    **{word: Fraction(value) for word, value in _ENGLISH_SCALES.items()},
    **_UNIT_FRACTIONS,
    **_OTHER_FRACTIONS,
}
_KNOWN_WORDS = set(_SINGLE_WORD_VALUES) | set(_PLURAL_DENOMINATORS) | set(_ARABIC_SCALES)


@dataclass(frozen=True)
class Unit:
    """A unit and how many of its dimension's base unit it equals."""

    name: str
    dimension: str
    factor: Fraction


_UNITS: Dict[str, Unit] = {}


def _add_unit(name: str, dimension: str, factor: Fraction, spellings: str) -> None:
    unit = Unit(name, dimension, Fraction(factor))
    for spelling in spellings.split():
        _UNITS[spelling] = unit


# Base units: metre, gram, millilitre, Egyptian pound and minute.
_add_unit("mm", "length", Fraction(1, 1000), "mm مم مليمتر ملليمتر مليمترات millimeter millimeters millimetre millimetres")
_add_unit("cm", "length", Fraction(1, 100), "cm سم سنتيمتر سنتيمترات سنتي سانتي centimeter centimeters centimetre centimetres")
_add_unit("m", "length", Fraction(1), "m م متر امتار meter meters metre metres")
_add_unit("km", "length", Fraction(1000), "km كم كيلومتر كيلومترات kilometer kilometers kilometre kilometres")
_add_unit("g", "mass", Fraction(1), "g جم جرام جرامات غرام غرامات gram grams")
_add_unit("kg", "mass", Fraction(1000), "kg كجم كيلوجرام كيلوجرامات كيلوغرام kilogram kilograms")
_add_unit("t", "mass", Fraction(1000000), "طن اطنان ton tons tonne tonnes")
_add_unit("ml", "volume", Fraction(1), "ml مل مليلتر مليلترات ملليلتر milliliter milliliters millilitre millilitres")
_add_unit("l", "volume", Fraction(1000), "l لتر لترات liter liters litre litres")
_add_unit("pound", "money", Fraction(1), "جنيه جنيهات pound pounds le egp")
_add_unit("piaster", "money", Fraction(1, 100), "قرش قروش piaster piasters piastre piastres")
_add_unit("second", "time", Fraction(1, 60), "ثانيه ثواني second seconds sec secs")
_add_unit("minute", "time", Fraction(1), "دقيقه دقائق دقايق minute minutes min mins")
_add_unit("hour", "time", Fraction(60), "ساعه ساعات hour hours hr hrs")
_add_unit("day", "time", Fraction(1440), "يوم ايام day days")

_ARABIC_CHOICES = {"ا": "أ", "ب": "ب", "ج": "جـ", "د": "د", "ه": "هـ", "و": "و"}
_ENGLISH_CHOICES = set("abcdef")

# In normalize_text form. Longer lead-ins are tried first.
_LEAD_INS = tuple(sorted(
    {
        "the answer is", "my answer is", "answer is", "answer", "the result is", "result is",
        "result", "it is", "it's", "its", "is", "equals", "i think it is", "i think it's", "i think",
        "الاجابه هي", "الاجابه", "اجابتي هي", "اجابتي", "الجواب هو", "الجواب", "الناتج هو",
        "الناتج", "النتيجه هي", "النتيجه", "هي", "هو", "يساوي", "تساوي", "بيساوي", "=",
    },
    key=len,
    reverse=True,
))


@dataclass(frozen=True)
class Answer:
    """A child's answer read as a number, a quantity with a unit, or multiple-choice letters."""

    kind: str
    value: Optional[Fraction] = None
    unit: Optional[Unit] = None
    choices: Tuple[str, ...] = ()

    def in_base_unit(self) -> Optional[Fraction]:
        """The value in the dimension's base unit, so 1.5 m and 150 cm compare equal."""
        if self.value is None:
            return None
        return self.value * self.unit.factor if self.unit else self.value


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
    """Return the exact value of a bare number, or None if it cannot be read with confidence."""
    return _parse_normalized_number(normalize_text(text))


def parse_answer(text: str) -> Optional[Answer]:
    """Read a whole answer: a number, a quantity with a unit, or choice letters, after a short lead-in."""
    core = _strip_lead_ins(normalize_text(text))
    if not core:
        return None
    choices = _parse_choices(core)
    if choices:
        return Answer("choice", choices=choices)
    number = _parse_normalized_number(core)
    if number is not None:
        return Answer("number", value=number)
    return _parse_quantity(core)


def _parse_normalized_number(text: str) -> Optional[Fraction]:
    if not text:
        return None
    value = _parse_numeric(text)
    return value if value is not None else _parse_words(text)


def _parse_numeric(text: str) -> Optional[Fraction]:
    if _DECIMAL.match(text):
        return Fraction(text.replace(",", ""))
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


def _english_below_100(tokens: List[str]) -> Optional[int]:
    values = [_ENGLISH_WHOLE.get(token) for token in tokens]
    if not 1 <= len(values) <= 2 or None in values:
        return None
    if len(values) == 1:
        return values[0]
    tens, unit = values
    return tens + unit if tens >= 20 and tens % 10 == 0 and 1 <= unit <= 9 else None


def _english_below_1000(tokens: List[str]) -> Optional[int]:
    if tokens.count("hundred") > 1:
        return None
    if "hundred" not in tokens:
        return _english_below_100(tokens)
    split = tokens.index("hundred")
    count = _english_below_100(tokens[:split]) if split else 1
    rest = _english_below_100(tokens[split + 1:]) if tokens[split + 1:] else 0
    if count is None or rest is None or not 1 <= count <= 9:
        return None
    return count * 100 + rest


def _english_integer(tokens: List[str]) -> Optional[int]:
    if tokens.count("thousand") > 1:
        return None
    if "thousand" not in tokens:
        return _english_below_1000(tokens)
    split = tokens.index("thousand")
    count = _english_below_1000(tokens[:split]) if split else 1
    rest = _english_below_1000(tokens[split + 1:]) if tokens[split + 1:] else 0
    if count is None or rest is None or count == 0:
        return None
    return count * 1000 + rest


def _parse_term(tokens: List[str]) -> Optional[Fraction]:
    if len(tokens) == 1:
        token = tokens[0]
        return _SINGLE_WORD_VALUES.get(token, _parse_numeric(token))
    if all(token in _ENGLISH_NUMBER_WORDS for token in tokens):
        value = _english_integer(tokens)
        if value is not None:
            return Fraction(value)
    if len(tokens) != 2:
        return None

    first, second = tokens
    count = _parse_term([first])
    if count is None or count.denominator != 1 or count <= 0:
        return None
    # "تلات تلاف" is 3,000 and "تلات ميه" is 300.
    if second in _ARABIC_SCALES:
        lowest, highest, scale = _ARABIC_SCALES[second]
        return count * scale if lowest <= count <= highest else None
    # "three quarters", "تلات تربع".
    if second in _PLURAL_DENOMINATORS:
        return count * _PLURAL_DENOMINATORS[second]
    # "one half" is fine, but "two half" is not clear enough to guess.
    if second in _UNIT_FRACTIONS and count == 1:
        return _UNIT_FRACTIONS[second]
    return None


def _is_arabic_word(term: List[str]) -> bool:
    return len(term) == 1 and term[0] in _ARABIC_WHOLE


def _parse_words(text: str) -> Optional[Fraction]:
    terms = _split_terms(text)
    if any(not term for term in terms):
        return None
    # Spoken Arabic often leaves out "و" after hundreds: "تمنميه تمانيه وتمانين".
    expanded: List[List[str]] = []
    for term in terms:
        if len(term) > 1 and _parse_term(term) is None and all(t in _ARABIC_NUMBER_WORDS for t in term):
            expanded.extend([token] for token in term)
        else:
            expanded.append(term)
    values = [_parse_term(term) for term in expanded]
    if any(value is None for value in values):
        return None
    return _combine(values, expanded)


def _combine(values: List[Fraction], terms: List[List[str]]) -> Optional[Fraction]:
    if len(values) == 1:
        return values[0]
    # A fraction can only come last: "two and a half", "اتنين ونص".
    fraction = Fraction(0)
    if 0 < values[-1] < 1:
        fraction, values, terms = values[-1], values[:-1], terms[:-1]
    if any(value.denominator != 1 or value <= 0 for value in values):
        return None

    # Arabic says units before tens: "خمسه وعشرين" is 25.
    merged: List[Fraction] = []
    index = 0
    while index < len(values):
        value = values[index]
        following = values[index + 1] if index + 1 < len(values) else None
        if (
            following is not None and 1 <= value <= 9 and 20 <= following <= 90 and following % 10 == 0
            and _is_arabic_word(terms[index]) and _is_arabic_word(terms[index + 1])
        ):
            merged.append(value + following)
            index += 2
        else:
            merged.append(value)
            index += 1

    # Each part must fill only the places left empty: 1000 + 300 + 25, never 5 + 5.
    total = merged[0]
    for value in merged[1:]:
        place = 10 ** (len(str(int(value))) - 1)
        if value >= total or total % (place * 10) != 0:
            return None
        total += value
    return total + fraction


def _strip_lead_ins(text: str) -> str:
    text = text.strip().rstrip(".!?؟:;").strip()
    changed = True
    while changed and text:
        changed = False
        for lead in _LEAD_INS:
            if text.startswith(lead) and (len(text) == len(lead) or text[len(lead)] in " :=" or lead == "="):
                text = text[len(lead):].lstrip(" :=").strip()
                changed = True
                break
        variable = re.match(r"^[a-zء-ي]\s*=\s*", text)
        if variable:
            text = text[variable.end():].strip()
            changed = True
    return text


def _parse_choices(text: str) -> Optional[Tuple[str, ...]]:
    parts = [part.strip("()[]{}.-: ") for part in re.split(r"[,/]|\s+", text)]
    parts = [part for part in parts if part]
    if not parts:
        return None
    # "أ و جـ" could mean "a and c" or three letters, so a list with "و" needs commas.
    if "و" in parts and len(parts) > 1 and "," not in text:
        return None
    letters = []
    for part in parts:
        if part in _ARABIC_CHOICES:
            letters.append(_ARABIC_CHOICES[part])
        elif part in _ENGLISH_CHOICES:
            letters.append(part)
        else:
            return None
    arabic = {letter in _ARABIC_CHOICES.values() for letter in letters}
    if len(set(letters)) != len(letters) or len(arabic) > 1:
        return None
    return tuple(letters)


def _lookup_unit(text: str) -> Optional[Unit]:
    if text in _UNITS:
        return _UNITS[text]
    # Arabic adds "ا" after a number: "15 كيلومترا".
    if text.endswith("ا") and text[:-1] in _UNITS:
        return _UNITS[text[:-1]]
    return None


def _parse_quantity(text: str) -> Optional[Answer]:
    tokens = text.split()
    candidates = []
    if len(tokens) >= 2:
        candidates.append((" ".join(tokens[:-1]), tokens[-1]))
    if len(tokens) >= 3:
        candidates.append((" ".join(tokens[:-2]), tokens[-2] + tokens[-1]))
    attached = re.match(r"^(.*\d)([a-zء-ي]+)$", text)
    if attached:
        candidates.append((attached.group(1), attached.group(2)))
    for number_text, unit_text in candidates:
        unit = _lookup_unit(unit_text)
        value = _parse_normalized_number(number_text.strip()) if unit else None
        if value is not None:
            return Answer("quantity", value=value, unit=unit)
    return None
