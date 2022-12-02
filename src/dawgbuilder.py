#!/usr/bin/env python3

"""

    DAWG dictionary builder

    Copyright (C) 2022 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    DawgBuilder uses a Directed Acyclic Word Graph (DAWG)
    to store a large set of words in an efficient structure in terms
    of storage and speed.

    The DAWG implementation is partially based on Steve Hanov's work
    (see http://stevehanov.ca/blog/index.php?id=115), which references
    a paper by Daciuk et al (http://www.aclweb.org/anthology/J00-1002.pdf).

    This implementation compresses node sequences with single edges between
    them into single multi-letter edges. It also removes redundant edges
    to "pure" final nodes.

    DawgBuilder reads a set of text input files containing plain words,
    one word per line, and outputs a text file with a compressed
    graph. This file is read by the DawgDictionary class; see
    dawgdictionary.py

    The output file is structured as a sequence of lines. Each line
    represents a node in the graph and contains information about
    outgoing edges from the node. Nodes are referred to by their
    line number, where the starting root node is in line 1 and subsequent
    nodes are numbered starting with 2.

    A node (line) is represented as follows:

    ['|']['_' prefix ':' nextnode]*

    If the node is a final node (i.e. a valid word is completed at
    the node), the first character in the line is
    a vertical bar ('|') followed by an underscore.
    The rest of the line is a sequence of edges where each edge
    is described by a prefix string followed by a colon (':')
    and the line number of the node following that edge. Edges are
    separated by underscores ('_'). The prefix string can contain
    embedded vertical bars indicating that the previous character was
    a final character in a valid word.

    Example:

    The following input word list (cf. http://tinyurl.com/kvhbyo2):

    car
    cars
    cat
    cats
    do
    dog
    dogs
    done
    ear
    ears
    eat
    eats

    generates this output graph:

    do:3_ca:2_ea:2
    t|s:0_r|s:0
    |_g|s:0_ne:0

    The root node in line 1 has three outgoing edges, "do" to node 3,
    "ca" to node 2, and "ea" to node 2.

    Node 2 (in line 2) has two edges, "t|s" to node 0 and "r|s" to node 0.
    This means that "cat" and "cats", "eat" and "eats" are valid words
    (on the first edge), as well as "car" and "cars", "ear" and "ears"
    (on the second edge).

    Node 3 (in line 3) is itself a final node, denoted by the vertical bar
    at the start of the line. Thus, "do" (coming in from the root) is a
    valid word, but so are "dog" and "dogs" (on the first edge) as well as
    "done" (on the second edge).

    Dictionary structure:

    Suppose the dictionary contains two words, 'word' and 'wolf'.
    This is represented by Python data structures as follows:

    root _Dawg -> {
        'w': _DawgNode(final=False, edges -> {
            'o': _DawgNode(final=False, edges -> {
                'r': _DawgNode(final=False, edges -> {
                    'd': _DawgNode(final=True, edges -> {})
                    }),
                'l': _DawgNode(final=False, edges -> {
                    'f': _DawgNode(final=True, edges -> {})
                    })
                })
            })
        }

"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, TypedDict

import os
import sys
import time

import binascii
import struct
import io

# The DAWG builder uses the collation (sorting) given by
# the current locale setting, typically 'is_IS' or 'en_US'
os.environ["PROJECT_ID"] = "explo-dev"
from languages import current_alphabet, set_locale


# Type definitions
DawgDict = Dict[str, Optional["_DawgNode"]]


MAXLEN = 48  # Longest possible word to be processed
WORD_MAXLEN = 15  # Longest possible word in a game vocabulary
COMMON_MAXLEN = 12  # Longest words in common word list used by weakest robot


class _DawgNode:

    """A _DawgNode is a node in a Directed Acyclic Word Graph (DAWG).
    It contains:
        * a node identifier (a simple unique sequence number);
        * a dictionary of edges (children) where each entry has a prefix
            (following letter(s)) together with its child _DawgNode;
        * and a Bool (final) indicating whether this node in the graph
            also marks the end of a legal word.

    A _DawgNode has a string representation which can be hashed to
    determine whether it is identical to a previously encountered node,
    i.e. whether it has the same final flag and the same edges with
    prefixes leading to the same child nodes. This assumes
    that the child nodes have already been subjected to the same
    test, i.e. whether they are identical to previously encountered
    nodes and, in that case, modified to point to the previous, identical
    subgraph. Each graph layer can thus depend on the (shallow) comparisons
    made in previous layers and deep comparisons are not necessary. This
    is an important optimization when building the graph.

    """

    # Running count of node identifiers
    # Zero is reserved for "None"
    _nextid = 1

    @staticmethod
    def sort_by_prefix(
        l: List[Tuple[str, Optional[_DawgNode]]]
    ) -> List[Tuple[str, Optional[_DawgNode]]]:
        """Return a list of (prefix, node) tuples sorted by prefix"""
        sortkey = current_alphabet().sortkey
        return sorted(l, key=lambda x: sortkey(x[0]))

    @staticmethod
    def stringify_edges(edges: DawgDict) -> str:
        """Utility function to create a compact descriptor string and
        hashable key for node edges"""
        edge_list = [
            prefix + ":" + ("0" if node is None else str(node.id))
            for prefix, node in _DawgNode.sort_by_prefix(list(edges.items()))
        ]
        return "_".join(edge_list)

    def __init__(self):
        self.id: int = _DawgNode._nextid
        _DawgNode._nextid += 1
        self.edges: DawgDict = dict()
        self.final = False
        self._strng = None  # Cached string representation of this node
        self._hash = None  # Hash of the final flag and a shallow traversal of the edges

    def __str__(self) -> str:
        """Return a string representation of this node, cached if possible"""
        if not self._strng:
            # We don't have a cached string representation: create it
            edges = _DawgNode.stringify_edges(self.edges)
            self._strng = "|_" + edges if self.final else edges
        return self._strng

    def __hash__(self) -> int:
        """Return a hash of this node, cached if possible"""
        if self._hash is None:
            # We don't have a cached hash: create it
            self._hash = self.__str__().__hash__()
        return self._hash

    def __eq__(self, o: Any) -> bool:
        """Use string equality based on the string representation of nodes"""
        if not isinstance(o, _DawgNode):
            return False
        return self.__str__() == o.__str__()

    def reset_id(self, newid: int) -> None:
        """Set a new id number for this node. This forces a reset of the cached data."""
        self.id = newid
        self._strng = None
        self._hash = None


class _Dawg:

    """Directed Acyclic Word Graph (DAWG)"""

    def __init__(self) -> None:
        self._lastword = ""
        self._lastlen = 0
        self._root: DawgDict = dict()
        # Initialize empty list of starting dictionaries
        self._dicts: List[Optional[DawgDict]] = [None for _ in range(MAXLEN)]
        self._dicts[0] = self._root
        # Initialize the result list of unique nodes

        # Keep a list of the values inserted too. Note that using
        # OrderedDict raises an exception while enumerating the values
        # (presumably because the dictionary has been altered).
        self._unique_nodes: Dict[Optional[_DawgNode], Optional[_DawgNode]] = dict()
        # Don't mess with the following unless you know what you're
        # doing - this is a hack to make sure dict enumeration and
        # renumbering of ids work correctly even under Python 3 dict
        # randomization
        self._unique_nodes_values: List[Optional[_DawgNode]] = list()

    def _collapse_branch(self, parent: DawgDict, prefix: str, node: _DawgNode) -> None:
        """Attempt to collapse a single branch of the tree"""

        di = node.edges
        assert di is not None

        # If the node has no outgoing edges, it must be a final node.
        # Optimize and reduce graph clutter by making the parent
        # point to None instead.

        if not di:
            assert node.final
            # We don't need to put a vertical bar (final marker) at
            # the end of the prefix; it's implicit
            parent[prefix] = None
            return

        # Attempt to collapse simple chains of single-letter nodes
        # with single outgoing edges into a single edge with a multi-letter prefix.
        # If any of the chained nodes has a final marker, add a vertical bar '|' to
        # the prefix instead.

        node_new: Optional[_DawgNode] = node

        if len(di) == 1:
            # Only one child: we can collapse
            lastd: Optional[_DawgNode] = None
            tail = ""
            for ch, nx in di.items():
                # There will only be one iteration of this loop
                tail = ch
                lastd = nx
            # Delete the child node and put a string of prefix characters into the root instead
            del parent[prefix]
            if node.final:
                tail = "|" + tail
            prefix += tail
            parent[prefix] = lastd
            node_new = lastd

        # If a node with the same signature (key) has already been generated,
        # i.e. having the same final flag and the same edges leading to the same
        # child nodes, replace the edge leading to this node with an edge
        # to the previously generated node.

        if node_new in self._unique_nodes:
            # Signature matches a previously generated node: replace the edge
            parent[prefix] = self._unique_nodes[node_new]
        else:
            # This is a new, unique signature: store it in the dictionary of unique nodes
            self._unique_nodes[node_new] = node_new
            self._unique_nodes_values.append(node_new)

    def _collapse(self, edges: Optional[DawgDict]) -> None:
        """Collapse and optimize the edges in the parent dict"""
        # Iterate through the letter position and
        # attempt to collapse all "simple" branches from it
        if edges:
            # We must iterate over a cloned list because
            # the underlying dict may be modified in _collapse_branch()
            for letter, node in list(edges.items()):
                if node:
                    self._collapse_branch(edges, letter, node)

    def _collapse_to(self, divergence: int) -> None:
        """Collapse the tree backwards from the point of divergence"""
        j = self._lastlen
        while j > divergence:
            if self._dicts[j]:
                self._collapse(self._dicts[j])
                self._dicts[j] = None
            j -= 1

    def add_word(self, wrd: str) -> None:
        """Add a word to the DAWG.
        Words are expected to arrive in sorted order.

        As an example, we may have these three words arriving in sequence:

        abbadísar
        abbadísarinnar  [extends last word by 5 letters]
        abbadísarstofa  [backtracks from last word by 5 letters]

        """
        # Sanity check: make sure the word is not too long
        lenword = len(wrd)
        if lenword >= MAXLEN:
            raise ValueError(
                "Word exceeds maximum length of {0} letters".format(MAXLEN)
            )
        # First see how many letters we have in common with the
        # last word we processed
        i = 0
        while i < lenword and i < self._lastlen and wrd[i] == self._lastword[i]:
            i += 1
        # Start from the point of last divergence in the tree
        # In the case of backtracking, collapse all previous outstanding branches
        self._collapse_to(i)
        # Add the (divergent) rest of the word
        d = self._dicts[i]  # Note that self._dicts[0] is self._root
        assert d is not None
        nd = None
        while i < lenword:
            nd = _DawgNode()
            # Add a new starting letter to the working dictionary,
            # with a fresh node containing an empty dictionary of subsequent letters
            d[wrd[i]] = nd  # pylint: disable=E1137
            d = nd.edges
            i += 1
            self._dicts[i] = d
        # We are at the node for the final letter in the word: mark it as such
        if nd is not None:
            nd.final = True
        # Save our position to optimize the handling of the next word
        self._lastword = wrd
        self._lastlen = lenword

    def finish(self):
        """Complete the optimization of the tree"""
        self._collapse_to(0)
        self._lastword = ""
        self._lastlen = 0
        self._collapse(self._root)
        # Renumber the nodes for a tidier graph and more compact output
        # 1 is the line number of the root in text output files, so we start with 2
        ix = 2
        for n in self._unique_nodes_values:
            if n is not None:
                n.reset_id(ix)
                ix += 1

    def _dump_level(self, level: int, d: DawgDict) -> None:
        """Dump a level of the tree and continue into sublevels by recursion"""
        for ch, nx in d.items():
            if not nx:
                continue
            s = " " * level + ch
            if nx.final:
                s += "|"
            s += " " * (50 - len(s))
            s += nx.__str__()
            print(s)
            if nx.edges:
                self._dump_level(level + 1, nx.edges)

    def dump(self) -> None:
        """Write a human-readable text representation of the DAWG to the standard output"""
        self._dump_level(0, self._root)
        print(
            "Total of {0} nodes and {1} edges with {2} prefix characters".format(
                self.num_unique_nodes(), self.num_edges(), self.num_edge_chars()
            )
        )
        for n in self._unique_nodes_values:
            if n is not None:
                print("Node {0}{1}".format(n.id, "|" if n.final else ""))
                for prefix, nd in n.edges.items():
                    print(
                        "   Edge {0} to node {1}".format(
                            prefix, 0 if nd is None else nd.id
                        )
                    )

    def num_unique_nodes(self) -> int:
        """Count the total number of unique nodes in the graph"""
        return len(self._unique_nodes)

    def num_edges(self) -> int:
        """Count the total number of edges between unique nodes in the graph"""
        edges = 0
        for n in self._unique_nodes_values:
            if n is not None:
                edges += len(n.edges)
        return edges

    def num_edge_chars(self) -> int:
        """Count the total number of edge prefix letters in the graph"""
        chars = 0
        for n in self._unique_nodes_values:
            if n is not None:
                for prefix in n.edges:
                    # Add the length of all prefixes to the edge, minus the vertical bar
                    # '|' which indicates a final character within the prefix
                    chars += len(prefix) - prefix.count("|")
        return chars

    def write_packed(self, packer: "_BinaryDawgPacker") -> None:
        """Write the optimized DAWG to a packer"""
        packer.start(len(self._root))
        # Start with the root edges
        sortfunc = _DawgNode.sort_by_prefix
        for prefix, nd in sortfunc(list(self._root.items())):
            if nd is None:
                # This can happen in Polish, where only one
                # word (ęsi) starts with the letter ę
                packer.edge(0, prefix)
            else:
                packer.edge(nd.id, prefix)
        for node in self._unique_nodes_values:
            if node is not None:
                packer.node_start(node.id, node.final, len(node.edges))
                for prefix, nd in sortfunc(list(node.edges.items())):
                    if nd is None:
                        packer.edge(0, prefix)
                    else:
                        packer.edge(nd.id, prefix)
                packer.node_end(node.id)
        packer.finish()

    def write_text(self, stream: io.TextIOWrapper) -> None:
        """Write the optimized DAWG to a text stream"""
        print("Output graph has {0} nodes".format(len(self._unique_nodes)))
        # We don't have to write node ids since they correspond to line numbers.
        # The root is always in the first line and the first node after the root has id 2.
        # Start with the root edges
        stream.write(_DawgNode.stringify_edges(self._root) + "\n")
        for node in self._unique_nodes_values:
            if node is not None:
                stream.write(node.__str__() + "\n")


class _BinaryDawgPacker:

    """_BinaryDawgPacker packs the DAWG data to a byte stream.

    The stream format is as follows:

    For each node:
        BYTE Node header
            [feeeeeee]
                f = final bit
                eeee = number of edges
        For each edge out of a node:
            BYTE Prefix header
                [ftnnnnnn]
                If t == 1 then
                    f = final bit of single prefix character
                    nnnnnn = single prefix character,
                        coded as an index into AÁBDÐEÉFGHIÍJKLMNOÓPRSTUÚVXYÝÞÆÖ
                else
                    00nnnnnn = number of prefix characters following
                    n * BYTE Prefix characters
                        [fccccccc]
                            f = final bit
                            ccccccc = prefix character,
                                coded as an index into AÁBDÐEÉFGHIÍJKLMNOÓPRSTUÚVXYÝÞÆÖ
            DWORD Offset of child node

    """

    BYTE = struct.Struct("<B")
    UINT32 = struct.Struct("<L")

    def __init__(self, stream: io.BytesIO, encoding: str) -> None:
        self._stream = stream
        # _locs is a dict of already written nodes and their stream locations
        self._locs: Dict[int, int] = dict()
        # _fixups is a dict of node ids and file positions where the
        # node id has been referenced without knowing where the node is
        # located
        self._fixups: Dict[int, List[int]] = dict()
        self._encoding = encoding

    def start(self, num_root_edges: int) -> None:
        """Write a starting byte with the number of root edges"""
        self._stream.write(self.BYTE.pack(num_root_edges))

    def node_start(self, ident: int, final: bool, num_edges: int) -> None:
        """Start a new node in the binary buffer"""
        stream = self._stream
        pos = stream.tell()
        if ident in self._fixups:
            # We have previously output references to this node without
            # knowing its location: fix'em now
            for fix in self._fixups[ident]:
                stream.seek(fix)
                stream.write(self.UINT32.pack(pos))
            stream.seek(pos)
            del self._fixups[ident]
        # Remember where we put this node
        self._locs[ident] = pos
        stream.write(self.BYTE.pack((0x80 if final else 0x00) | (num_edges & 0x7F)))

    def node_end(self, ident: int) -> None:
        """End a node in the binary buffer"""
        pass

    def edge(self, ident: int, prefix: str) -> None:
        """Write an edge into the binary buffer"""
        b = bytearray()
        stream = self._stream
        for c in prefix:
            if c == "|":
                b[-1] |= 0x80
            else:
                b.append(self._encoding.index(c))

        if ident == 0:
            # The next pointer is 0: mark the last character in the prefix
            assert b[-1] & 0x80 == 0
            b[-1] |= 0x80

        if len(b) == 1:
            # Save space on single-letter prefixes
            stream.write(self.BYTE.pack(b[0] | 0x40))
        else:
            stream.write(self.BYTE.pack(len(b) & 0x3F))
            stream.write(b)
        if ident == 0:
            # We've already written a null pointer marker
            pass
        elif ident in self._locs:
            # We've already written the node and know where it is: write its location
            stream.write(self.UINT32.pack(self._locs[ident]))
        else:
            # This is a forward reference to a node we haven't written yet:
            # reserve space for the node location and add a fixup
            pos = stream.tell()
            stream.write(
                self.UINT32.pack(0xFFFFFFFF)
            )  # Temporary - will be overwritten
            if ident not in self._fixups:
                self._fixups[ident] = []
            self._fixups[ident].append(pos)

    def finish(self) -> None:
        """Clear the temporary fixup stuff from memory"""
        self._locs = dict()
        self._fixups = dict()

    def dump(self) -> None:
        """Print the stream buffer in hexadecimal format"""
        buf: bytes = self._stream.getvalue()
        print("Total of {0} bytes".format(len(buf)))
        s = binascii.hexlify(buf).decode("ascii")
        BYTES_PER_LINE = 16
        CHARS_PER_LINE = BYTES_PER_LINE * 2
        i = 0
        addr = 0
        lens = len(s)
        while i < lens:
            line = s[i : i + CHARS_PER_LINE]
            print(
                "{0:08x}: {1}".format(
                    addr,
                    " ".join([line[j : j + 2] for j in range(0, len(line) - 1, 2)]),
                )
            )
            i += CHARS_PER_LINE
            addr += BYTES_PER_LINE


class DawgBuilder:

    """Creates a DAWG from word lists and writes the resulting
    graph to binary or text files.

    The word lists are assumed to be pre-sorted in ascending
    lexicographic order. They are automatically merged during
    processing to appear as one aggregated and sorted word list.
    """

    def __init__(self, encoding: str) -> None:
        self._dawg: Optional[_Dawg] = None
        self._encoding = encoding
        self._alphabet = set(encoding)

    class _InFile:
        """InFile represents a single sorted input file."""

        def __init__(
            self,
            relpath: str,
            fname: str,
            input_filter: Optional[Callable[[str], str]] = None,
        ) -> None:
            self._eof: bool = False
            self._nxt: Optional[str] = None
            self._key: Optional[List[int]] = None  # Sortkey for self._nxt
            self._sortkey = current_alphabet().sortkey
            self._input_filter = input_filter
            fpath = os.path.abspath(os.path.join(relpath, fname))
            self._fin = open(fpath, "r", encoding="utf-8")
            print("Opened input file {0}".format(fpath))
            self._init()

        def _init(self) -> None:
            # Read the first word from the file to initialize the iteration
            self.read_word()

        def read_word(self) -> bool:
            """Read lines until we have a legal word or EOF"""
            assert self._fin is not None
            f = self._input_filter
            while True:
                try:
                    line = next(self._fin).strip()
                except StopIteration:
                    # We're done with this file
                    self._eof = True
                    return False
                if not line:
                    continue
                if f is not None:
                    line = f(line)
                if line and len(line) < MAXLEN:
                    # Valid word
                    self._nxt = line
                    self._key = self._sortkey(line)
                    return True

        def next_word(self) -> Optional[str]:
            """Returns the next available word from this input file"""
            return None if self._eof else self._nxt

        def next_key(self) -> Optional[List[int]]:
            """Returns the sort key of the next available word from this input file"""
            return None if self._eof else self._key

        def has_word(self) -> bool:
            """True if a word is available, or False if EOF has been reached"""
            return not self._eof

        def close(self) -> None:
            """Close the associated file, if it is still open"""
            if self._fin is not None:
                self._fin.close()
            self._fin = None

    class _InFileToBeSorted(_InFile):
        """InFileToBeSorted represents an input file that should be pre-sorted in memory"""

        def _init(self) -> None:
            """Read the entire file and pre-sort it"""
            self._list: List[str] = []
            self._index = 0
            self._sortkey = current_alphabet().sortkey
            f = self._input_filter
            assert self._fin is not None
            try:
                for line in self._fin:
                    line = line.strip()
                    if not line:
                        continue
                    if f is not None:
                        line = f(line)
                    if line and len(line) < MAXLEN:
                        # Valid word
                        self._list.append(line)
            except StopIteration:
                pass
            finally:
                self._fin.close()
                self._fin = None
            self._len = len(self._list)
            self._list.sort(key=self._sortkey)
            self.read_word()

        def read_word(self) -> bool:
            if self._index >= self._len:
                self._eof = True
                return False
            self._nxt = self._list[self._index]
            self._key = self._sortkey(self._nxt)
            self._index += 1
            return True

        def close(self) -> None:
            """Close the associated file, if it is still open"""
            pass

    def _load(
        self,
        relpath: str,
        inputs: List[str],
        removals: Optional[str],
        word_filter: Optional[Callable[[str], bool]],
        input_filter: Optional[Callable[[str], str]] = None,
    ) -> None:
        """Load word lists into the DAWG from one or more static text files,
        assumed to be located in the relpath subdirectory.
        The text files should contain one word per line,
        encoded in UTF-8 format. Lines may end with CR/LF or LF only.
        Upper or lower case should be consistent throughout.
        All lower case is preferred. The words should appear in
        ascending sort order within each file. The input files will
        be merged in sorted order in the load process. Words found
        in the removals file will be removed from the output.
        """
        self._dawg = _Dawg()
        # Total number of words read from input files
        incount = 0
        # Total number of words written to output file
        # (may be less than incount because of filtering or duplicates)
        outcount = 0
        # Total number of duplicate words found in input files
        duplicates = 0
        # Count removed words due to the removed word list
        removed = 0
        # Enforce strict ascending lexicographic order
        lastword = None
        lastkey = None
        # Open the input files. The first (main) input file is assumed
        # to be pre-sorted. Other input files are sorted in memory before
        # being used.
        infiles = [
            DawgBuilder._InFile(relpath, f, input_filter=input_filter)
            if ix == 0
            else DawgBuilder._InFileToBeSorted(relpath, f, input_filter=input_filter)
            for ix, f in enumerate(inputs)
        ]
        # Open the removal file, if any
        if removals is None:
            removal = None
        else:
            removal = DawgBuilder._InFileToBeSorted(relpath, removals)
        remove_key = None if removal is None else removal.next_key()
        # Merge the inputs
        while True:
            smallest = None
            key_smallest: Optional[List[int]] = None
            # Find the smallest next word among the input files
            for f in infiles:
                if f.has_word():
                    if smallest is None:
                        smallest = f
                        key_smallest = smallest.next_key()
                    else:
                        # Use the sort ordering of the current locale to compare words
                        assert key_smallest is not None
                        key_f = f.next_key()
                        assert key_smallest is not None
                        assert key_f is not None
                        if key_f == key_smallest:
                            # We have the same word in two files: make sure we don't add it twice
                            f.read_word()
                            incount += 1
                            duplicates += 1
                        elif key_f < key_smallest:
                            # New smallest word
                            smallest = f
                            key_smallest = key_f
            if smallest is None:
                # All files exhausted: we're done
                break
            # We have the smallest word
            word = smallest.next_word()
            assert word is not None
            assert key_smallest is not None
            key = key_smallest
            assert key is not None
            incount += 1
            if lastkey and lastkey >= key:
                # Something appears to be wrong with the input sort order.
                # If it's a duplicate, we don't mind too much, but if it's out
                # of order, display a warning
                if lastkey > key:
                    print(
                        'Warning: input files should be in ascending order, but "{0}" > "{1}"'.format(
                            lastword, word
                        )
                    )
                else:
                    # Identical to previous word
                    print(f"Duplicate word: {word}")
                    duplicates += 1
            elif word_filter is None or word_filter(word):
                # This word passes the filter: check the removal list, if any
                while remove_key is not None and remove_key < key:
                    # Skip past words in the removal file as needed
                    assert removal is not None
                    removal.read_word()
                    remove_key = removal.next_key()
                if remove_key is not None and remove_key == key:
                    # Found a word to be removed
                    assert removal is not None
                    removal.read_word()
                    remove_key = removal.next_key()
                    removed += 1
                elif set(word) - self._alphabet:
                    print(
                        "The word '{0}' contains characters that are "
                        "not in the expected alphabet".format(word)
                    )
                else:
                    # Not a word to be removed: add it to the graph
                    self._dawg.add_word(word)
                    outcount += 1
                lastword = word
                lastkey = key
            if incount % 5000 == 0:
                # Progress indicator
                print("{0}...".format(incount), end="\r")
                sys.stdout.flush()
            # Advance to the next word in the file we read from
            smallest.read_word()
        # Done merging: close all files
        for f in infiles:
            assert not f.has_word()
            f.close()
        # Complete and clean up
        self._dawg.finish()
        print(
            "Finished loading {0} words, output {1} words, {2} duplicates skipped, {3} removed".format(
                incount, outcount, duplicates, removed
            )
        )

    def _output_binary(self, relpath: str, output: str) -> None:
        """Write the DAWG to a flattened binary output file with extension '.dawg'"""
        assert self._dawg is not None
        f = io.BytesIO()
        # Create a packer to flatten the tree onto a binary stream
        p = _BinaryDawgPacker(f, self._encoding)
        # Write the tree using the packer
        self._dawg.write_packed(p)
        # Write packed DAWG to binary file
        with open(
            os.path.abspath(os.path.join(relpath, output + ".bin.dawg")), "wb"
        ) as of:
            of.write(f.getvalue())
        f.close()

    def _output_text(self, relpath: str, output: str) -> None:
        """Write the DAWG to a text output file with extension '.text.dawg'"""
        assert self._dawg is not None
        fname = os.path.abspath(os.path.join(relpath, output + ".text.dawg"))
        with open(fname, "w", encoding="utf-8", newline="\n") as fout:
            self._dawg.write_text(fout)

    # pylint: disable=bad-continuation
    def build(
        self,
        inputs: List[str],
        output: str,
        relpath: str = "resources",
        word_filter: Optional[Callable[[str], bool]] = None,
        removals: Optional[str] = None,
        input_filter: Optional[Callable[[str], str]] = None,
    ):
        """Build a DAWG from input file(s) and write it to the output file(s)
        (potentially in multiple formats).
        The input files are assumed to be individually sorted in correct
        ascending alphabetical order. They will be merged in parallel into
        a single sorted stream and added to the DAWG.
        """
        # inputs is a list of input file names
        # output is an output file name without file type suffix (extension);
        # ".dawg" and ".text.dawg" will be appended depending on output formats
        # relpath is a relative path to the input and output files
        print("DawgBuilder starting...")
        if (not inputs) or (not output):
            # Nothing to do
            print("No inputs or no output: Nothing to do")
            return
        self._load(relpath, inputs, removals, word_filter, input_filter)
        # print("Dumping...")
        # self._dawg.dump()
        print("Outputting...")
        # self._output_text(relpath, output)
        self._output_binary(relpath, output)
        print("DawgBuilder done")


# Filter functions
# The resulting DAWG will include all words for which filter() returns True, and exclude others.
# Useful for excluding long words or words containing "foreign" characters.

# noinspection PyUnusedLocal
def nofilter(word: str) -> bool:  # pylint: disable=W0613
    """No filtering - include all input words in output graph"""
    return True


def filter_skrafl(word: str) -> bool:
    """Filtering for an Icelandic crossword game.
    Exclude words longer than WORD_MAXLEN letters (won't fit on board)
    Exclude words with non-Icelandic letters, i.e. C, Q, W, Z
    Exclude two-letter words in the word database that are not
    allowed according to the rules of 'Skraflfélag Íslands'
    """
    return len(word) <= WORD_MAXLEN


def filter_common(word: str) -> bool:
    """For the list of common words used by the weakest robot,
    skip words longer than 12 characters (those would almost
    never be used anyway)
    """
    return len(word) <= COMMON_MAXLEN


def run_test() -> None:
    """Build a DAWG from the files listed"""
    # This creates a DAWG from a single file named testwords.txt
    print("Starting DAWG build for testwords.txt")
    db = DawgBuilder(encoding=current_alphabet().order)
    t0 = time.time()
    db.build(
        ["testwords.txt"],  # Input files to be merged
        "testwords",  # Output file - full name will be testwords.text.dawg
        "resources",  # Subfolder of input and output files
    )
    t1 = time.time()
    print("Build took {0:.2f} seconds".format(t1 - t0))


def run_twl06() -> None:
    """Build a DAWG from the files listed"""
    # This creates a DAWG from a single file named twl06.txt,
    # the Tournament Word List version 6
    print("Starting DAWG build for twl06.txt")
    # Set the English-United States locale
    set_locale("en_US")
    db = DawgBuilder(encoding=current_alphabet().order)
    t0 = time.time()
    db.build(
        ["twl06.txt"],  # Input files to be merged
        "twl06",  # Output file - full name will be twl06.bin.dawg
        "resources",  # Subfolder of input and output files
    )
    t1 = time.time()
    print("Build took {0:.2f} seconds".format(t1 - t0))


def run_otcwl2014() -> None:
    """Build a DAWG from the files listed"""
    # This creates a DAWG from a single file named otcwl2014.txt
    print("Starting DAWG build for otcwl2014.txt")
    # Set the English-United States locale
    set_locale("en_US")
    db = DawgBuilder(encoding=current_alphabet().order)
    t0 = time.time()
    db.build(
        ["otcwl2014.txt"],  # Input files to be merged
        "otcwl2014",  # Output file - full name will be otcwl2014.bin.dawg
        "resources",  # Subfolder of input and output files
    )
    t1 = time.time()
    print("Build took {0:.2f} seconds".format(t1 - t0))


def run_sowpods() -> None:
    """Build a DAWG from the files listed"""
    # This creates a DAWG from a single file named sowpods.txt,
    # the combined European & U.S. English word list
    print("Starting DAWG build for sowpods.txt")
    # Set the English-GB locale
    set_locale("en_GB")
    db = DawgBuilder(encoding=current_alphabet().order)
    t0 = time.time()
    db.build(
        ["sowpods.txt"],  # Input files to be merged
        "sowpods",  # Output file - full name will be sowpods.bin.dawg
        "resources",  # Subfolder of input and output files
    )
    t1 = time.time()
    print("Build took {0:.2f} seconds".format(t1 - t0))


def run_osps37() -> None:
    """Build a DAWG from the files listed"""
    # This creates a DAWG from a single file named osps37.txt,
    # containing the Polish word list.
    print("Starting DAWG build for osps37.txt")

    def input_filter(line: str) -> str:
        """Return the first word in a line, lowercased"""
        a = line.split()
        return a[0].lower()

    # Set the generic Polish locale
    set_locale("pl")
    db = DawgBuilder(encoding=current_alphabet().order)
    t0 = time.time()
    db.build(
        ["osps37.txt"],  # Input files to be merged
        "osps37",  # Output file - full name will be osps37.bin.dawg
        "resources",  # Subfolder of input and output files
        input_filter=input_filter,
    )
    t1 = time.time()
    print("Build took {0:.2f} seconds".format(t1 - t0))


def run_skrafl() -> None:
    """Build a DAWG from the files listed"""
    # This creates a DAWG from the full database of Icelandic words in
    # 'Beygingarlýsing íslensks nútímamáls' (BIN), except abbreviations,
    # 'skammstafanir', and proper names, 'sérnöfn'.
    # The words in ordalisti.add.txt are added to BIN, and words in
    # ordalisti.remove.txt (known errors) are removed.
    # The result is about 2.3 million words, generating >100,000 graph nodes
    print("Starting DAWG build for skraflhjalp/netskrafl.appspot.com")
    set_locale("is_IS")

    db = DawgBuilder(encoding=current_alphabet().order)
    t0 = time.time()
    db.build(
        ["ordalisti.full.sorted.txt", "ordalisti.add.txt"],  # Input files to be merged
        "ordalisti",  # Output file - full name will be ordalisti.bin.dawg
        "resources",  # Subfolder of input and output files
        filter_skrafl,  # Word filter function to apply
        "ordalisti.remove.txt",  # Words to remove
    )
    t1 = time.time()
    print("Build took {0:.2f} seconds".format(t1 - t0))

    # Process Miðlungur vocabulary

    print("Starting DAWG build for Miðlungur")
    db = DawgBuilder(encoding=current_alphabet().order)
    t0 = time.time()
    # "isl"/"is_IS" specifies Icelandic sorting order - modify this for other languages
    db.build(
        ["ordalisti.mid.sorted.txt", "ordalisti.add.txt"],  # Input files to be merged
        "midlungur",  # Output file - full name will be midlungur.bin.dawg
        "resources",  # Subfolder of input and output files
        filter_skrafl,  # Word filter function to apply
        "ordalisti.remove.txt",  # Words to remove
    )
    t1 = time.time()
    print("Build took {0:.2f} seconds".format(t1 - t0))

    # Process Amlóði vocabulary

    print("Starting DAWG build for Amlóði")
    db = DawgBuilder(encoding=current_alphabet().order)
    t0 = time.time()
    # "isl"/"is_IS" specifies Icelandic sorting order - modify this for other languages
    db.build(
        ["ordalisti.aml.filtered.txt"],  # Input files to be merged
        "amlodi",  # Output file - full name will be amlodi.bin.dawg
        "resources",  # Subfolder of input and output files
        filter_common,  # Word filter function to apply
    )
    t1 = time.time()
    print("Build took {0:.2f} seconds".format(t1 - t0))

    # Test loading of DAWG
    from dawgdictionary import PackedDawgDictionary

    dawg = PackedDawgDictionary(current_alphabet())
    fpath = os.path.abspath(os.path.join("resources", "ordalisti.bin.dawg"))
    t0 = time.time()
    dawg.load(fpath)
    t1 = time.time()

    print("ordalisti.bin.dawg loaded in {0:.2f} seconds".format(t1 - t0))

    # Test loading of Miðlungur DAWG
    dawg = PackedDawgDictionary(current_alphabet())
    fpath = os.path.abspath(os.path.join("resources", "midlungur.bin.dawg"))
    t0 = time.time()
    dawg.load(fpath)
    t1 = time.time()

    print("midlungur.bin.dawg loaded in {0:.2f} seconds".format(t1 - t0))

    # Test loading of Amlóði DAWG
    dawg = PackedDawgDictionary(current_alphabet())
    fpath = os.path.abspath(os.path.join("resources", "amlodi.bin.dawg"))
    t0 = time.time()
    dawg.load(fpath)
    t1 = time.time()

    print("amlodi.bin.dawg loaded in {0:.2f} seconds".format(t1 - t0))

    print("DAWG builder run complete")


def run_icelandic_filter() -> None:
    """Read an Icelandic robot vocabulary and filter out words
    that occur rarely in the Icelandic Gigaword Corpus (IGC, Risamálheild),
    as measured by the icegrams database built by Miðeind"""

    print("Icelandic filtering in progress")

    MIN_ICELANDIC_FREQUENCY = 5

    from icegrams.ngrams import Ngrams

    # The name of the input file containing the robot vocabulary
    source = os.path.join("resources", "ordalisti.aml.sorted.txt")

    # Read the input file, which is sorted in descending order by frequency,
    # and filter the words
    ngrams = Ngrams()
    vocab: List[str] = []
    icnt = 0
    with open(source, "r", encoding="utf-8") as f:
        for word in f:
            word = word.strip()
            if not word:
                continue
            icnt += 1
            if len(word) == 2 or ngrams.freq(word) >= MIN_ICELANDIC_FREQUENCY:
                vocab.append(word)
            # else:
            #    print("Deleting {0}".format(word))

    # Write the filtered vocabulary to a file, always using LF line endings
    # even on Windows
    with open(
        os.path.join("resources", "ordalisti.aml.filtered.txt"),
        "w",
        encoding="utf-8",
        newline="\n",
    ) as f:
        for w in vocab:
            f.write(f"{w}\n")
    print(f"Icelandic filtering done; count was {icnt} but becomes {len(vocab)}")


def run_english_filter() -> None:
    """Read list of frequent English words, filter them by the
    two main vocabularies (SOWPODS and OTCWL2014) and add them
    to the two robot vocabularies for each main vocabulary,
    until we have enough words in each."""

    AML_VOCAB_SIZE = 20_000  # Easy robot vocabulary size
    MID_VOCAB_SIZE = 35_000  # Medium robot vocabulary size

    print(
        f"English filtering in progress, vocab size of {AML_VOCAB_SIZE}/{MID_VOCAB_SIZE}"
    )

    from dawgdictionary import PackedDawgDictionary

    # Load the OTCWL2014 vocabulary as a packed DAWG
    set_locale("en_US")
    otcwl2014 = PackedDawgDictionary(current_alphabet())
    otcwl2014.load(os.path.join("resources", "otcwl2014.bin.dawg"))

    # Load the SOWPODS vocabulary as a packed DAWG
    set_locale("en_UK")
    sowpods = PackedDawgDictionary(current_alphabet())
    sowpods.load(os.path.join("resources", "sowpods.bin.dawg"))

    # The name of the input file containing
    # the list of frequent English words
    source = os.path.join("resources", "english.freq.tsv")

    # Define our tasks

    class TaskDict(TypedDict):
        vocab: List[str]
        cnt: int
        size: int
        maxlen: int
        d: PackedDawgDictionary
        out: str

    tasks = [
        TaskDict(
            vocab=[],
            cnt=0,
            size=AML_VOCAB_SIZE,
            maxlen=12,  # Only include words up to 12 letters long
            d=otcwl2014,
            out="otcwl2014.aml.sorted.txt",
        ),
        TaskDict(
            vocab=[],
            cnt=0,
            size=MID_VOCAB_SIZE,
            maxlen=15,
            d=otcwl2014,
            out="otcwl2014.mid.sorted.txt",
        ),
        TaskDict(
            vocab=[],
            cnt=0,
            size=AML_VOCAB_SIZE,
            maxlen=12,  # Only include words up to 12 letters long
            d=sowpods,
            out="sowpods.aml.sorted.txt",
        ),
        TaskDict(
            vocab=[],
            cnt=0,
            size=MID_VOCAB_SIZE,
            maxlen=15,
            d=sowpods,
            out="sowpods.mid.sorted.txt",
        ),
    ]

    # Read the input file, which is sorted in descending order by frequency,
    # and filter the words
    cnt = 0
    with open(source, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cnt += 1
            a = line.split("\t")
            if len(a) != 2:
                continue
            word = a[0]
            # We only use words ranging from 3 to 15 letters, inclusive
            if not (2 < len(word) < 16):
                continue
            # For each task, check whether the word should be added
            for t in tasks:
                if t["cnt"] < t["size"] and len(word) <= t["maxlen"] and word in t["d"]:
                    t["vocab"].append(word)
                    t["cnt"] += 1
            # Circuit breaker: stop when all tasks are complete
            if all(t["cnt"] >= t["size"] for t in tasks):
                break
    for t in tasks:
        t["vocab"].sort()
        with open(
            os.path.join("resources", t["out"]), "w", encoding="utf-8", newline="\n"
        ) as f:
            for w in t["vocab"]:
                f.write(f"{w}\n")
    print(f"English filtering done after reading {cnt} lines from source")


def run_english_robot_vocabs() -> None:
    """Build DAWGS for English robot vocabularies"""
    print("Starting DAWG build for English robot vocabularies")

    set_locale("en_US")

    print("Starting DAWG build for Sif/otcwl2014")
    db = DawgBuilder(encoding=current_alphabet().order)
    t0 = time.time()
    db.build(
        ["otcwl2014.aml.sorted.txt"],  # Input files to be merged
        "otcwl2014.aml",  # Output file - full name will be otcwl2014.aml.bin.dawg
        "resources",  # Subfolder of input and output files
        filter_skrafl,  # Word filter function to apply
    )
    t1 = time.time()
    print("Build took {0:.2f} seconds".format(t1 - t0))

    print("Starting DAWG build for Frigg/otcwl2014")
    db = DawgBuilder(encoding=current_alphabet().order)
    t0 = time.time()
    db.build(
        ["otcwl2014.mid.sorted.txt"],  # Input files to be merged
        "otcwl2014.mid",  # Output file - full name will be otcwl2014.mid.bin.dawg
        "resources",  # Subfolder of input and output files
        filter_skrafl,  # Word filter function to apply
    )
    t1 = time.time()
    print("Build took {0:.2f} seconds".format(t1 - t0))

    set_locale("en_UK")

    print("Starting DAWG build for Sif/sowpods")
    db = DawgBuilder(encoding=current_alphabet().order)
    t0 = time.time()
    db.build(
        ["sowpods.aml.sorted.txt"],  # Input files to be merged
        "sowpods.aml",  # Output file - full name will be sowpods.aml.bin.dawg
        "resources",  # Subfolder of input and output files
        filter_skrafl,  # Word filter function to apply
    )
    t1 = time.time()
    print("Build took {0:.2f} seconds".format(t1 - t0))

    print("Starting DAWG build for Frigg/sowpods")
    db = DawgBuilder(encoding=current_alphabet().order)
    t0 = time.time()
    db.build(
        ["sowpods.mid.sorted.txt"],  # Input files to be merged
        "sowpods.mid",  # Output file - full name will be sowpods.mid.bin.dawg
        "resources",  # Subfolder of input and output files
        filter_skrafl,  # Word filter function to apply
    )
    t1 = time.time()
    print("Build took {0:.2f} seconds".format(t1 - t0))


if __name__ == "__main__":

    ALL_TASKS = [
        run_icelandic_filter,  # Remove rare Icelandic words from robot vocabularies
        run_skrafl,  # Icelandic
        run_osps37,  # Polish
        # run_twl06,
        run_otcwl2014,  # en_US
        run_sowpods,  # en_UK
        run_english_filter,
        run_english_robot_vocabs,
    ]

    def name(t: Callable[[], None]) -> str:
        return t.__name__[4:]

    alltasks = frozenset(name(t) for t in ALL_TASKS)

    def exit_with_help() -> None:
        print("Please specify a task to perform or 'all'.")
        print("The tasks are:", ", ".join(alltasks))
        exit(1)

    if len(sys.argv) < 2:
        exit_with_help()

    if len(sys.argv) == 2 and sys.argv[1] == "all":
        tasks = ALL_TASKS
    else:
        args = frozenset(sys.argv[1:])
        if not (args <= alltasks):
            exit_with_help()
        # Keep original task order
        tasks = [t for t in ALL_TASKS if name(t) in args]
        if not tasks:
            exit_with_help()

    for task in tasks:
        task()
