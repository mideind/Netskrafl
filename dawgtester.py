# -*- coding: utf-8 -*-

""" Test module for DAWG dictionary

    Author: Vilhjalmur Thorsteinsson, 2014

    This module contains test code for dawgdictionary.py

"""

import os
import codecs
import time

from dawgdictionary import DawgDictionary
from languages import Alphabet


class DawgTester:

    def __init__(self):
        self._dawg = None

    def _test(self, word):
        print(u"\"{0}\" is {1}found".format(word, u"" if word in self._dawg else u"not "))

    def _test_true(self, word):
        if word not in self._dawg:
            print(u"Error: \"{0}\" was not found".format(word))

    def _test_false(self, word):
        if word in self._dawg:
            # Tests the __contains__ operator
            print(u"Error: \"{0}\" was found".format(word))

    def run(self, fname, relpath):
        """ Load a DawgDictionary and test its functionality """

        print("DawgDictionary tester")
        print("Author: Vilhjalmur Thorsteinsson")
        print

        self._dawg = DawgDictionary()
        fpath = os.path.abspath(os.path.join(relpath, fname + ".text.dawg"))
        t0 = time.time()
        self._dawg.load(fpath)
        t1 = time.time()

        print("DAWG loaded in {0:.2f} seconds".format(t1 - t0))

        t0 = time.time()
        self._dawg.store_pickle(os.path.abspath(os.path.join(relpath, fname + ".dawg.pickle")))
        t1 = time.time()

        print("DAWG pickle file stored in {0:.2f} seconds".format(t1 - t0))

        print("Checking a set of random words:")
        self._test_true(u"abbadísarinnar")
        self._test_true(u"absintufyllirí")
        self._test_false(u"absolútt")
        self._test_true(u"aborri")
        self._test_true(u"eipaði")
        self._test_true(u"geipaði")
        self._test_false(u"eipeði")
        self._test_false(u"abs")
        self._test_true(u"halló")
        self._test_true(u"blús")
        # self._test_true(u"hraðskákmótin") # Not in BÍN
        # self._test_true(u"jólahraðskákmótið") # Longer than 15 letters
        self._test_true(u"nafnskírteinið")
        self._test_false(u"abstraktmálarið")
        self._test_true(u"abstraktmálari")
        self._test_false(u"abstraktmálar")
        self._test_false(u"abstraktmála")
        self._test_true(u"prófun")
        self._test_true(u"upphitun")
        self._test_false(u"")
        self._test_false(u"abo550")
        self._test_false(u"ertðu")
        self._test_false(u"sértðu")
        self._test_false(u"vextu")
        self._test_true(u"sértu")
        self._test_true(u"dren")
        self._test_true(u"drenið")
        self._test_true(u"drensins")
        self._test_true(u"álínis")
        self._test_false(u"réttleganna")
        self._test_false(u"meistarleganna")
        self._test_false(u"hjálpsamligana")

        self._test_true(u"bitla")
        self._test_true(u"friðla")
        self._test_true(u"fræla")
        self._test_true(u"geistla")
        self._test_true(u"greppla")
        self._test_true(u"hógla")
        self._test_true(u"hretla")
        self._test_true(u"hrumla")
        self._test_true(u"hæfla")
        self._test_true(u"jagla")
        self._test_true(u"mörla")
        self._test_true(u"níðla")
        self._test_true(u"ógjörla")
        self._test_true(u"ragla")
        self._test_true(u"rangla")
        self._test_true(u"síðla")
        self._test_true(u"sjóla")
        self._test_true(u"skopla")
        self._test_true(u"skrifla")
        self._test_true(u"snæla")
        self._test_true(u"spéla")
        self._test_true(u"smásmugula")
        self._test_true(u"safala")
        self._test_true(u"strangla")
        self._test_true(u"strikla")
        self._test_true(u"sumla")
        self._test_true(u"tæpla")
        self._test_true(u"vesalla")
        self._test_true(u"vesla")
        self._test_true(u"vitla")
        self._test_true(u"vígla")
        self._test_true(u"vísla")
        self._test_true(u"þolla")
        self._test_true(u"þrifla")

        self._test_false(u"eystðu")
        self._test_false(u"blæstðu")
        self._test_false(u"botnfrýstðu")
        self._test_false(u"áttðu")
        self._test_false(u"endurkýstðu")
        self._test_false(u"frýstðu")
        self._test_false(u"gaddfrýstðu")
        self._test_false(u"gagnfrýstðu")
        self._test_false(u"gýstðu")
        self._test_false(u"grandlestðu")
        self._test_false(u"helfrýstðu")
        self._test_false(u"hnýstðu")
        self._test_false(u"hralestðu")
        self._test_true(u"hraðlestu")
        self._test_false(u"innblæstðu")
        self._test_false(u"kýstðu")
        self._test_false(u"kanntðu")
        self._test_false(u"lestðu")
        self._test_false(u"ljóslestðu")
        self._test_false(u"marglestðu")
        self._test_false(u"máttðu")
        self._test_false(u"mislestðu")
        self._test_false(u"moldeystðu")
        self._test_false(u"manstðu")
        self._test_false(u"muntðu")
        self._test_false(u"ofrístðu")
        self._test_false(u"rístðu")
        self._test_false(u"sandblæstðu")
        self._test_false(u"skaltðu")
        self._test_false(u"stokkfrýstðu")
        self._test_false(u"anntðu")
        self._test_false(u"uppeystðu")
        self._test_false(u"uppblæstðu")
        self._test_false(u"úteystðu")
        self._test_false(u"vextðu")
        self._test_false(u"ertðu")
        self._test_false(u"sértðu")
        self._test_false(u"viltðu")
        self._test_false(u"veistðu")
        self._test_false(u"þaullestðu")
        self._test_false(u"þinglestðu")
        self._test_false(u"þrautlestðu")
        self._test_false(u"þarftðu")
        self._test_false(u"þurreystðu")

        # All two-letter words on the official list of the
        # Icelandic Skrafl society
        smallwords = [
            u"að", u"af", u"ak", u"al", u"an", u"ar", u"as", u"at", u"ax",
            u"áa", u"áð", u"ái", u"ál", u"ám", u"án", u"ár", u"ás", u"át",
            u"bí", u"bú", u"bý", u"bæ",
            u"dá", u"do", u"dó", u"dý",
            u"eð", u"ef", u"eg", u"ei", u"ek", u"el", u"em", u"en", u"er", u"et", u"ex", u"ey",
            u"ég", u"él", u"ét",
            u"fa", u"fá", u"fé", u"fæ",
            u"gá",
            u"ha", u"há", u"hí", u"hó", u"hý", u"hæ",
            u"ið", u"il", u"im",
            u"íð", u"íl", u"ím", u"ís",
            u"já", u"jó", u"jú",
            u"ká", u"ku", u"kú",
            u"la", u"lá", u"lé", u"ló", u"lý", u"læ",
            u"má", u"mi", u"mó", u"mý",
            u"ná", u"né", u"nó", u"nú", u"ný", u"næ",
            u"of", u"og", u"ok", u"op", u"or",
            u"óa", u"óð", u"óf", u"ói", u"ók", u"ól", u"óm", u"ón", u"óp", u"ós", u"óx",
            u"pí", u"pu", u"pú",
            u"rá", u"re", u"ré", u"rí", u"ró", u"rú", u"rý", u"ræ",
            u"sá", u"sé", u"sí", u"so", u"sú", u"sý", u"sæ",
            u"tá", u"te", u"té", u"ti", u"tí", u"tó", u"tý",
            u"um", u"un",
            u"úa", u"úð", u"úf", u"úi", u"úr", u"út",
            u"vá", u"vé", u"ví", u"vó",
            u"yl", u"ym", u"yr", u"ys",
            u"ýf", u"ýg", u"ýi", u"ýk", u"ýl", u"ýr", u"ýs", u"ýt",
            u"þá", u"þó", u"þú", u"þý",
            u"æð", u"æf", u"æg", u"æi", u"æl", u"æp", u"ær", u"æs", u"æt",
            u"öl", u"ör", u"ös", u"öt", u"öx"]

        print("Checking small words:")

        # Check all possible two-letter combinations, allowing only those in the list
        for first in Alphabet.order:
            for second in Alphabet.order:
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
        print(u"Permutations of \"{0}\":".format(word))
        cnt = 0
        for word in permlist:
            print(u"\"{0}\"".format(word)),
            cnt += 1
            if cnt % 6 == 0:
                print
        print
        print(u"{0} permutations found in {1:.2f} seconds".format(cnt, t1 - t0))
        print
        t0 = time.time()
        word = u"pr?óf"
        permlist = self._dawg.find_permutations(word)
        t1 = time.time()
        print(u"Permutations of \"{0}\":".format(word))
        cnt = 0
        for word in permlist:
            print(u"\"{0}\"".format(word)),
            cnt += 1
            if cnt % 6 == 0:
                print
        print
        print(u"{0} permutations found in {1:.2f} seconds".format(cnt, t1 - t0))
        print

        print("Finding matches:")
        t0 = time.time()
        word = u"e??st??"
        mlist = self._dawg.find_matches(word)
        t1 = time.time()
        print(u"Matches of \"{0}\":".format(word))
        cnt = 0
        for word in mlist:
            print(u"\"{0}\"".format(word)),
            cnt += 1
            if cnt % 6 == 0:
                print
        print
        print(u"{0} matches found in {1:.2f} seconds".format(cnt, t1 - t0))
        print

        t0 = time.time()
        word = u"f?r??t??n"
        mlist = self._dawg.find_matches(word)
        t1 = time.time()
        print(u"Matches of \"{0}\":".format(word))
        cnt = 0
        for word in mlist:
            print(u"\"{0}\"".format(word)),
            cnt += 1
            if cnt % 6 == 0:
                print
        print
        print(u"{0} matches found in {1:.2f} seconds".format(cnt, t1 - t0))
        print

        word = u"??"
        mlist = self._dawg.find_matches(word)

        print(u"{0} two-letter words found; should be {1}".format(len(mlist), len(smallwords)))
        cnt = 0
        for word in mlist:
            if word not in smallwords:
                print (u"{0} in match result but not in smallwords".format(word))
        print

        print(u"Test finished")

        self._dawg = None


def test():
    # Test navivation in the DAWG
    dt = DawgTester()
    dt.run("ordalisti", "resources")


if __name__ == '__main__':

    test()
