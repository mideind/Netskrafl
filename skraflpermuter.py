# -*- coding: utf-8 -*-

""" SCRABBLE(tm) rack permutations

    Author: Vilhjalmur Thorsteinsson, 2014

    This module implements a main class named Tabulator and
    a helper class named WordDatabase.

    Tabulator takes a SCRABBLE(tm) rack and processes it to find
    all valid word permutations within the rack. It can then
    be queried for the number of such permutations, the list
    of permutations, the highest "plain" score in the list,
    and the list of the permutations having the highest such score.
    It also generates valid combinations of the
    rack with a single additional letter.

    WordDatabase can judge whether a particular word is valid
    on the board, given a dictionary. It uses a preprocessed word
    graph (DAWG) loaded from a text file. The word graph is
    implemented in class DawgDictionary in dawgdictionary.py.

    Note: SCRABBLE is a registered trademark. This software or its author
    are in no way affiliated with or endorsed by the owners or licensees
    of the SCRABBLE trademark.

"""

import os
import itertools
import codecs
import logging
import time
import threading

import dawgdictionary

from languages import Alphabet


class WordDatabase:

    """ Maintains the set of permitted words and judges whether a word is acceptable.
    
    This class loads and maintains a Directed Acyclic Word Graph (DAWG) of valid words.
    The DAWG is used to check racks for validity and to find all valid words embedded
    within a rack.

    The word database is fairly big (several megabytes) so it is important to avoid multiple
    instances of it. The Tabulator implementation below makes sure to use a singleton
    instance of the WordDatabase class, in the class variable _word_db, across all invocations.

    The word graph is loaded from a text file, 'ordalisti.text.dawg', assumed to be in
    the 'resources' folder. This file is separately pre-generated using DawgBuilder.run_skrafl()
    in dawgbuilder.py.

    The graph contains a cleaned-up version of a database originally from bin.arnastofnun.is,
    used under license conditions from "Stofnun Árna Magnússonar í íslenskum fræðum".

    """

    def __init__(self):
        # We maintain the list of permitted words in a DAWG dictionary
        # The DAWG is lazily loaded into memory upon first use
        self._dawg = None
        self._lock = threading.Lock()

    def _load(self):
        """ Load word lists into memory from static preprocessed text files """
        # Make sure we only have one thread doing this simultaneously
        with self._lock:
            if self._dawg is not None:
                # Already loaded, nothing to do
                return
            fname = os.path.abspath(os.path.join("resources", "ordalisti.text.dawg"))
            logging.info(u"Loading graph from file {0}".format(fname))
            t0 = time.time()
            self._dawg = dawgdictionary.DawgDictionary()
            self._dawg.load(fname)
            t1 = time.time()
            logging.info(u"Loaded {0} graph nodes in {1:.2f} seconds".format(self._dawg.num_nodes(), t1 - t0))

    def initialize(self):
        """ Force preloading of word lists into memory """
        if self._dawg is None:
            self._load()

    def is_valid_word(self, word):
        """ Checks whether a word is found in the list of legal words """
        if not word:
            return False
        if self._dawg is None:
            self._load()
        assert self._dawg is not None
        return self._dawg.find(word)

    def __contains__(self, word):
        """ Enable simple lookup syntax: "word" in word_db """
        return self.is_valid_word(word)

    def find_permutations(self, rack):
        """ Find all embedded words within a rack """
        if not rack:
            return None
        if self._dawg is None:
            self._load()
        assert self._dawg is not None
        return self._dawg.find_permutations(rack)

    def find_matches(self, pattern, sort=True):
        """ Find all words that match a pattern """
        if not pattern:
            return None
        if self._dawg is None:
            self._load()
        assert self._dawg is not None
        return self._dawg.find_matches(pattern, sort)

    def navigate(self, nav):
        """ Use a generic navigator to traverse the graph """
        if self._dawg is None:
            self._load()
        assert self._dawg is not None
        self._dawg.navigate(nav)


class Tabulator:

    """ Processes and tabulates the possible permutations and combinations
        within a given rack.

        An instance of this class is passed to the result.html web page
        for display using the Jinja2 template mechanism.

    """

    # A singleton instance of the WordDatabase class, used by
    # all Tabulator instances throughout a server session
    _word_db = None

    def __init__(self):
        self._counter = 0
        self._allwords = []
        self._highscore = 0
        self._highwords = []
        self._combinations = { }
        self._rack = u''
        self._rack_is_valid = False # True if the rack is itself a valid word
        self._pattern = False # True if the result is a pattern match ('=')
        if Tabulator._word_db is None:
            # The word database will be lazily loaded from file upon first use
            Tabulator._word_db = WordDatabase()

    def process(self, rack):
        """ Generate the data that will be shown to the user on the result page.
            This includes a list of permutations of the rack, as well as combinations
            of the rack with a single additional letter. High scoring words are also
            tabulated. """
        # Start with basic hygiene
        if not rack:
            return False
        rack = rack.strip()
        if not rack:
            return False
        # Make sure we reset all state in case we're called multiple times
        self._counter = 0
        self._allwords = []
        self._highscore = 0
        self._highwords = []
        self._combinations = { }
        self._rack = u''
        self._pattern = False
        # Do a sanity check on the input by calculating its raw score, thereby
        # checking whether all the letters are valid
        score = 0
        rack_lower = u'' # Rack converted to lowercase
        wildcards = 0 # Number of wildcard characters
        # If the rack starts with an equals sign ('=') we do a pattern match
        # instead of a permutation search
        if rack[0] == u'=':
            self._pattern = True
            rack = rack[1:]
        # Sanitize the rack, converting upper case to lower case and
        # catching invalid characters
        try:
            for c in rack:
                ch = c
                if ch in Alphabet.upper:
                    # Uppercase: find corresponding lowercase letter
                    ch = Alphabet.lowercase(ch)
                if ch in u'?_*':
                    # This is one of the allowed wildcard characters
                    wildcards += 1
                    ch = u'?'
                else:
                    score += Alphabet.scores[ch]
                rack_lower += ch
        except KeyError:
            # A letter in the rack is not valid, even after conversion to lower case
            return False
        if not self._pattern and (wildcards > 2):
            # Too many wildcards in a permutation search - need to constrain result set size
            return False
        # The rack contains only valid letters
        self._rack = rack_lower
        # Generate combinations
        if not self._pattern and not wildcards:
            # If no wildcards given, check combinations with one additional letter
            query = self._rack + u'?'
            # Permute the rack with one additional letter
            p = self._word_db.find_permutations(query)
            # Check the permutations to find valid words and their scores
            if p is not None:
                for word in p:
                    # Only interested in full-length permutations, i.e. with the additional letter
                    if len(word) == len(query):
                        # Find out which letter was added
                        addedletter = Alphabet.string_subtract(word, self._rack)
                        self._add_combination(addedletter, word)
        # Check permutations
        # The shortest possible rack to check for permutations is 2 letters
        if len(self._rack) < 2:
            return True
        if self._pattern:
            # Use pattern matching
            p = self._word_db.find_matches(self._rack, True) # We'd like a sorted result
        else:
            # Find permutations
            p = self._word_db.find_permutations(self._rack)
        if p is None:
            return True
        for word in p:
            if len(word) < 2:
                # Don't show single letter words
                continue
            # Calculate the basic score of the word
            score = self.score(word)
            if wildcards and not self._pattern:
                # Complication: Make sure we don't count the score of the wildcard tile(s)
                wildchars = Alphabet.string_subtract(word, self._rack)
                # What we have left are the wildcard substitutes: subtract'em
                score -= self.score(wildchars)
            self._add_permutation(word, score)
        # Successful
        return True

    def score(self, word):
        """ Calculate the score for a word """
        if word is None:
            return 0
        try:
            s = sum(Alphabet.scores[c] for c in word)
        except KeyError:
            # Word contains an unrecognized letter: return a zero score
            s = 0
        return s

    def _add_permutation(self, word, score):
        """ Add a valid permulation to the tabulation result """
        self._counter += 1
        self._allwords.append(word)
        if score > self._highscore:
            # New high scoring word: note it and start a new list
            self._highscore = score
            self._highwords = [word]
        elif score == self._highscore:
            # Equal score to the previous high scorer: append to the list
            self._highwords.append(word)

    def _add_combination(self, ch, word):
        """ Add to a list of legal combinations that are possible if the letter ch is added to the rack """
        if ch in self._combinations:
            self._combinations[ch].append(word)
        else:
            self._combinations[ch] = [word]

    def rack(self):
        """ Returns a display form of the rack that was tabulated """
        return (u'= ' + self._rack) if self._pattern else self._rack

    def count(self):
        """ Returns a count of all valid letter permutations in the rack """
        return self._counter

    def allwords(self):
        """ Returns a list of all the valid letter permulations in the rack """
        return self._allwords
        
    def highscore(self):
        """Returns the highest scoring letter permutation (by plain summation) in the rack"""
        return self._highscore

    def highwords(self):
        """ Returns a list of all letter permutations in the rack having the highest score """
        return self._highwords

    def combinations(self):
        """ Returns a list of the combinations possible with additional letters.
        The list contains (ch, wordlist) tuples where ch is the additional letter
        and wordlist is a list of legal words that can be formed with that letter. """
        lc = list(self._combinations.items())
        if lc:
            # Sort the combinations properly in alphabetical order before returning them
           lc.sort(key = lambda x: Alphabet.order.index(x[0]))
           return lc
        # No combinations
        return None

    def is_valid_word(self, word):
        """ Checks whether a word is valid """
        return Tabulator._word_db.is_valid_word(word)
