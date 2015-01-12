# -*- coding: utf-8 -*-

""" Language, locale and alphabet encapsulation module

    Author: Vilhjalmur Thorsteinsson, 2014

    The classes in this module encapsulate particulars of supported
    languages, including the character set, scores, tiles in the
    initial bag, sorting, etc.

    Currently the only supported language is Icelandic.

"""

from functools import reduce

class Alphabet:

    """ This implementation of the Alphabet class encapsulates particulars of the Icelandic
        language and Scrabble rules. Other languages can be supported by modifying
        or subclassing this class.
    """

    # Dictionary of Scrabble letter scores

    scores = {
        u'a': 1,
        u'á': 4,
        u'b': 6,
        u'd': 4,
        u'ð': 2,
        u'e': 1,
        u'é': 6,
        u'f': 3,
        u'g': 2,
        u'h': 3,
        u'i': 1,
        u'í': 4,
        u'j': 5,
        u'k': 2,
        u'l': 2,
        u'm': 2,
        u'n': 1,
        u'o': 3,
        u'ó': 6,
        u'p': 8,
        u'r': 1,
        u's': 1,
        u't': 1,
        u'u': 1,
        u'ú': 8,
        u'v': 3,
        u'x': 10,
        u'y': 7,
        u'ý': 9,
        u'þ': 4,
        u'æ': 5,
        u'ö': 7,
        u'?': 0
    }

    # Tiles in initial bag, with frequencies
    bag_tiles = [
        (u"a", 10),
        (u"á", 2),
        (u"b", 1),
        (u"d", 2),
        (u"ð", 5),
        (u"e", 6),
        (u"é", 1),
        (u"f", 3),
        (u"g", 4),
        (u"h", 2),
        (u"i", 8),
        (u"í", 2),
        (u"j", 1),
        (u"k", 3),
        (u"l", 3),
        (u"m", 3),
        (u"n", 8),
        (u"o", 3),
        (u"ó", 1),
        (u"p", 1),
        (u"r", 7),
        (u"s", 6),
        (u"t", 5),
        (u"u", 6),
        (u"ú", 1),
        (u"v", 2),
        (u"x", 1),
        (u"y", 1),
        (u"ý", 1),
        (u"þ", 1),
        (u"æ", 1),
        (u"ö", 1),
        (u"?", 2)] # Blank tiles

    # Sort ordering of Icelandic letters allowed in Scrabble
    order = u'aábdðeéfghiíjklmnoóprstuúvxyýþæö'
    # Upper case version of the order string
    upper = u'AÁBDÐEÉFGHIÍJKLMNOÓPRSTUÚVXYÝÞÆÖ'
    # All tiles including wildcard '?'
    all_tiles = order + u'?'

    # Sort ordering of all valid letters
    full_order = u'aábcdðeéfghiíjklmnoópqrstuúvwxyýzþæö'
    # Upper case version of the full order string
    full_upper = u'AÁBCDÐEÉFGHIÍJKLMNOÓPQRSTUÚVWXYÝZÞÆÖ'

    # Letter bit pattern
    bit = [1 << n for n in range(len(order))]

    # Locale collation (sorting) map, initialized in _init()
    _lcmap = None # Case sensitive
    _lcmap_nocase = None # Case insensitive


    @staticmethod
    def score(tiles):
        """ Return the net (plain) score of the given tiles """
        if not tiles:
            return 0
        return sum([Alphabet.scores[tile] for tile in tiles])

    @staticmethod
    def bit_pattern(word):
        """ Return a pattern of bits indicating which letters are present in the word """
        return reduce(lambda x, y: x | y, [Alphabet.bit_of(c) for c in word], 0)

    @staticmethod
    def bit_of(c):
        """ Returns the bit corresponding to a character in the alphabet """
        return Alphabet.bit[Alphabet.order.index(c)]

    @staticmethod
    def all_bits_set():
        """ Return a bit pattern where the bits for all letters in the Alphabet are set """
        return 2 ** len(Alphabet.order) - 1

    @staticmethod
    def lowercase(ch):
        """ Convert an uppercase character to lowercase """
        return Alphabet.full_order[Alphabet.full_upper.index(ch)]

    @staticmethod
    def tolower(s):
        """ Return the argument string converted to lowercase """
        return u''.join([Alphabet.lowercase(c) if c in Alphabet.full_upper else c for c in s])

    @staticmethod
    def sortkey(word):
        """ Return a sort key with the proper lexicographic ordering
            for the given word, which must be 'pure', i.e. alphabetic. """
        # This assumes that Alphabet.full_order is correctly ordered in ascending order.
        return [Alphabet.full_order.index(ch) for ch in word]

    @staticmethod
    def sort(l):
        """ Sort a list in-place by lexicographic ordering according to this Alphabet """
        l.sort(key = Alphabet.sortkey)

    @staticmethod
    def sorted(l):
        """ Return a list sorted by lexicographic ordering according to this Alphabet """
        return sorted(l, key = Alphabet.sortkey)

    @staticmethod
    def string_subtract(a, b):
        """ Subtract all letters in b from a, counting each instance separately """
        # Note that this cannot be done with sets, as they fold multiple letter instances into one
        lcount = [a.count(c) - b.count(c) for c in Alphabet.all_tiles]
        return u''.join([Alphabet.all_tiles[ix] * lcount[ix]
            for ix in range(len(lcount)) if lcount[ix] > 0])

    @staticmethod
    def full_bag():
        """ Return a full bag of tiles """
        return u''.join([tile * count for (tile, count) in Alphabet.bag_tiles])

    @staticmethod
    def format_timestamp(ts, format = None):
        """ Return a timestamp formatted as a readable string """
        # Currently always returns the full ISO format: YYYY-MM-DD HH:MM:SS
        return u"" + ts.isoformat(' ')[0:19]
 
    @staticmethod
    def _init():
        """ Create a collation (sort) mapping for the Icelandic language """
        lcmap = [i for i in range(0,256)]

        def rotate(letter, sort_after):
            """ Modifies the lcmap so that the letter is sorted after the indicated letter """
            sort_as = lcmap[sort_after] + 1
            letter_val = lcmap[letter]
            # We only support the case where a letter is moved forward in the sort order
            if letter_val > sort_as:
                for i in range(0, 256):
                    if (lcmap[i] >= sort_as) and (lcmap[i] < letter_val):
                        lcmap[i] += 1
            lcmap[letter] = sort_as

        def adjust(s):
            """ Ensure that the sort order in the lcmap is in ascending order as in s """
            # This does not need to be terribly efficient as the code is
            # only run once, during initialization
            for i in range(1, len(s) - 1):
                rotate(ord(s[i]), ord(s[i-1]))

        adjust(Alphabet.full_upper) # Uppercase adjustment
        adjust(Alphabet.full_order) # Lowercase adjustment

        # Now we have a case-sensitive sorting map: copy it
        Alphabet._lcmap = lcmap[:]

        # Create a case-insensitive sorting map, where the lower case
        # characters have the same sort value as the upper case ones
        for i, c in enumerate(Alphabet.full_order):
            lcmap[ord(c)] = lcmap[ord(Alphabet.full_upper[i])]

        # Store the case-insensitive sorting map
        Alphabet._lcmap_nocase = lcmap

    @staticmethod
    def sortkey(lstr):
        """ Key function for locale-based sorting """
        assert Alphabet._lcmap
        return [Alphabet._lcmap[ord(c)] if ord(c) <= 255 else 256 for c in lstr]

    @staticmethod
    def sortkey_nocase(lstr):
        """ Key function for locale-based sorting, case-insensitive """
        assert Alphabet._lcmap_nocase
        return [Alphabet._lcmap_nocase[ord(c)] if ord(c) <= 255 else 256 for c in lstr]


# Initialize the locale collation (sorting) map
Alphabet._init()

