"""

    Alphabet encapsulation module

    Copyright (C) 2024 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    Currently the supported languages are Icelandic, English (UK and US),
    Polish and Norwegian (Bokmål).

"""

from __future__ import annotations

from typing import (
    List,
    Callable,
)

import abc
import functools
from datetime import datetime


class Alphabet(abc.ABC):
    """Base class for alphabets particular to languages,
    i.e. the letters used in a game"""

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
        """Key function for locale-based sorting"""
        # Note: this only works for lowercase strings that
        # contain letters from the bag (plus '?')
        o = self.all_tiles
        return [o.index(c) for c in lstr if c != "|"]

    def sortval(self, c: str) -> int:
        """Sort value for any character, with correct ordering
        for the current alphabet, case-insensitive"""
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
        """Return a case-insensitive sort key for the given string"""
        return [self.sortval(c) for c in lstr]

    def bit_pattern(self, word: str) -> int:
        """Return a pattern of bits indicating which letters
        are present in the word"""
        bitwise_or: Callable[[int, int], int] = lambda x, y: x | y
        lbit = self.letter_bit
        return functools.reduce(bitwise_or, (lbit[c] for c in word), 0)

    def bit_of(self, c: str) -> int:
        """Returns the bit corresponding to a character in the alphabet"""
        return self.letter_bit[c]

    def all_bits_set(self) -> int:
        """Return a bit pattern where the bits for all letters
        in the Alphabet are set"""
        return 2 ** len(self.order) - 1

    def string_subtract(self, a: str, b: str) -> str:
        """Subtract all letters in b from a, counting each instance separately"""
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
        """Return a timestamp formatted as a readable string"""
        # Currently always returns the full ISO format: YYYY-MM-DD HH:MM:SS
        return ts.isoformat(" ")[0:19]

    # noinspection PyUnusedLocal
    @staticmethod
    def format_timestamp_short(ts: datetime) -> str:
        """Return a timestamp formatted as a readable string"""
        # Returns a short ISO format: YYYY-MM-DD HH:MM
        return ts.isoformat(" ")[0:16]


class _IcelandicAlphabet(Alphabet):
    """The Icelandic alphabet"""

    order = "aábdðeéfghiíjklmnoóprstuúvxyýþæö"
    # Upper case version of the order string
    upper = "AÁBDÐEÉFGHIÍJKLMNOÓPRSTUÚVXYÝÞÆÖ"

    # Sort ordering of all valid letters
    full_order = "aábcdðeéfghiíjklmnoópqrstuúvwxyýzþæö"
    # Upper case version of the full order string
    full_upper = "AÁBCDÐEÉFGHIÍJKLMNOÓPQRSTUÚVWXYÝZÞÆÖ"


IcelandicAlphabet = _IcelandicAlphabet()


class _EnglishAlphabet(Alphabet):
    """The English alphabet"""

    order = "abcdefghijklmnopqrstuvwxyz"
    # Upper case version of the order string
    upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    # Sort ordering of all valid letters
    full_order = order
    # Upper case version of the full order string
    full_upper = upper


EnglishAlphabet = _EnglishAlphabet()


class _PolishAlphabet(Alphabet):
    """The Polish alphabet"""

    order = "aąbcćdeęfghijklłmnńoóprsśtuwyzźż"
    upper = "AĄBCĆDEĘFGHIJKLŁMNŃOÓPRSŚTUWYZŹŻ"

    # Sort ordering of all valid letters
    full_order = "aąbcćdeęfghijklłmnńoópqrsśtuvwxyzźż"
    # Upper case version of the full order string
    full_upper = "AĄBCĆDEĘFGHIJKLŁMNŃOÓPQRSŚTUVWXYZŹŻ"


PolishAlphabet = _PolishAlphabet()


class _NorwegianAlphabet(Alphabet):
    """The Norwegian alphabet"""

    # Note: Ä, Ö, Ü, Q, X and Z are not included in the
    # Norwegian tile set, but they can appear in words in
    # the dictionary (and can be played via the blank tile),
    # so we include them here
    order = "aäbcdefghijklmnoöpqrstuüvwxyzæøå"
    upper = "AÄBCDEFGHIJKLMNOÖPQRSTUÜVWXYZÆØÅ"

    # Sort ordering of all valid letters
    full_order = order
    # Upper case version of the full order string
    full_upper = upper


NorwegianAlphabet = _NorwegianAlphabet()
