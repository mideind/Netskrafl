"""

    Word dictionary implemented with a DAWG

    Copyright © 2025 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

"""

from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple, List

import os
import threading
import logging
import time

from languages import (
    Alphabet,
    IcelandicAlphabet,
    EnglishAlphabet,
    NorwegianAlphabet,
    PolishAlphabet,
    current_vocabulary,
    vocabulary_for_locale,
)
from dawgdictionary import PackedDawgDictionary


# Type definitions
IterTuple = Tuple[str, int]
PrefixNodes = Tuple[IterTuple, ...]
TwoLetterListTuple = Tuple[List[str], List[str]]


# Base project directory path
BASE_PATH = os.path.join(os.path.dirname(__file__), "..")


class Wordbase:

    """ Container for singleton instances of the supported dictionaries """

    # Known dictionaries
    DAWGS: Sequence[Tuple[str, Alphabet]] = [
        # Icelandic
        ("ordalisti", IcelandicAlphabet),
        ("amlodi", IcelandicAlphabet),
        ("midlungur", IcelandicAlphabet),
        # US English
        ("otcwl2014", EnglishAlphabet),
        ("otcwl2014.aml", EnglishAlphabet),
        ("otcwl2014.mid", EnglishAlphabet),
        # ("twl06", EnglishAlphabet),
        # UK & Rest-of-World English
        ("sowpods", EnglishAlphabet),
        ("sowpods.aml", EnglishAlphabet),
        ("sowpods.mid", EnglishAlphabet),
        # Polish
        ("osps37", PolishAlphabet),
        ("osps37.aml", PolishAlphabet),
        ("osps37.mid", PolishAlphabet),
        # Norwegian Bokmål
        ("nsf2023", NorwegianAlphabet),
        ("nsf2023.aml", NorwegianAlphabet),
        ("nsf2023.mid", NorwegianAlphabet),
        # Norwegian Nynorsk
        ("nynorsk2024", NorwegianAlphabet),
        ("nynorsk2024.aml", NorwegianAlphabet),
        ("nynorsk2024.mid", NorwegianAlphabet),
    ]

    _dawg: Dict[str, PackedDawgDictionary] = dict()

    _lock = threading.Lock()

    @staticmethod
    def initialize() -> None:
        """ Load all known dictionaries into memory """
        with Wordbase._lock:
            if not Wordbase._dawg:
                for dawg, alphabet in Wordbase.DAWGS:
                    try:
                        Wordbase._dawg[dawg] = Wordbase._load_resource(dawg, alphabet)
                    except FileNotFoundError:
                        logging.error("Unable to load DAWG {0}".format(dawg))

    @staticmethod
    def _load_resource(resource: str, alphabet: Alphabet) -> PackedDawgDictionary:
        """ Load a dictionary from a binary DAWG file """
        bname = os.path.abspath(
            os.path.join(BASE_PATH, "resources", resource + ".bin.dawg")
        )
        t0 = time.time()
        dawg = PackedDawgDictionary(alphabet)
        dawg.load(bname)
        t1 = time.time()
        logging.info("Loaded DAWG {1} in {0:.2f} seconds".format(t1 - t0, bname))
        return dawg

    @staticmethod
    def dawg() -> PackedDawgDictionary:
        """ Return the main dictionary DAWG object, associated with the
            current thread, i.e. the current user's (or game's) locale """
        return Wordbase._dawg[current_vocabulary()]

    @staticmethod
    def dawg_for_locale(locale: str) -> PackedDawgDictionary:
        """ Return the DAWG object associated with the given locale """
        vocab = vocabulary_for_locale(locale)
        return Wordbase._dawg[vocab]

    @staticmethod
    def dawg_for_vocab(vocab: str) -> Optional[PackedDawgDictionary]:
        """ Return the DAWG object associated with the given vocabulary """
        return Wordbase._dawg.get(vocab)

    @staticmethod
    def two_letter_words(
        vocabulary: Optional[str] = None,
    ) -> Tuple[List[str], List[str]]:
        """ Return the two letter word list associated with the
            current vocabulary """
        dawg = Wordbase._dawg.get(vocabulary or current_vocabulary())
        return ([], []) if dawg is None else dawg.two_letter_words()

    @staticmethod
    def warmup() -> bool:
        """ Called from GAE instance initialization; add warmup code here if needed """
        return True


Wordbase.initialize()
