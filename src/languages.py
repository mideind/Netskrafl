"""

    Language, locale and alphabet encapsulation module

    Copyright (C) 2021 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The GNU Affero General Public License, version 3, applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    The classes in this module encapsulate particulars of supported
    languages, including the character set, scores, tiles in the
    initial bag, sorting, etc.

    Currently the only supported language is Icelandic.

    Locale-dependent information is stored in a ContextVar called
    current_locale, defined at the bottom of this module. ContextVars
    were introduced in Python 3.7 and encapsulate thread local state
    in a safe manner, also under asynchronous frameworks. The default
    locale is 'is_IS', i.e. the Icelandic locale with the Icelandic
    alphabet and 'new' tile set. To use another locale during processing
    of a request or otherwise, set the current_locale variable accordingly
    before invoking the request processing code.

"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Type, NamedTuple, Callable, TypeVar, overload

import abc
import functools
from datetime import datetime
from contextvars import ContextVar


_T = TypeVar("_T")


class Alphabet(abc.ABC):

    """ Base class for alphabets particular to languages,
        i.e. the letters used in a game """

    # The following are overridden in derived classes
    order = ""
    upper = ""
    full_order = ""
    full_upper = ""

    def __init__(self):
        # Sanity checks
        assert len(self.order) == len(self.upper)
        assert len(self.full_order) == len(self.full_upper)
        assert len(self.full_order) >= len(self.order)

        # All tiles including wildcard '?'
        self.all_tiles = self.order + "?"

        # Map letters to bits
        self.letter_bit = {letter: 1 << ix for ix, letter in enumerate(self.order)}

        # Ordinal value of first upper case character of alphabet
        self.ord_first = ord(self.full_upper[0])
        assert self.ord_first <= ord(self.full_order[0])
        self.ord_offset = len(self.full_upper)

        # Map both lower and upper case (full) alphabets
        # to consecutive sort values, starting with ord(first_char_of_alphabet)
        self.sortval_map = {
            ord(c): self.ord_first + ix for ix, c in enumerate(self.full_order)
        }
        self.sortval_map.update(
            {ord(c): self.ord_first + ix for ix, c in enumerate(self.full_upper)}
        )

        # Assemble a decoding dictionary where encoded indices are mapped to
        # characters, eventually with a suffixed vertical bar '|' to denote finality
        self.coding = {i: c for i, c in enumerate(self.order)}
        self.coding.update({i | 0x80: c + "|" for i, c in enumerate(self.order)})

    def sortkey(self, lstr: str) -> List[int]:
        """ Key function for locale-based sorting """
        # Note: this only works for lowercase strings that
        # contain letters from the bag (plus '?')
        o = self.all_tiles
        return [o.index(c) for c in lstr if c != "|"]

    def sortval(self, c: str) -> int:
        """ Sort value for any character, with correct ordering
            for the current alphabet, case-insensitive """
        o = ord(c)
        if o < self.ord_first:
            # A 'low' ordinal below our alphabet: return it as-is
            return o
        v = self.sortval_map.get(o)
        if v is not None:
            # Alphabetic character: return its sort value
            return v
        # A 'high' ordinal outside the alphabet: return it
        # after adding an offset so we're sure it doesn't
        # interfere with the alphabet's sort values
        # (note that we know that ord(c) >= self.ord_first)
        return self.ord_offset + o

    def sortkey_nocase(self, lstr: str) -> List[int]:
        """ Return a case-insensitive sort key for the given string """
        return [self.sortval(c) for c in lstr]

    def bit_pattern(self, word: str) -> int:
        """ Return a pattern of bits indicating which letters
            are present in the word """
        bitwise_or: Callable[[int, int], int] = lambda x, y: x | y
        lbit = self.letter_bit
        return functools.reduce(bitwise_or, (lbit[c] for c in word), 0)

    def bit_of(self, c: str) -> int:
        """ Returns the bit corresponding to a character in the alphabet """
        return self.letter_bit[c]

    def all_bits_set(self) -> int:
        """ Return a bit pattern where the bits for all letters
            in the Alphabet are set """
        return 2 ** len(self.order) - 1

    def string_subtract(self, a: str, b: str) -> str:
        """ Subtract all letters in b from a, counting each instance separately """
        # Note that this cannot be done with sets,
        # as they fold multiple letter instances into one
        lcount = [a.count(c) - b.count(c) for c in self.all_tiles]
        return "".join(
            [
                self.all_tiles[ix] * lcount[ix]
                for ix in range(len(lcount))
                if lcount[ix] > 0
            ]
        )

    # noinspection PyUnusedLocal
    @staticmethod
    def format_timestamp(ts: datetime) -> str:
        """ Return a timestamp formatted as a readable string """
        # Currently always returns the full ISO format: YYYY-MM-DD HH:MM:SS
        return ts.isoformat(" ")[0:19]

    # noinspection PyUnusedLocal
    @staticmethod
    def format_timestamp_short(ts: datetime) -> str:
        """ Return a timestamp formatted as a readable string """
        # Returns a short ISO format: YYYY-MM-DD HH:MM
        return ts.isoformat(" ")[0:16]

    @staticmethod
    def tileset_for_locale(locale: str) -> Type[TileSet]:
        """ Return an appropriate tile set for a given locale """
        return TILESETS.get(locale, NewTileSet)


class _IcelandicAlphabet(Alphabet):

    """ The Icelandic alphabet """

    order = "aábdðeéfghiíjklmnoóprstuúvxyýþæö"
    # Upper case version of the order string
    upper = "AÁBDÐEÉFGHIÍJKLMNOÓPRSTUÚVXYÝÞÆÖ"

    # Sort ordering of all valid letters
    full_order = "aábcdðeéfghiíjklmnoópqrstuúvwxyýzþæö"
    # Upper case version of the full order string
    full_upper = "AÁBCDÐEÉFGHIÍJKLMNOÓPQRSTUÚVWXYÝZÞÆÖ"


IcelandicAlphabet = _IcelandicAlphabet()


class _EnglishAlphabet(Alphabet):

    """ The English alphabet """

    order = "abcdefghijklmnopqrstuvwxyz"
    # Upper case version of the order string
    upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    # Sort ordering of all valid letters
    full_order = order
    # Upper case version of the full order string
    full_upper = upper


EnglishAlphabet = _EnglishAlphabet()


class _PolishAlphabet(Alphabet):

    """ The Polish alphabet """

    order = "aąbcćdeęfghijklłmnńoóprsśtuwyzźż"
    upper = "AĄBCĆDEĘFGHIJKLŁMNŃOÓPRSŚTUWYZŹŻ"

    # Sort ordering of all valid letters
    full_order = "aąbcćdeęfghijklłmnńoópqrsśtuvwxyzźż"
    # Upper case version of the full order string
    full_upper = "AĄBCĆDEĘFGHIJKLŁMNŃOÓPQRSŚTUVWXYZŹŻ"


PolishAlphabet = _PolishAlphabet()


class TileSet(abc.ABC):

    """ Abstract base class for tile sets. Concrete classes are found below. """

    # The following will be overridden in derived classes
    alphabet: Alphabet
    scores: Dict[str, int] = dict()
    bag_tiles: List[Tuple[str, int]] = []
    _full_bag = ""

    @classmethod
    def score(cls, tiles: str):
        """ Return the net (plain) score of the given tiles """
        if not tiles:
            return 0
        return sum([cls.scores[tile] for tile in tiles])

    @classmethod
    def full_bag(cls):
        """ Return a full bag of tiles """
        if not cls._full_bag:
            # Cache the bag
            cls._full_bag = "".join([tile * count for (tile, count) in cls.bag_tiles])
        return cls._full_bag

    @classmethod
    def num_tiles(cls):
        """ Return the total number of tiles in this tile set """
        return sum(n for _, n in cls.bag_tiles)


class OldTileSet(TileSet):

    """ The old (original) Icelandic tile set """

    # Letter scores in the old (original) Icelandic tile set

    alphabet = IcelandicAlphabet

    scores = {
        "a": 1,
        "á": 4,
        "b": 6,
        "d": 4,
        "ð": 2,
        "e": 1,
        "é": 6,
        "f": 3,
        "g": 2,
        "h": 3,
        "i": 1,
        "í": 4,
        "j": 5,
        "k": 2,
        "l": 2,
        "m": 2,
        "n": 1,
        "o": 3,
        "ó": 6,
        "p": 8,
        "r": 1,
        "s": 1,
        "t": 1,
        "u": 1,
        "ú": 8,
        "v": 3,
        "x": 10,
        "y": 7,
        "ý": 9,
        "þ": 4,
        "æ": 5,
        "ö": 7,
        "?": 0,
    }

    # Tiles in initial bag, with frequencies

    bag_tiles = [
        ("a", 10),
        ("á", 2),
        ("b", 1),
        ("d", 2),
        ("ð", 5),
        ("e", 6),
        ("é", 1),
        ("f", 3),
        ("g", 4),
        ("h", 2),
        ("i", 8),
        ("í", 2),
        ("j", 1),
        ("k", 3),
        ("l", 3),
        ("m", 3),
        ("n", 8),
        ("o", 3),
        ("ó", 1),
        ("p", 1),
        ("r", 7),
        ("s", 6),
        ("t", 5),
        ("u", 6),
        ("ú", 1),
        ("v", 2),
        ("x", 1),
        ("y", 1),
        ("ý", 1),
        ("þ", 1),
        ("æ", 1),
        ("ö", 1),
        ("?", 2),  # Blank tiles
    ]

    BAG_SIZE: int = 0


# Number of tiles in bag
OldTileSet.BAG_SIZE = OldTileSet.num_tiles()


class NewTileSet(TileSet):

    """ The new Icelandic tile set, created by Skraflfélag Íslands """

    alphabet = IcelandicAlphabet

    # Scores in new Icelandic tile set

    scores = {
        "a": 1,
        "á": 3,
        "b": 5,
        "d": 5,
        "ð": 2,
        "e": 3,
        "é": 7,
        "f": 3,
        "g": 3,
        "h": 4,
        "i": 1,
        "í": 4,
        "j": 6,
        "k": 2,
        "l": 2,
        "m": 2,
        "n": 1,
        "o": 5,
        "ó": 3,
        "p": 5,
        "r": 1,
        "s": 1,
        "t": 2,
        "u": 2,
        "ú": 4,
        "v": 5,
        "x": 10,
        "y": 6,
        "ý": 5,
        "þ": 7,
        "æ": 4,
        "ö": 6,
        "?": 0,
    }

    # New Icelandic tile set

    bag_tiles = [
        ("a", 11),
        ("á", 2),
        ("b", 1),
        ("d", 1),
        ("ð", 4),
        ("e", 3),
        ("é", 1),
        ("f", 3),
        ("g", 3),
        ("h", 1),
        ("i", 7),
        ("í", 1),
        ("j", 1),
        ("k", 4),
        ("l", 5),
        ("m", 3),
        ("n", 7),
        ("o", 1),
        ("ó", 2),
        ("p", 1),
        ("r", 8),
        ("s", 7),
        ("t", 6),
        ("u", 6),
        ("ú", 1),
        ("v", 1),
        ("x", 1),
        ("y", 1),
        ("ý", 1),
        ("þ", 1),
        ("æ", 2),
        ("ö", 1),
        ("?", 2),  # Blank tiles
    ]

    BAG_SIZE: int = 0


# Number of tiles in bag
NewTileSet.BAG_SIZE = NewTileSet.num_tiles()


class EnglishTileSet(TileSet):

    alphabet = EnglishAlphabet

    scores = {
        "e": 1,
        "a": 1,
        "i": 1,
        "o": 1,
        "n": 1,
        "r": 1,
        "t": 1,
        "l": 1,
        "s": 1,
        "u": 1,
        "d": 2,
        "g": 2,
        "b": 3,
        "c": 3,
        "m": 3,
        "p": 3,
        "f": 4,
        "h": 4,
        "v": 4,
        "w": 4,
        "y": 4,
        "k": 5,
        "j": 8,
        "x": 8,
        "q": 10,
        "z": 10,
        "?": 0,
    }

    bag_tiles = [
        ("e", 12),
        ("a", 9),
        ("i", 9),
        ("o", 8),
        ("n", 6),
        ("r", 6),
        ("t", 6),
        ("l", 4),
        ("s", 4),
        ("u", 4),
        ("d", 4),
        ("g", 3),
        ("b", 2),
        ("c", 2),
        ("m", 2),
        ("p", 2),
        ("f", 2),
        ("h", 2),
        ("v", 2),
        ("w", 2),
        ("y", 2),
        ("k", 1),
        ("j", 1),
        ("x", 1),
        ("q", 1),
        ("z", 1),
        ("?", 2),  # Blank tiles
    ]

    BAG_SIZE: int = 0


# Number of tiles in bag
EnglishTileSet.BAG_SIZE = EnglishTileSet.num_tiles()


class NewEnglishTileSet(TileSet):

    """ New English Tile Set - Copyright (C) Miðeind ehf.
        Created by a proprietary method of game simulation.
    """

    alphabet = EnglishAlphabet

    scores = {
        "i": 1,
        "o": 1,
        "s": 1,
        "a": 1,
        "e": 1,
        "t": 2,
        "h": 2,
        "y": 2,
        "m": 2,
        "u": 2,
        "d": 2,
        "n": 2,
        "l": 2,
        "r": 2,
        "p": 2,
        "k": 3,
        "b": 3,
        "g": 3,
        "c": 3,
        "f": 3,
        "w": 4,
        "x": 5,
        "v": 5,
        "j": 6,
        "z": 6,
        "q": 12,
        "?": 0,
    }

    bag_tiles = [
        ("e", 12),
        ("a", 11),
        ("s", 9),
        ("o", 7),
        ("i", 6),
        ("r", 6),
        ("n", 5),
        ("l", 5),
        ("t", 4),
        ("u", 4),
        ("d", 4),
        ("m", 3),
        ("g", 3),
        ("c", 3),
        ("h", 2),
        ("y", 2),
        ("p", 2),
        ("b", 2),
        ("k", 1),
        ("w", 1),
        ("f", 1),
        ("x", 1),
        ("v", 1),
        ("j", 1),
        ("z", 1),
        ("q", 1),
        ("?", 2),  # Blank tiles
    ]

    BAG_SIZE: int = 0


# Number of tiles in bag
NewEnglishTileSet.BAG_SIZE = NewEnglishTileSet.num_tiles()
assert NewEnglishTileSet.BAG_SIZE == EnglishTileSet.BAG_SIZE
# Sanity check tile count
assert sum(t[1] for t in NewEnglishTileSet.bag_tiles) == 100
# Sanity check total points in bag
assert (
    sum(t[1] * NewEnglishTileSet.scores[t[0]] for t in NewEnglishTileSet.bag_tiles)
    == 187
)


class PolishTileSet(TileSet):

    """ Polish tile set """

    alphabet = PolishAlphabet

    scores = {
        "a": 1,
        "ą": 5,
        "b": 3,
        "c": 2,
        "ć": 6,
        "d": 2,
        "e": 1,
        "ę": 5,
        "f": 5,
        "g": 3,
        "h": 3,
        "i": 1,
        "j": 3,
        "k": 3,
        "l": 2,
        "ł": 3,
        "m": 2,
        "n": 1,
        "ń": 7,
        "o": 1,
        "ó": 5,
        "p": 2,
        "r": 1,
        "s": 1,
        "ś": 5,
        "t": 2,
        "u": 3,
        "w": 1,
        "y": 2,
        "z": 1,
        "ź": 9,
        "ż": 5,
        "?": 0,
    }

    bag_tiles = [
        ("a", 9),
        ("ą", 1),
        ("b", 2),
        ("c", 3),
        ("ć", 1),
        ("d", 3),
        ("e", 7),
        ("ę", 1),
        ("f", 1),
        ("g", 2),
        ("h", 2),
        ("i", 8),
        ("j", 2),
        ("k", 3),
        ("l", 3),
        ("ł", 2),
        ("m", 3),
        ("n", 5),
        ("ń", 1),
        ("o", 6),
        ("ó", 1),
        ("p", 3),
        ("r", 4),
        ("s", 4),
        ("ś", 1),
        ("t", 3),
        ("u", 2),
        ("w", 4),
        ("y", 4),
        ("z", 5),
        ("ź", 1),
        ("ż", 1),
        ("?", 2),  # Blank tiles
    ]

    BAG_SIZE: int = 0


# Number of tiles in bag
PolishTileSet.BAG_SIZE = PolishTileSet.num_tiles()
assert PolishTileSet.BAG_SIZE == 100

# Mapping of locale code to tileset

TILESETS: Dict[str, Type[TileSet]] = {
    "is": NewTileSet,
    "is_IS": NewTileSet,
    "pl": PolishTileSet,
    "pl_PL": PolishTileSet,
    "en": NewEnglishTileSet,
    "en_AU": NewEnglishTileSet,
    "en_BZ": NewEnglishTileSet,
    "en_CA": NewEnglishTileSet,
    "en_GB": NewEnglishTileSet,
    "en_IE": NewEnglishTileSet,
    "en_IN": NewEnglishTileSet,
    "en_JM": NewEnglishTileSet,
    "en_MY": NewEnglishTileSet,
    "en_NZ": NewEnglishTileSet,
    "en_PH": NewEnglishTileSet,
    "en_SG": NewEnglishTileSet,
    "en_TT": NewEnglishTileSet,
    "en_US": NewEnglishTileSet,
    "en_ZA": NewEnglishTileSet,
    "en_ZW": NewEnglishTileSet,
}

# Mapping of locale code to alphabet

ALPHABETS: Dict[str, Alphabet] = {
    "is": IcelandicAlphabet,
    "en": EnglishAlphabet,
    "pl": PolishAlphabet,
    # Everything else presently defaults to IcelandicAlphabet
}

# Mapping of locale code to vocabulary,
# also via dictionary subset category ('common' = common vocabulary, etc.)

VOCABULARIES: Dict[str, Dict[str, str]] = {
    "is": {"main": "ordalisti", "common": "amlodi", "medium": "midlungur"},
    "en": {"main": "sowpods"},
    "en_US": {"main": "otcwl2014"},
    "pl": {"main": "osps37"},
    # Everything else presently defaults to 'ordalisti'
}

# Mapping of locale code to board type

BOARD_TYPES: Dict[str, str] = {
    "is": "standard",
    # Everything else defaults to 'explo'
}

# Mapping of locale code to language

LANGUAGES: Dict[str, str] = {
    "is": "is",
    "en_US": "en",
    "en_GB": "en",
    "pl": "pl",
    # Everything else defaults to 'en'
}

# Set of all supported locale codes
SUPPORTED_LOCALES = frozenset(
    TILESETS.keys()
    | ALPHABETS.keys()
    | VOCABULARIES.keys()
    | BOARD_TYPES.keys()
    | LANGUAGES.keys()
)

class Locale(NamedTuple):
    lc: str
    language: str
    alphabet: Alphabet
    tileset: Type[TileSet]
    vocabulary: str
    board_type: str

# Use a context variable (thread local) to store the locale information
# for the current thread, i.e. for the current request
default_locale: Locale = Locale(
    "is_IS", "is", IcelandicAlphabet, NewTileSet, "ordalisti", "standard"
)
current_locale: ContextVar[Locale] = ContextVar("locale", default=default_locale)

current_lc: Callable[[], str] = lambda: current_locale.get().lc
current_language: Callable[[], str] = lambda: current_locale.get().language
current_alphabet: Callable[[], Alphabet] = lambda: current_locale.get().alphabet
current_tileset: Callable[[], Type[TileSet]] = lambda: current_locale.get().tileset
current_vocabulary: Callable[[], str] = lambda: current_locale.get().vocabulary
current_board_type: Callable[[], str] = lambda: current_locale.get().board_type

@overload
def dget(d: Dict[str, _T], key: str) -> Optional[_T]:
    ...

@overload
def dget(d: Dict[str, _T], key: str, default: _T) -> _T:
    ...

def dget(d: Dict[str, _T], key: str, default: Optional[_T] = None) -> Optional[_T]:
    """ Retrieve value from dictionary by locale code, as precisely as possible,
        i.e. trying 'is_IS' first, then 'is', before giving up """
    val = d.get(key)
    while val is None:
        key = "".join(key.split("_")[0:-1])
        if key:
            val = d.get(key)
        else:
            break
    return default if val is None else val


def alphabet_for_locale(lc: str) -> Alphabet:
    """ Return the Alphabet for the given locale """
    return dget(ALPHABETS, lc, default_locale.alphabet)


def tileset_for_locale(lc: str) -> Type[TileSet]:
    """ Return the identifier of the default board type for the given locale """
    return dget(TILESETS, lc, default_locale.tileset)


def vocabulary_for_locale(lc: str, category: str = "main") -> str:
    """ Return the name of the vocabulary for the given locale,
        i.e. 'ordalisti' for is_IS. This can further include a
        category, such as 'common' or 'medium' for constraining
        vocabularies. """
    d = dget(VOCABULARIES, lc)
    if d is None:
        d = dget(VOCABULARIES, default_locale.lc)
        assert d is not None
    return d.get(category, "")


def board_type_for_locale(lc: str) -> str:
    """ Return the identifier of the default board type for the given locale """
    return dget(BOARD_TYPES, lc, "explo")


def language_for_locale(lc: str) -> str:
    """ Return the identifier of the language for the given locale """
    return dget(LANGUAGES, lc, "en")


def set_locale(lc: str) -> None:
    """ Set the current thread's locale context """
    locale = Locale(
        lc=lc,
        language=language_for_locale(lc),
        alphabet=alphabet_for_locale(lc),
        tileset=tileset_for_locale(lc),
        vocabulary=vocabulary_for_locale(lc),
        board_type=board_type_for_locale(lc),
    )
    current_locale.set(locale)


def set_game_locale(lc: str) -> None:
    """ Override the current thread's locale context to correspond to a
        particular game's locale. This doesn't change the UI language,
        which remains tied to the logged-in user. """
    locale = Locale(
        lc=lc,
        language=current_language(),
        alphabet=alphabet_for_locale(lc),
        tileset=tileset_for_locale(lc),
        vocabulary=vocabulary_for_locale(lc),
        board_type=board_type_for_locale(lc),
    )
    current_locale.set(locale)
