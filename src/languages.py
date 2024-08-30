"""

    Language and locale encapsulation module

    Copyright (C) 2024 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    The classes in this module encapsulate particulars of supported
    languages, including tiles in the initial bag, scores, etc.

    Currently the supported languages are Icelandic, English (UK and US),
    Polish and Norwegian (Bokmål).

    Locale-dependent information is stored in a ContextVar called
    current_locale, defined at the bottom of this module. ContextVars
    were introduced in Python 3.7 and encapsulate thread local state
    in a safe manner, also under asynchronous frameworks.
    
    The default locale for Netskrafl is 'is_IS', i.e. the Icelandic locale
    with the Icelandic alphabet and the 'new' tile set. To use another
    locale during processing of a request or otherwise, set the current_locale
    variable accordingly before invoking the request processing code.

"""

from __future__ import annotations

from typing import (
    Dict,
    List,
    Mapping,
    Optional,
    Tuple,
    Type,
    NamedTuple,
    Callable,
    TypeVar,
    overload,
)

import abc
import functools
from contextvars import ContextVar

from config import DEFAULT_LOCALE, PROJECT_ID
from alphabets import (
    Alphabet,
    IcelandicAlphabet,
    EnglishAlphabet,
    PolishAlphabet,
    NorwegianAlphabet,
)


_T = TypeVar("_T")

DEFAULT_LANGUAGE = "is_IS" if PROJECT_ID == "netskrafl" else "en_US"
DEFAULT_BOARD_TYPE = "standard" if PROJECT_ID == "netskrafl" else "explo"


class TileSet(abc.ABC):
    """Abstract base class for tile sets. Concrete classes are found below."""

    # The following will be overridden in derived classes
    alphabet: Alphabet
    scores: Dict[str, int] = dict()
    bag_tiles: List[Tuple[str, int]] = []
    _full_bag = ""

    @classmethod
    def score(cls, tiles: str):
        """Return the net (plain) score of the given tiles"""
        if not tiles:
            return 0
        return sum([cls.scores[tile] for tile in tiles])

    @classmethod
    def full_bag(cls):
        """Return a full bag of tiles"""
        if not cls._full_bag:
            # Cache the bag
            cls._full_bag = "".join([tile * count for (tile, count) in cls.bag_tiles])
        return cls._full_bag

    @classmethod
    def num_tiles(cls):
        """Return the total number of tiles in this tile set"""
        return sum(n for _, n in cls.bag_tiles)


class OldTileSet(TileSet):
    """
    The old (original) Icelandic tile set.
    This tile set is awful. We don't recommend using it.
    It is only included here for backwards compatibility.
    """

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
    """
    The new Icelandic tile set, created by Skraflfélag Íslands
    and Miðeind ehf. This tile set is used by default in Netskrafl
    and Explo.
    """

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
    """
    Original ('classic') English tile set. Only included for
    documentation and reference; not used in Explo.
    """

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
    """
    New English Tile Set - Copyright (C) Miðeind ehf.
    This set was created by a proprietary method,
    based on extensive game simulation and optimization.
    THIS TILE SET IS PUBLISHED UNDER THE CC-BY-NC 4.0 LICENSE.
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
    """Polish tile set"""

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


class OriginalNorwegianTileSet(TileSet):
    """
    This tile set is presently not used by Netskrafl or Explo.
    It is only included here for documentation and reference.
    """

    alphabet = NorwegianAlphabet

    scores = {
        "a": 1,
        "b": 4,
        "c": 10,
        "d": 1,
        "e": 1,
        "f": 2,
        "g": 2,
        "h": 3,
        "i": 1,
        "j": 4,
        "k": 2,
        "l": 1,
        "m": 2,
        "n": 1,
        "o": 2,
        "p": 4,
        "r": 1,
        "s": 1,
        "t": 1,
        "u": 4,
        "v": 4,
        "w": 8,
        "y": 6,
        "æ": 6,
        "ø": 5,
        "å": 4,
        "?": 0,
    }

    bag_tiles = [
        ("a", 7),
        ("b", 3),
        ("c", 1),
        ("d", 5),
        ("e", 9),
        ("f", 4),
        ("g", 4),
        ("h", 3),
        ("i", 5),
        ("j", 2),
        ("k", 4),
        ("l", 5),
        ("m", 3),
        ("n", 6),
        ("o", 4),
        ("p", 2),
        ("r", 6),
        ("s", 6),
        ("t", 6),
        ("u", 3),
        ("v", 3),
        ("w", 1),
        ("y", 1),
        ("æ", 1),
        ("ø", 2),
        ("å", 2),
        ("?", 2),  # Blank tiles
    ]

    BAG_SIZE: int = 0


# Number of tiles in bag
OriginalNorwegianTileSet.BAG_SIZE = OriginalNorwegianTileSet.num_tiles()
assert OriginalNorwegianTileSet.BAG_SIZE == 100


class NewNorwegianTileSet(TileSet):
    """
    The new, improved Norwegian tile set was designed
    by Taral Guldahl Seierstad and is used here
    by kind permission. Thanks Taral!
    """

    alphabet = NorwegianAlphabet

    scores = {
        "a": 1,
        "b": 3,
        "c": 8,
        "d": 2,
        "e": 1,
        "f": 4,
        "g": 2,
        "h": 3,
        "i": 1,
        "j": 5,
        "k": 2,
        "l": 1,
        "m": 2,
        "n": 1,
        "o": 2,
        "p": 3,
        "r": 1,
        "s": 1,
        "t": 1,
        "u": 3,
        "v": 3,
        "w": 10,
        "y": 3,
        "æ": 6,
        "ø": 4,
        "å": 3,
        "?": 0,
    }

    bag_tiles = [
        ("a", 11),
        ("b", 3),
        ("c", 1),
        ("d", 4),
        ("e", 12),
        ("f", 2),
        ("g", 3),
        ("h", 3),
        ("i", 5),
        ("j", 2),
        ("k", 4),
        ("l", 5),
        ("m", 2),
        ("n", 5),
        ("o", 4),
        ("p", 2),
        ("r", 6),
        ("s", 4),
        ("t", 5),
        ("u", 4),
        ("v", 3),
        ("w", 1),
        ("y", 2),
        ("æ", 1),
        ("ø", 2),
        ("å", 2),
        ("?", 2),  # Blank tiles
    ]

    BAG_SIZE: int = 0


# Number of tiles in bag
NewNorwegianTileSet.BAG_SIZE = NewNorwegianTileSet.num_tiles()
assert NewNorwegianTileSet.BAG_SIZE == 100


# Mapping of locale code to tileset

TILESETS: Dict[str, Type[TileSet]] = {
    "is": NewTileSet,
    "is_IS": NewTileSet,
    "pl": PolishTileSet,
    "pl_PL": PolishTileSet,
    "nb": NewNorwegianTileSet,
    "nb_NO": NewNorwegianTileSet,
    "no": NewNorwegianTileSet,
    "no_NO": NewNorwegianTileSet,
    "nn": NewNorwegianTileSet,
    "nn_NO": NewNorwegianTileSet,
    "en": NewEnglishTileSet,
    "en_US": NewEnglishTileSet,
    "en_GB": NewEnglishTileSet,
    "en_UK": NewEnglishTileSet,
}

# Mapping of locale code to alphabet

ALPHABETS: Dict[str, Alphabet] = {
    "is": IcelandicAlphabet,
    "en": EnglishAlphabet,
    "pl": PolishAlphabet,
    "no": NorwegianAlphabet,
    "nb": NorwegianAlphabet,
    "nn": NorwegianAlphabet,
    # Everything else presently defaults to IcelandicAlphabet
}

# Mapping of locale code to (main) vocabulary

VOCABULARIES: Dict[str, str] = {
    "is": "ordalisti",
    "en": "sowpods",
    "en_US": "otcwl2014",
    "pl": "osps37",
    "nb": "nsf2023",
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
    "is_IS": "is",
    "en_US": "en_US",
    "en_GB": "en_GB",
    "en_AU": "en_GB",
    "en_BZ": "en_GB",
    "en_CA": "en_GB",
    "en_IE": "en_GB",
    "en_IN": "en_GB",
    "en_JM": "en_GB",
    "en_MY": "en_GB",
    "en_NZ": "en_GB",
    "en_PH": "en_GB",
    "en_SG": "en_GB",
    "en_TT": "en_GB",
    "en_UK": "en_GB",
    "en_ZA": "en_GB",
    "en_ZW": "en_GB",
    "pl": "pl",
    "pl_PL": "pl",
    "nb": "nb",
    "nb_NO": "nb",
    # For generic Norwegian, default to Bokmål
    "no": "nb",
    "no_NO": "nb",
    # Everything else defaults to 'en_US'
}

# Set of all supported locale codes
RECOGNIZED_LOCALES = frozenset(
    TILESETS.keys()
    | ALPHABETS.keys()
    | VOCABULARIES.keys()
    | BOARD_TYPES.keys()
    | LANGUAGES.keys()
)

# Map from recognized locales ('en_ZA', 'no_NO') to the
# currently supported set of game locales ('en_GB', 'nb_NO')
RECOGNIZED_TO_SUPPORTED_LOCALES: Mapping[str, str] = {
    "is": "is_IS",  # Icelandic
    "en": "en_US",  # English (US)
    "en_AU": "en_GB",  # English (UK)
    "en_BZ": "en_GB",
    "en_CA": "en_GB",
    "en_IE": "en_GB",
    "en_IN": "en_GB",
    "en_JM": "en_GB",
    "en_MY": "en_GB",
    "en_NZ": "en_GB",
    "en_PH": "en_GB",
    "en_SG": "en_GB",
    "en_TT": "en_GB",
    "en_UK": "en_GB",
    "en_ZA": "en_GB",
    "en_ZW": "en_GB",
    "pl": "pl_PL",  # Polish
    "nb": "nb_NO",  # Norwegian Bokmål
    "no": "nb_NO",  # Norwegian generic
    "nn": "nb_NO",  # Norwegian Nynorsk
    # "ga": "ga_IE",  # Gaeilge/Irish  # TODO: Uncomment this when Irish is supported
}

# Set of all supported game locales
# This set is used for player presence management
# and to group players together into communities
SUPPORTED_LOCALES = frozenset(RECOGNIZED_TO_SUPPORTED_LOCALES.values())


class Locale(NamedTuple):
    lc: str
    language: str
    alphabet: Alphabet
    tileset: Type[TileSet]
    vocabulary: str
    board_type: str


default_locale_netskrafl = Locale(
    "is_IS", "is", IcelandicAlphabet, NewTileSet, "ordalisti", "standard"
)
default_locale_explo = Locale(
    "en_US", "en_US", EnglishAlphabet, NewEnglishTileSet, "otcwl2014", "explo"
)
default_locale = (
    default_locale_netskrafl if PROJECT_ID == "netskrafl" else default_locale_explo
)

# Use a context variable (thread local) to store the locale information
# for the current thread, i.e. for the current request
current_locale: ContextVar[Locale] = ContextVar("locale", default=default_locale)

current_lc: Callable[[], str] = lambda: current_locale.get().lc
current_language: Callable[[], str] = lambda: current_locale.get().language
current_alphabet: Callable[[], Alphabet] = lambda: current_locale.get().alphabet
current_tileset: Callable[[], Type[TileSet]] = lambda: current_locale.get().tileset
current_vocabulary: Callable[[], str] = lambda: current_locale.get().vocabulary
current_board_type: Callable[[], str] = lambda: current_locale.get().board_type


@overload
def dget(d: Dict[str, _T], key: str) -> Optional[_T]: ...


@overload
def dget(d: Dict[str, _T], key: str, default: _T) -> _T: ...


def dget(d: Dict[str, _T], key: str, default: Optional[_T] = None) -> Optional[_T]:
    """Retrieve value from dictionary by locale code, as precisely as possible,
    i.e. trying 'is_IS' first, then 'is', before giving up"""
    val = d.get(key)
    while val is None:
        key = "".join(key.split("_")[0:-1])
        if key:
            val = d.get(key)
        else:
            break
    return default if val is None else val


def alphabet_for_locale(lc: str) -> Alphabet:
    """Return the Alphabet for the given locale"""
    return dget(ALPHABETS, lc, default_locale.alphabet)


def tileset_for_locale(lc: str) -> Type[TileSet]:
    """Return the identifier of the default board type for the given locale"""
    return dget(TILESETS, lc, default_locale.tileset)


def vocabulary_for_locale(lc: str) -> str:
    """Return the name of the main vocabulary for the given locale,
    i.e. 'ordalisti' for is_IS."""
    return dget(VOCABULARIES, lc, default_locale.vocabulary)


def board_type_for_locale(lc: str) -> str:
    """Return the identifier of the default board type for the given locale"""
    return dget(BOARD_TYPES, lc, DEFAULT_BOARD_TYPE)


def language_for_locale(lc: str) -> str:
    """Return the identifier of the language for the given locale"""
    return dget(LANGUAGES, lc, DEFAULT_LANGUAGE)


@functools.lru_cache(maxsize=128)
def to_supported_locale(lc: str) -> str:
    """Return the locale code if it is supported, otherwise its parent
    locale, or the fallback DEFAULT_LOCALE if none of the above is found"""
    if not lc:
        return DEFAULT_LOCALE
    # Defensive programming: we always use underscores in locale codes
    lc = lc.replace("-", "_")
    found = lc in RECOGNIZED_LOCALES
    while not found:
        lc = "".join(lc.split("_")[0:-1])
        if lc:
            found = lc in RECOGNIZED_LOCALES
        else:
            break
    if found:
        # We may be down to a generic locale such as 'en' or 'pl'.
        # Go back to a more specific locale, if available.
        return RECOGNIZED_TO_SUPPORTED_LOCALES.get(lc, lc)
    # Not found at all: return a global generic locale
    return DEFAULT_LOCALE


_LOCALE_CACHE: Dict[Tuple[str, str], Locale] = {}


def set_locale(lc: str) -> None:
    """Set the current thread's locale context"""
    key = (lc, language_for_locale(lc))
    if (locale := _LOCALE_CACHE.get(key)) is None:
        locale = Locale(
            lc=key[0],
            language=key[1],
            alphabet=alphabet_for_locale(lc),
            tileset=tileset_for_locale(lc),
            vocabulary=vocabulary_for_locale(lc),
            board_type=board_type_for_locale(lc),
        )
        _LOCALE_CACHE[key] = locale
    current_locale.set(locale)


def set_game_locale(lc: str) -> None:
    """Override the current thread's locale context to correspond to a
    particular game's locale. This doesn't change the UI language,
    which remains tied to the logged-in user."""
    key = (lc, current_language())
    if (locale := _LOCALE_CACHE.get(key)) is None:
        locale = Locale(
            lc=key[0],
            language=key[1],
            alphabet=alphabet_for_locale(lc),
            tileset=tileset_for_locale(lc),
            vocabulary=vocabulary_for_locale(lc),
            board_type=board_type_for_locale(lc),
        )
        _LOCALE_CACHE[key] = locale
    current_locale.set(locale)
