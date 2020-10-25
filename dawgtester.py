#!/usr/bin/env python3

""" Test module for DAWG dictionary

    Copyright (C) 2020 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    This module contains test code for dawgdictionary.py

"""

from __future__ import annotations

from typing import Optional

import os
import time

from dawgdictionary import PackedDawgDictionary
from languages import IcelandicAlphabet


class DawgTester:

    def __init__(self):
        self._dawg: Optional[PackedDawgDictionary] = None

    def _test(self, word: str) -> None:
        assert self._dawg is not None
        print("\"{0}\" is {1}found".format(word, "" if word in self._dawg else u"not "))

    def _test_true(self, word: str) -> None:
        assert self._dawg is not None
        if word not in self._dawg:
            print("Error: \"{0}\" was not found".format(word))

    def _test_false(self, word: str) -> None:
        assert self._dawg is not None
        if word in self._dawg:
            # Tests the __contains__ operator
            print("Error: \"{0}\" was found".format(word))

    def run(self, fname, relpath):
        """ Load a DawgDictionary and test its functionality """

        print("DawgDictionary tester")
        print("Author: Vilhjálmur Þorsteinsson\n")

        t0 = time.time()
        self._dawg = PackedDawgDictionary()
        fpath = os.path.abspath(os.path.join(relpath, fname + ".bin.dawg"))
        self._dawg.load(fpath)
        t1 = time.time()

        print("DAWG loaded in {0:.2f} seconds".format(t1 - t0))

        print("Checking a set of random words:")
        self._test_true("abbadísarinnar")
        self._test_true("absintufyllirí")
        self._test_false("absolútt")
        self._test_true("aborri")
        self._test_true("eipaði")
        self._test_true("geipaði")
        self._test_false("eipeði")
        self._test_false("abs")
        self._test_true("halló")
        self._test_true("blús")
        # self._test_true("hraðskákmótin") # Not in BÍN
        # self._test_true("jólahraðskákmótið") # Longer than 15 letters

        self._test_true("dylstu")
        self._test_true("innslagi")

        self._test_true("nafnskírteinið")
        self._test_false("abstraktmálarið")
        self._test_true("abstraktmálari")
        self._test_false("abstraktmálar")
        self._test_false("abstraktmála")
        self._test_true("prófun")
        self._test_true("upphitun")
        self._test_false("")
        self._test_false("abo550")
        self._test_false("ertðu")
        self._test_false("sértðu")
        # self._test_false("vextu") # Seems to be allowed
        self._test_true("sértu")
        self._test_true("dren")
        self._test_true("drenið")
        self._test_true("drensins")
        self._test_true("álínis")
        self._test_true("hán")
        self._test_true("háni")
        self._test_true("háns")
        self._test_true("hvívetna")
        self._test_false("réttleganna")
        self._test_false("meistarleganna")
        self._test_false("hjálpsamligana")
        self._test_false("ennig")

        self._test_true("bitla")
        self._test_true("friðla")
        self._test_true("fræla")
        self._test_true("geistla")
        self._test_true("greppla")
        self._test_true("hógla")
        self._test_true("hretla")
        self._test_true("hrumla")
        self._test_true("hæfla")
        self._test_true("jagla")
        self._test_true("mörla")
        self._test_true("níðla")
        self._test_true("ógjörla")
        self._test_true("ragla")
        self._test_true("rangla")
        self._test_true("síðla")
        self._test_true("sjóla")
        self._test_true("skopla")
        self._test_true("skrifla")
        self._test_true("snæla")
        self._test_true("spéla")
        self._test_true("smásmugula")
        self._test_true("safala")
        self._test_true("strangla")
        self._test_true("strikla")
        self._test_true("sumla")
        self._test_true("tæpla")
        self._test_true("vesalla")
        self._test_true("vesla")
        self._test_true("vitla")
        self._test_true("vígla")
        self._test_true("vísla")
        self._test_true("þolla")
        self._test_true("þrifla")
        self._test_true("hóg")
        self._test_true("íra")
        self._test_true("íri")
        self._test_true("bravó")
        self._test_true("áldós")
        self._test_true("fleirum")

        self._test_false("eystðu")
        self._test_false("blæstðu")
        self._test_false("botnfrýstðu")
        self._test_false("áttðu")
        self._test_false("endurkýstðu")
        self._test_false("frýstðu")
        self._test_false("gaddfrýstðu")
        self._test_false("gagnfrýstðu")
        self._test_false("gýstðu")
        self._test_false("grandlestðu")
        self._test_false("helfrýstðu")
        self._test_false("hnýstðu")
        self._test_false("hralestðu")
        self._test_true("hraðlestu")
        self._test_false("innblæstðu")
        self._test_false("kýstðu")
        self._test_false("kanntðu")
        self._test_false("lestðu")
        self._test_false("ljóslestðu")
        self._test_false("marglestðu")
        self._test_false("máttðu")
        self._test_false("mislestðu")
        self._test_false("moldeystðu")
        self._test_false("manstðu")
        self._test_false("muntðu")
        self._test_false("ofrístðu")
        self._test_false("rístðu")
        self._test_false("sandblæstðu")
        self._test_false("skaltðu")
        self._test_false("stokkfrýstðu")
        self._test_false("anntðu")
        self._test_false("uppeystðu")
        self._test_false("uppblæstðu")
        self._test_false("úteystðu")
        self._test_false("vextðu")
        self._test_false("ertðu")
        self._test_false("sértðu")
        self._test_false("viltðu")
        self._test_false("veistðu")
        self._test_false("þaullestðu")
        self._test_false("þinglestðu")
        self._test_false("þrautlestðu")
        self._test_false("þarftðu")
        self._test_false("þurreystðu")
        self._test_false("fatai")
        self._test_false("ina")

        # Spurnarmyndir (question forms)
        # Allowed in singular (present and past tense),
        # disallowed in plural (present and past tense)
        self._test_true("ertu")
        self._test_true("vertu")
        self._test_true("sértu")
        self._test_true("varstu")
        self._test_true("verðurðu")
        self._test_true("varðstu")
        self._test_true("fórstu")
        self._test_true("ferðu")
        self._test_true("komstu")
        self._test_true("kemurðu")
        self._test_true("borðarðu")
        self._test_true("borðaðirðu")
        self._test_false("voruði")
        self._test_false("eruði")
        self._test_false("fóruði")
        self._test_false("fariði")
        self._test_false("borðiði")
        self._test_false("borðuðuði")
        self._test_false("komiði")
        self._test_false("komuði")

        # All two-letter words on the official list of the
        # Icelandic Skrafl society
        smallwords = [
            "að", "af", "ak", "al", "an", "ar", "as", "at", "ax",
            "áa", "áð", "ái", "ál", "ám", "án", "ár", "ás", "át",
            "bí", "bú", "bý", "bæ",
            "dá", "do", "dó", "dý",
            "eð", "ef", "eg", "ei", "ek", "el", "em", "en", "er", "es", "et", "ex", "ey",
            "ég", "él", "ét",
            "fa", "fá", "fé", "fæ",
            "gá",
            "ha", "há", "hí", "hó", "hý", "hæ",
            "ið", "il", "im",
            "íð", "íl", "ím", "ís",
            "já", "je", "jó", "jú",
            "ká", "ku", "kú",
            "la", "lá", "lé", "ló", "lú", "lý", "læ",
            "má", "mi", "mó", "mý",
            "ná", "né", "nó", "nú", "ný", "næ",
            "of", "og", "oj", "ok", "op", "or",
            "óa", "óð", "óf", "ói", "ók", "ól", "óm", "ón", "óp", "ós", "óx",
            "pí", "pu", "pú", "pæ",
            "rá", "re", "ré", "rí", "ró", "rú", "rý", "ræ",
            "sá", "sé", "sí", "so", "sú", "sý", "sæ",
            "tá", "te", "té", "ti", "tí", "tó", "tý",
            "um", "un",
            "úa", "úð", "úf", "úi", "úr", "út",
            "vá", "vé", "ví", "vó",
            "yl", "ym", "yr", "ys",
            "ýf", "ýg", "ýi", "ýk", "ýl", "ýr", "ýs", "ýt",
            "þá", "þó", "þú", "þý",
            "æð", "æf", "æg", "æi", "æl", "æp", "ær", "æs", "æt",
            "öl", "ör", "ös", "öt", "öx"
        ]

        print("Checking small words:")

        # Check all possible two-letter combinations, allowing only those in the list
        for first in IcelandicAlphabet.order:
            for second in IcelandicAlphabet.order:
                word = first + second
                if word in smallwords:
                    self._test_true(word)
                else:
                    self._test_false(word)

        print("Finding permutations:")
        t0 = time.time()
        word = u"einstök"
        permlist = self._dawg.find_permutations(word)
        t1 = time.time()
        print("Permutations of \"{0}\":".format(word))
        cnt = 0
        for word in permlist:
            print("\"{0}\"".format(word), sep=" ")
            cnt += 1
            if cnt % 6 == 0:
                print()
        print()
        print("{0} permutations found in {1:.2f} seconds".format(cnt, t1 - t0))
        print()
        t0 = time.time()
        word = u"pr?óf"
        permlist = self._dawg.find_permutations(word)
        t1 = time.time()
        print("Permutations of \"{0}\":".format(word))
        cnt = 0
        for word in permlist:
            print("\"{0}\"".format(word), sep=" ")
            cnt += 1
            if cnt % 6 == 0:
                print()
        print()
        print("{0} permutations found in {1:.2f} seconds".format(cnt, t1 - t0))
        print()

        print("Finding matches:")
        t0 = time.time()
        word = u"e??st??"
        mlist = self._dawg.find_matches(word)
        t1 = time.time()
        print("Matches of \"{0}\":".format(word))
        cnt = 0
        for word in mlist:
            print("\"{0}\"".format(word), sep=" ")
            cnt += 1
            if cnt % 6 == 0:
                print()
        print()
        print("{0} matches found in {1:.2f} seconds".format(cnt, t1 - t0))
        print()

        t0 = time.time()
        word = u"f?r??t??n"
        mlist = self._dawg.find_matches(word)
        t1 = time.time()
        print("Matches of \"{0}\":".format(word))
        cnt = 0
        for word in mlist:
            print("\"{0}\"".format(word), sep=" ")
            cnt += 1
            if cnt % 6 == 0:
                print()
        print()
        print("{0} matches found in {1:.2f} seconds".format(cnt, t1 - t0))
        print()

        word = "??"
        mlist = self._dawg.find_matches(word)

        print("{0} two-letter words found; should be {1}".format(len(mlist), len(smallwords)))
        for word in mlist:
            if word not in smallwords:
                print("{0} in match result but not in smallwords".format(word))
        print()

        print("Test finished")

        self._dawg = None


def test():
    # Test navivation in the DAWG
    dt = DawgTester()
    dt.run("ordalisti", "resources")


if __name__ == '__main__':

    test()
