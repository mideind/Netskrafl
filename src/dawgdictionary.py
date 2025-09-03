"""

    Word dictionary implemented with a DAWG

    Copyright © 2025 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    DawgDictionary uses a Directed Acyclic Word Graph (DAWG) internally
    to store a large set of words in an efficient structure in terms
    of storage and speed.

    The graph is pre-built using the code in dawgbuilder.py and stored
    in a text-based file to be loaded at run-time by DawgDictionary.

    The main class supports three fundamental query functions:

    DawgDictionary.find(word)
        Returns True if the word is found in the dictionary, or False if not.
        The __contains__ operator is supported, so "'myword' in dawgdict" also works.

    DawgDictionary.find_matches(pattern)
        Returns a list of words that match the pattern. The pattern can contain
        wildcards ('?'). For example, result = dawgdict.find_matches("ex???") returns
        a list of all 5-letter words starting with "ex".

    DawgDictionary.find_permutations(rack)
        Returns a list of all permutations of the given rack, i.e. valid words
        consisting of one or more letters from the rack in various orders.
        The rack may contain wildcards ('?'). For example,
        result = dawgdict.find_permutations("se?")
        returns a list of all words from 1 to 3 characters that can be constructed from
        the letters "s" and "e" and any one additional letter.

    All of the above query functions are built on top of a generic DAWG navigation function:

    DawgDictionary.navigate(navigator)
        Uses a navigation object to control the traversal of the graph and tabulate
        results. The navigation object should implement a number of interface functions,
        as documented in comments for the navigate() function.

    DawgDictionary.FindNavigator(word)
        A navigation class to find words by exact match. Used by DawgDictionary.find()

    DawgDictionary.PermutationNavigator(rack, minlen)
        A navigation class to find rack permutations. Used by DawgDictionary.find_permutations()

    DawgDictionary.MatchNavigator(rack, minlen)
        A navigation class to find words matching a pattern. Used by DawgDictionary.find_matches()

    See also comments in dawgbuilder.py

    Test code for this module is found in dawgtester.py

"""

from __future__ import annotations

from functools import lru_cache
import struct
from typing import Callable, Iterator, Optional, Tuple, List

import os
import threading
import abc

from alphabets import Alphabet


# Type definitions
IterTuple = Tuple[str, int]
PrefixNodes = Tuple[IterTuple, ...]
TwoLetterListTuple = Tuple[List[str], List[str]]
SortKeyFunc = Callable[[str], List[int]]


# Base project directory path
BASE_PATH = os.path.join(os.path.dirname(__file__), "..")


class PackedDawgDictionary:
    """Encapsulates a DAWG dictionary that is initialized from a packed
    binary file on disk and navigated as a byte buffer."""

    def __init__(self, alphabet: Alphabet) -> None:
        # The packed byte buffer
        self.b: Optional[bytes] = None
        # Lock to ensure that only one thread loads the dictionary
        self._lock = threading.Lock()
        self.alphabet = alphabet
        self.sortkey = alphabet.sortkey
        self.coding = alphabet.coding
        # Cached list of two letter words in this DAWG,
        # sorted by first letter and second letter
        self._two_letter: Tuple[List[str], List[str]] = ([], [])

    def load(self, fname: str) -> None:
        """Load a packed DAWG from a binary file"""
        with self._lock:
            # Ensure that we don't have multiple threads trying to load simultaneously
            if self.b is not None:
                # Already loaded
                return
            # Quickly gulp the file contents into the byte buffer
            with open(fname, mode="rb") as fin:
                self.b = fin.read()

    def find(self, word: str) -> bool:
        """Look for a word in the graph, returning True if it is found or False if not"""
        nav = FindNavigator(word)
        self.navigate(nav)
        return nav.is_found()

    def __contains__(self, word: str) -> bool:
        """Enable simple lookup syntax: "word" in dawgdict"""
        return self.find(word)

    def __hash__(self) -> int:
        """Return a hash value for this dictionary"""
        return id(self)

    def __eq__(self, other: object) -> bool:
        """Return True if this dictionary is equal to another"""
        return self is other

    def find_matches(self, pattern: str, sort: bool = True) -> List[str]:
        """Returns a list of words matching a pattern.
        The pattern contains characters and '?'-signs denoting wildcards.
        Characters are matched exactly, while the wildcards match any character.
        """
        nav = MatchNavigator(self.sortkey, pattern, sort)
        self.navigate(nav)
        return nav.result()

    def find_permutations(self, rack: str, minlen: int = 0) -> List[str]:
        """Returns a list of legal permutations of a rack of letters.
        The list is sorted in descending order by permutation length.
        The rack may contain question marks '?' as wildcards, matching all letters.
        Question marks should be used carefully as they can
        yield very large result sets.
        """
        nav = PermutationNavigator(self.sortkey, rack, minlen)
        self.navigate(nav)
        return nav.result()

    def navigate(self, nav: Navigator) -> None:
        """A generic function to navigate through the DAWG under
        the control of a navigation object.

        The navigation object should implement the following interface:

        def push_edge(firstchar)
            returns True if the edge should be entered or False if not
        def accepting()
            returns False if the navigator does not want more characters
        def accepts(newchar)
            returns True if the navigator will accept and 'eat' the new character
        def accept(matched, final)
            called to inform the navigator of a match and whether it is a final word
        def pop_edge()
            called when leaving an edge that has been navigated; returns False
            if there is no need to visit other edges
        def done()
            called when the navigation is completed
        """
        if self.b is None:
            # No graph: no navigation
            nav.done()
        else:
            Navigation(nav, self).go()

    def resume_navigation(
        self, nav: Navigator, prefix: str, nextnode: int, leftpart: str
    ) -> None:
        """Continue a previous navigation of the DAWG, using saved
        state information"""
        assert self.b is not None
        Navigation(nav, self).resume(prefix, nextnode, leftpart)

    def two_letter_words(self) -> TwoLetterListTuple:
        """Return the two letter words in this DAWG,
        sorted by first letter and by second letter"""
        if not self._two_letter[0]:
            # Cache has not yet been populated: calculate the lists
            sk = self.alphabet.sortkey
            # The list sorted by first letter
            tw0 = self.find_matches("??", sort=True)
            # The list sorted by second (last) letter
            tw1 = sorted(tw0, key=lambda w: sk(w[1] + w[0]))
            self._two_letter = (tw0, tw1)
        return self._two_letter


class Navigator(abc.ABC):
    """Base class for navigators that move through the DAWG,
    finding words or patterns or collecting information,
    for instance about possible moves"""

    is_resumable = False

    def __init__(self) -> None:
        pass

    @abc.abstractmethod
    def push_edge(self, firstchar: str) -> bool:
        """Returns True if the edge should be entered or False if not"""
        raise NotImplementedError

    @abc.abstractmethod
    def accepting(self) -> bool:
        """Returns False if the navigator does not want more characters"""
        raise NotImplementedError

    @abc.abstractmethod
    def accepts(self, newchar: str) -> bool:
        """Returns True if the navigator will accept the new character"""
        raise NotImplementedError

    # pylint: disable=unused-argument
    @abc.abstractmethod
    def accept(self, matched: str, final: bool) -> None:
        """Called to inform the navigator of a match and whether it is a final word"""
        raise NotImplementedError

    def accept_resumable(self, prefix: str, nextnode: int, matched: str) -> None:
        """This is not an abstract method since it is not mandatory to implement"""
        # If implemented in a subclass, set is_resumable = True
        raise NotImplementedError

    def pop_edge(self) -> bool:
        """Called when leaving an edge that has been navigated;
        returns False if there is no need to visit other edges"""
        # An implementation is not mandatory
        return False

    def done(self) -> None:
        """Called when the whole navigation is done"""
        # An implementation is not mandatory
        pass


class FindNavigator(Navigator):
    """A navigation class to be used with DawgDictionary.navigate()
    to find a particular word in the dictionary by exact match"""

    def __init__(self, word: str) -> None:
        super().__init__()
        self._word = word
        self._len = len(word)
        self._index = 0
        self._found = False

    def push_edge(self, firstchar: str) -> bool:
        """Returns True if the edge should be entered or False if not"""
        # Enter the edge if it fits where we are in the word
        return self._word[self._index] == firstchar

    def accepting(self) -> bool:
        """Returns False if the navigator does not want more characters"""
        # Don't go too deep
        return self._index < self._len

    def accepts(self, newchar: str) -> bool:
        """Returns True if the navigator will accept the new character"""
        if newchar != self._word[self._index]:
            return False
        # Match: move to the next index position
        self._index += 1
        return True

    # pylint: disable=unused-argument
    def accept(self, matched: str, final: bool) -> None:
        """Called to inform the navigator of a match and whether it is a final word"""
        if final and self._index == self._len:
            # Yes, this is what we were looking for
            # assert matched == self._word
            self._found = True

    def is_found(self) -> bool:
        """Return True if the sought word was found in the DAWG"""
        return self._found


class PermutationNavigator(Navigator):
    """A navigation class to be used with DawgDictionary.navigate()
    to find all permutations of a rack
    """

    def __init__(self, sortkey: SortKeyFunc, rack: str, minlen: int = 0) -> None:
        super().__init__()
        self._rack = rack
        self._stack: List[str] = []
        self._result: List[str] = []
        self._minlen = minlen
        self._sortkey = sortkey

    def push_edge(self, firstchar: str) -> bool:
        """Returns True if the edge should be entered or False if not"""
        # Follow all edges that match a letter in the rack
        # (which can be '?', matching all edges)
        rack = self._rack
        if not ((firstchar in rack) or ("?" in rack)):
            return False
        # Fit: save our rack and move into the edge
        self._stack.append(rack)
        return True

    def accepting(self) -> bool:
        """Returns False if the navigator does not want more characters"""
        # Continue as long as there is something left on the rack
        return bool(self._rack)

    def accepts(self, newchar: str) -> bool:
        """Returns True if the navigator will accept the new character"""
        rack = self._rack
        exactmatch = newchar in rack
        if (not exactmatch) and ("?" not in rack):
            # Can't continue with this prefix - we no longer have rack letters matching it
            return False
        # We're fine with this: accept the character and remove from the rack
        if exactmatch:
            self._rack = rack.replace(newchar, "", 1)
        else:
            self._rack = rack.replace("?", "", 1)
        return True

    def accept(self, matched: str, final: bool) -> None:
        """Called to inform the navigator of a match and whether it is a final word"""
        if final and len(matched) >= self._minlen:
            self._result.append(matched)

    def pop_edge(self) -> bool:
        """Called when leaving an edge that has been navigated"""
        self._rack = self._stack.pop()
        # We need to visit all outgoing edges, so return True
        return True

    def done(self) -> None:
        """Called when the whole navigation is done"""
        self._result.sort(key=lambda x: (-len(x), self._sortkey(x)))

    def result(self) -> List[str]:
        """Return the list of results accumulated during the navigation"""
        return self._result


class MatchNavigator(Navigator):
    """A navigation class to be used with DawgDictionary.navigate()
    to find all words matching a pattern
    """

    def __init__(self, sortkey: SortKeyFunc, pattern: str, sort: bool) -> None:
        super().__init__()
        self._pattern = pattern
        self._lenp = len(pattern)
        self._index = 0
        self._chmatch = pattern[0]
        self._wildcard = self._chmatch == "?"
        self._stack: List[Tuple[int, str, bool]] = []
        self._result: List[str] = []
        self._sort = sort
        self._sortkey = sortkey

    def push_edge(self, firstchar: str) -> bool:
        """Returns True if the edge should be entered or False if not"""
        # Follow all edges that match a letter in the rack
        # (which can be '?', matching all edges)
        if not self._wildcard and (firstchar != self._chmatch):
            return False
        # Fit: save our index and move into the edge
        self._stack.append((self._index, self._chmatch, self._wildcard))
        return True

    def accepting(self) -> bool:
        """Returns False if the navigator does not want more characters"""
        # Continue as long as there is something left to match
        return self._index < self._lenp

    def accepts(self, newchar: str) -> bool:
        """Returns True if the navigator will accept the new character"""
        if not self._wildcard and (newchar != self._chmatch):
            return False
        self._index += 1
        if self._index < self._lenp:
            self._chmatch = self._pattern[self._index]
            self._wildcard = self._chmatch == "?"
        return True

    def accept(self, matched: str, final: bool) -> None:
        """Called to inform the navigator of a match and whether it is a final word"""
        if final and self._index == self._lenp:
            # We have an entire pattern match
            # (Note that this could be relaxed to also return partial (shorter) pattern matches)
            self._result.append(matched)

    def pop_edge(self) -> bool:
        """Called when leaving an edge that has been navigated"""
        self._index, self._chmatch, self._wildcard = self._stack.pop()
        # We need to continue visiting edges only if this is a wildcard position
        return self._wildcard

    def done(self) -> None:
        """Called when the whole navigation is done"""
        if self._sort:
            self._result.sort(key=self._sortkey)

    def result(self) -> List[str]:
        """Return the list of results accumulated during the navigation"""
        return self._result


# The structure used to decode an edge offset from bytes
_UINT32 = struct.Struct("<L")


class Navigation:
    """Manages the state for a navigation while it is in progress"""

    def __init__(self, nav: Navigator, pd: PackedDawgDictionary) -> None:
        # Store the associated navigator
        self._nav = nav
        # The DAWG dictionary we are navigating
        self._pd = pd
        assert pd.b is not None
        self._b = pd.b
        # If the navigator implements accept_resumable(),
        # note it and call it with additional state information instead of
        # plain accept()
        self._resumable = nav.is_resumable

    @staticmethod
    def _iter_from_node(pd: PackedDawgDictionary, offset: int) -> Iterator[IterTuple]:
        """A generator for yielding prefixes and next node offset along an edge
        starting at the given offset in the DAWG bytes"""
        b = pd.b
        assert b is not None
        coding = pd.coding
        num_edges = b[offset] & 0x7F
        offset += 1
        for _ in range(num_edges):
            len_byte = b[offset]
            offset += 1
            if len_byte & 0x40:
                prefix = coding[len_byte & 0x3F]  # Single character
            else:
                len_byte &= 0x3F
                prefix = "".join(coding[b[offset + j]] for j in range(len_byte))
                offset += len_byte
            if b[offset - 1] & 0x80:
                # The last character of the prefix had a final marker: nextnode is 0
                nextnode = 0
            else:
                # Read the next node offset
                # Tuple of length 1, i.e. (n, )
                (nextnode,) = _UINT32.unpack_from(b, offset)
                offset += 4
            yield prefix, nextnode

    @staticmethod
    @lru_cache(maxsize=8 * 1024)  # 8K entries seems to be plenty
    def _tuple_from_node(pd: PackedDawgDictionary, offset: int) -> PrefixNodes:
        """Return a cached tuple of prefixes and next node offsets along an edge"""
        return tuple(Navigation._iter_from_node(pd, offset))

    def _navigate_from_node(self, offset: int, matched: str) -> None:
        """Starting from a given node, navigate outgoing edges"""
        # Go through the edges of this node and follow the ones
        # okayed by the navigator
        nav = self._nav
        for prefix, nextnode in Navigation._tuple_from_node(self._pd, offset):
            if nav.push_edge(prefix[0]):
                # This edge is a candidate: navigate through it
                self._navigate_from_edge(prefix, nextnode, matched)
                if not nav.pop_edge():
                    # Short-circuit and finish the loop if pop_edge() returns False
                    break

    def _navigate_from_edge(self, prefix: str, nextnode: int, matched: str) -> None:
        """Navigate along an edge, accepting partial and full matches"""
        # Go along the edge as long as the navigator is accepting
        b = self._b
        lenp = len(prefix)
        j = 0
        nav = self._nav
        while j < lenp and nav.accepting():
            # See if the navigator is OK with accepting the current character
            if not nav.accepts(prefix[j]):
                # Nope: we're done with this edge
                return
            # So far, we have a match: add a letter to the matched path
            matched += prefix[j]
            j += 1
            # Check whether the next prefix character is a vertical bar, denoting finality
            final = False
            if j < lenp:
                if prefix[j] == "|":
                    final = True
                    j += 1
            elif nextnode == 0 or b[nextnode] & 0x80:
                # If we're at the final char of the prefix and the next node is final,
                # set the final flag as well (there is no trailing vertical bar in this case)
                final = True
            # Tell the navigator where we are
            if self._resumable:
                # The navigator wants to know the position in the graph
                # so that navigation can be resumed later from this spot
                nav.accept_resumable(prefix[j:], nextnode, matched)
            else:
                # Normal navigator: tell it about the match
                nav.accept(matched, final)
        # We're done following the prefix for as long as it goes and
        # as long as the navigator was accepting
        if j < lenp:
            # We didn't complete the prefix, so the navigator must no longer
            # be interested (accepting): we're done
            return
        if nextnode != 0 and nav.accepting():
            # Gone through the entire edge and still have rack letters left:
            # continue with the next node
            self._navigate_from_node(nextnode, matched)

    def go(self) -> None:
        """Perform the navigation using the given navigator"""
        # The ship is ready to go
        if self._nav.accepting():
            # Leave shore and navigate the open seas
            self._navigate_from_node(0, "")
        self._nav.done()

    def resume(self, prefix: str, nextnode: int, matched: str) -> None:
        """Resume navigation from a previously saved state"""
        self._navigate_from_edge(prefix, nextnode, matched)

"""
# Debug instrumentation:
# Create a thread that runs every 30 seconds and logs the
# cache statistics for the Navigation._tuple_from_node() method
def _log_cache_stats() -> None:
    while True:
        time.sleep(30)
        logging.info(Navigation._tuple_from_node.cache_info())

threading.Thread(target=_log_cache_stats, daemon=True).start()
"""
