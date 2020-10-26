"""

    Language, locale and alphabet encapsulation module

    Copyright (C) 2020 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The GNU General Public License, version 3, applies to this software.
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

from typing import Dict, List, Tuple, Optional, Type, NamedTuple, Callable

import abc
import functools
from datetime import datetime
from contextvars import ContextVar


class Alphabet(abc.ABC):

    """ Base class for alphabets particular to languages,
        i.e. the letters used in a game """

    LCMAP = [i for i in range(0, 256)]

    # The following are overridden in derived classes
    order = ""
    upper = ""
    all_tiles = ""
    full_order = ""
    full_upper = ""

    def __init__(self):
        # Map letters to bits
        self.letter_bit = {letter: 1 << ix for ix, letter in enumerate(self.order)}

        lcmap = self.LCMAP[:]

        def rotate(letter: int, sort_after: int) -> None:
            """Modifies the lcmap so that the letter is sorted
            after the indicated letter"""
            sort_as = lcmap[sort_after] + 1
            letter_val = lcmap[letter]
            # We only support the case where a letter is moved
            # forward in the sort order
            if letter_val > sort_as:
                for i in range(0, 256):
                    if sort_as <= lcmap[i] < letter_val:
                        lcmap[i] += 1
            lcmap[letter] = sort_as

        def adjust(s: str) -> None:
            """Ensure that the sort order in the lcmap is
            in ascending order as in s"""
            # This does not need to be terribly efficient as the code is
            # only run once, during initialization
            for i in range(1, len(s) - 1):
                rotate(ord(s[i]), ord(s[i - 1]))

        adjust(self.full_upper)  # Uppercase adjustment
        adjust(self.full_order)  # Lowercase adjustment

        # Now we have a case-sensitive sorting map: copy it
        self._lcmap = lcmap[:]

        # Create a case-insensitive sorting map, where the lower case
        # characters have the same sort value as the upper case ones
        for i, c in enumerate(self.full_order):
            lcmap[ord(c)] = lcmap[ord(self.full_upper[i])]

        # Store the case-insensitive sorting map
        self._lcmap_nocase = lcmap

        # Assemble a decoding dictionary where encoded indices are mapped to
        # characters, eventually with a suffixed vertical bar '|' to denote finality
        self.coding = {i: c for i, c in enumerate(self.order)}
        self.coding.update({i | 0x80: c + "|" for i, c in enumerate(self.order)})

    def bit_pattern(self, word: str) -> int:
        """Return a pattern of bits indicating which letters
        are present in the word"""
        return functools.reduce(
            lambda x, y: x | y, [self.letter_bit[c] for c in word], 0
        )

    def bit_of(self, c):
        """ Returns the bit corresponding to a character in the alphabet """
        return self.letter_bit[c]

    def all_bits_set(self) -> int:
        """Return a bit pattern where the bits for all letters
        in the Alphabet are set"""
        return 2 ** len(self.order) - 1

    def lowercase(self, ch: str) -> str:
        """ Convert an uppercase character to lowercase """
        return self.full_order[self.full_upper.index(ch)]

    def tolower(self, s: str) -> str:
        """ Return the argument string converted to lowercase """
        return "".join(
            [self.lowercase(c) if c in self.full_upper else c for c in s]
        )

    def sort(self, l: List[str]) -> None:
        """Sort a list in-place by lexicographic ordering
        according to this Alphabet"""
        l.sort(key=self.sortkey)

    def sorted(self, l: List[str]) -> List[str]:
        """Return a list sorted by lexicographic ordering
        according to this Alphabet"""
        return sorted(l, key=self.sortkey)

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

    def sortkey(self, lstr: str) -> List[int]:
        """ Key function for locale-based sorting """
        return [self._lcmap[ord(c)] if ord(c) <= 255 else 256 for c in lstr]

    def sortkey_nocase(self, lstr: str) -> List[int]:
        """ Key function for locale-based sorting, case-insensitive """
        return [self._lcmap_nocase[ord(c)] if ord(c) <= 255 else 256 for c in lstr]

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
    # All tiles including wildcard '?'
    all_tiles = order + "?"

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
    # All tiles including wildcard '?'
    all_tiles = order + "?"

    # Sort ordering of all valid letters
    full_order = order
    # Upper case version of the full order string
    full_upper = upper


EnglishAlphabet = _EnglishAlphabet()


class TileSet(abc.ABC):

    """ Abstract base class for tile sets. Concrete classes are found below. """

    # The following will be overridden in derived classes
    scores: Dict[str, int] = dict()
    bag_tiles: List[Tuple[str, int]] = []
    _full_bag = ""

    @classmethod
    def score(cls, tiles):
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
        return sum(n for letter, n in cls.bag_tiles)


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

# Mapping of locale code to tileset

TILESETS: Dict[str, Type[TileSet]] = dict(
    is_IS=NewTileSet,
    en_AU=EnglishTileSet,
    en_BZ=EnglishTileSet,
    en_CA=EnglishTileSet,
    en_GB=EnglishTileSet,
    en_IE=EnglishTileSet,
    en_IN=EnglishTileSet,
    en_JM=EnglishTileSet,
    en_MY=EnglishTileSet,
    en_NZ=EnglishTileSet,
    en_PH=EnglishTileSet,
    en_SG=EnglishTileSet,
    en_TT=EnglishTileSet,
    en_US=EnglishTileSet,
    en_ZA=EnglishTileSet,
    en_ZW=EnglishTileSet,
)

Locale = NamedTuple(
    "Locale", [("lc", str), ("alphabet", Alphabet), ("tileset", Type[TileSet])]
)

# Use a context variable (thread local) to store the locale information
# for the current thread, i.e. for the current request
default_locale: Locale = Locale("is_IS", IcelandicAlphabet, NewTileSet)
current_locale: ContextVar[Locale] = ContextVar("locale", default=default_locale)

current_lc: Callable[[], str] = lambda: current_locale.get().lc
current_alphabet: Callable[[], Alphabet] = lambda: current_locale.get().alphabet
current_tileset: Callable[[], Type[TileSet]] = lambda: current_locale.get().tileset
