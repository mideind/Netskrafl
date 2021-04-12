"""

    Skraflplayer - an automatic SCRABBLE(tm) player

    Copyright (C) 2021 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The GNU General Public License, version 3, applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module finds and ranks all legal moves on
    a SCRABBLE(tm)-like board.

    The algorithm is based on the classic paper by Appel & Jacobson,
    "The World's Fastest Scrabble Program",
    http://www.cs.cmu.edu/afs/cs/academic/class/15451-s06/www/lectures/scrabble.pdf

    The main class in the module is called AutoPlayer. Given a game State,
    it finds all legal moves, ranks them and returns the 'best'
    (currently the highest-scoring) move.

    Moves are found by examining each one-dimensional Axis of the board
    in turn, i.e. 15 rows and 15 columns for a total of 30 axes.
    For each Axis an array of Squares is constructed. The cross-check set
    of each empty Square is calculated, i.e. the set of letters that form
    valid words by connecting with word parts across the square's Axis.
    To save processing time, the cross-check sets are also intersected with
    the letters in the rack, unless the rack contains a blank tile.

    Any empty square with a non-null cross-check set or adjacent to
    a covered square within the axis is a potential anchor square.
    Each anchor square is examined in turn, from "left" to "right".
    The algorithm roughly proceeds as follows:

    1) Count the number of empty non-anchor squares to the left of
        the anchor. Call the number 'maxleft'.
    2) Generate all permutations of rack tiles found by navigating
        from the root of the DAWG, of length 1..maxleft, i.e. all
        possible word beginnings from the rack.
    3) For each such permutation, attempt to complete the
        word by placing the rest of the available tiles on the
        anchor square and to its right.
    4) In any case, even if maxleft=0, place a starting tile on the
        anchor square and attempt to complete a word to its right.
    5) When placing a tile on the anchor square or to its right,
        do so under three constraints: (a) the cross-check
        set of the square in question; (b) that there is
        a path in the DAWG corresponding to the tiles that have
        been laid down so far, incl. step 2 and 3; (c) a matching
        tile is still available in the rack (with blank tiles always
        matching).
    6) If extending to the right and coming to a tile that is
        already on the board, it must correspond to the DAWG path
        being followed.
    7) If we are running off the edge of the axis, or have come
        to an empty square, and we are at a final node in the
        DAWG indicating that a word is completed, we have a candidate
        move. Calculate its score and add it to the list of potential
        moves.

    Steps 1)-3) above are mostly implemented in the class LeftPartNavigator,
    while steps 4)-7) are found in ExtendRightNavigator. These classes
    correspond to the Appel & Jacobson LeftPart and ExtendRight functions.

    Note: SCRABBLE is a registered trademark. This software or its author
    are in no way affiliated with or endorsed by the owners or licensees
    of the SCRABBLE trademark.

"""

from __future__ import annotations

from typing import Optional, List, Tuple, Dict, cast

import random

from dawgdictionary import Wordbase, PackedDawgDictionary
from languages import Alphabet, current_alphabet
from skraflmechanics import (
    State,
    Board,
    Cover,
    Rack,
    MoveBase,
    Move,
    ExchangeMove,
    PassMove,
)
from dawgdictionary import Navigator


# Type definitions
LeftPart = Tuple[str, str, str, int]
MoveTuple = Tuple[MoveBase, int]
MoveList = List[MoveTuple]


class Square:

    """Represents a single square within an axis.
    A square knows about its cross-checks, i.e. which letters can be
    legally placed in the square while matching correctly with word
    parts above and/or below the square.
    """

    def __init__(self) -> None:
        # Cross checks, i.e. possible letters to be placed here,
        # represented as a bit pattern
        self._cc = 0
        # The tile located here, '?' if blank tile
        self._tile: Optional[str] = None
        # The letter located here, including meaning of blank tile
        self._letter: Optional[str] = None
        # Is this an anchor square?
        self._anchor = False

    def init(self, autoplayer: AutoPlayer, row: int, col: int, crosscheck: int) -> None:
        """ Initialize this square from the board """
        board = autoplayer.board()
        self._tile = board.tile_at(row, col)
        self._letter = board.letter_at(row, col)
        # Cross checks and anchors
        self._cc = crosscheck
        if self.is_open() and board.has_adjacent(row, col):
            # Empty square with adjacent covered squares and nonzero cross-checks:
            # mark as anchor
            self.mark_anchor()

    def is_empty(self) -> bool:
        """ Is this square empty? """
        return self._letter == " "

    def is_open(self) -> bool:
        """ Can a new tile from the rack be placed here? """
        return self.is_empty() and bool(self._cc)

    def is_open_for(self, letter_bit: int) -> bool:
        """ Can this letter be placed here? """
        return bool(self._cc & letter_bit)

    @property
    def letter(self) -> str:
        """ Return the letter at this square """
        return self._letter or ""

    def mark_anchor(self) -> None:
        """ Mark this square as an anchor """
        self._anchor = True

    def is_anchor(self) -> bool:
        """ Is this an anchor square? """
        return self._anchor


class Axis:

    """Represents a one-dimensional axis on the board, either
    horizontal or vertical. This is used to find legal moves
    for an AutoPlayer.
    """

    def __init__(self, autoplayer: AutoPlayer, index: int, horizontal: bool) -> None:

        self._autoplayer = autoplayer
        self._sq = [Square() for _ in range(Board.SIZE)]
        self._index = index
        self._horizontal = horizontal
        self._rack = autoplayer.rack()
        # Bit pattern representing empty squares on this axis
        self._empty_bits = 0
        self._dawg = Wordbase.dawg()

    def is_horizontal(self) -> bool:
        """ Is this a horizontal (row) axis? """
        return self._horizontal

    def is_vertical(self) -> bool:
        """ Is this a vertical (column) axis? """
        return not self._horizontal

    def coordinate_of(self, index: int) -> Tuple[int, int]:
        """ Return the co-ordinate on the board of a square within this axis """
        return (self._index, index) if self._horizontal else (index, self._index)

    def coordinate_step(self) -> Tuple[int, int]:
        """ How to move along this axis on the board, (row,col) """
        return (0, 1) if self._horizontal else (1, 0)

    def letter_at(self, index: int) -> str:
        """ Return the letter at the index """
        return self._sq[index].letter

    def is_open(self, index: int) -> bool:
        """ Is the square at the index open (i.e. can a tile be placed there?) """
        return self._sq[index].is_open()

    def is_open_for(self, index: int, letter_bit: int) -> bool:
        """ Is the square at the index open for this letter? """
        return self._sq[index].is_open_for(letter_bit)

    def is_empty(self, index: int) -> bool:
        """ Is the square at the index empty? """
        return bool(self._empty_bits & (1 << index))

    @property
    def autoplayer(self) -> AutoPlayer:
        """ Return the associated Autoplayer instance """
        return self._autoplayer

    def mark_anchor(self, index: int) -> None:
        """Force the indicated square to be an anchor. Used in first move
        to mark the center square."""
        self._sq[index].mark_anchor()

    def init_crosschecks(self) -> None:
        """ Calculate and return a list of cross-check bit patterns for the indicated axis """

        alphabet = current_alphabet()
        # The cross-check set is the set of letters that can appear in a square
        # and make cross words (above/left and/or below/right of the square) valid
        board = self._autoplayer.board()
        # Prepare to visit all squares on the axis
        x, y = self.coordinate_of(0)
        xd, yd = self.coordinate_step()
        # Fetch the default cross-check bits, which depend on the rack.
        # If the rack contains a wildcard (blank tile), the default cc set
        # contains all letters in the Alphabet. Otherwise, it contains the
        # letters in the rack.
        all_cc = self._autoplayer.rack_bit_pattern()
        # Go through the open squares and calculate their cross-checks
        for ix in range(Board.SIZE):
            cc = all_cc  # Start with the default cross-check set
            if not board.is_covered(x, y):
                if self.is_horizontal():
                    above = board.letters_above(x, y)
                    below = board.letters_below(x, y)
                else:
                    above = board.letters_left(x, y)
                    below = board.letters_right(x, y)
                query = above or ""
                query += "?"
                if below:
                    query += below
                if len(query) > 1:
                    # Nontrivial cross-check: Query the word database
                    # for words that fit this pattern
                    # Don't need a sorted result
                    matches = self._dawg.find_matches(query, sort=False)
                    bits = 0
                    if matches:
                        cix = len(above) if above else 0
                        # Note the set of allowed letters here
                        bits = alphabet.bit_pattern(
                            "".join(wrd[cix] for wrd in matches)
                        )
                    # Reduce the cross-check set by intersecting it with the allowed set.
                    # If the cross-check set and the rack have nothing in common, this
                    # will lead to the square being marked as closed, which saves
                    # calculation later on
                    cc &= bits
            # Initialize the square
            self._sq[ix].init(self._autoplayer, x, y, cc)
            # Keep track of empty squares within the axis in a bit pattern for speed
            if self._sq[ix].is_empty():
                self._empty_bits |= 1 << ix
            x += xd
            y += yd

    def _gen_moves_from_anchor(
        self, index: int, maxleft: int, lpn: Optional[LeftPermutationNavigator]
    ) -> None:
        """ Find valid moves emanating (on the left and right) from this anchor """
        if maxleft == 0 and index > 0 and not self.is_empty(index - 1):
            # We have a left part already on the board: try to complete it
            leftpart = ""
            ix = index
            while ix > 0 and not self.is_empty(ix - 1):
                leftpart = self._sq[ix - 1].letter + leftpart
                ix -= 1
            # Use the ExtendRightNavigator to find valid words with this left part
            nav = LeftFindNavigator(leftpart)
            self._dawg.navigate(nav)
            ns = nav.state()
            if ns is not None:
                # We found a matching prefix in the graph
                _, prefix, next_node = ns
                # assert matched == leftpart
                rnav = ExtendRightNavigator(self, index, self._rack)
                self._dawg.resume_navigation(rnav, prefix, next_node, leftpart)
            return

        # We are not completing an existing left part
        # Begin by extending an empty prefix to the right, i.e. placing
        # tiles on the anchor square itself and to its right
        rnav = ExtendRightNavigator(self, index, self._rack)
        self._dawg.navigate(rnav)

        if maxleft > 0 and lpn is not None:
            # Follow this by an effort to permute left prefixes into the open space
            # to the left of the anchor square
            for left_len in range(1, maxleft + 1):
                lp_list = lpn.leftparts(left_len)
                if lp_list is not None:
                    for leftpart, rack_leave, prefix, next_node in lp_list:
                        rnav = ExtendRightNavigator(self, index, rack_leave)
                        self._dawg.resume_navigation(rnav, prefix, next_node, leftpart)

    def generate_moves(self, lpn: Optional[LeftPermutationNavigator]) -> None:
        """Find all valid moves on this axis by attempting to place tiles
        at and around all anchor squares"""
        last_anchor = -1
        len_rack = len(self._rack)
        for i in range(Board.SIZE):
            if self._sq[i].is_anchor():
                # Count the consecutive open, non-anchor squares on the left of the anchor
                open_sq = 0
                left = i
                # pylint: disable=bad-continuation
                while (
                    left > 0
                    and left > (last_anchor + 1)
                    and self._sq[left - 1].is_open()
                ):
                    open_sq += 1
                    left -= 1
                # We have a maximum left part length of min(open_sq, len_rack-1) as the anchor
                # square itself must always be filled from the rack
                self._gen_moves_from_anchor(i, min(open_sq, len_rack - 1), lpn)
                last_anchor = i


class LeftPermutationNavigator(Navigator):

    """A navigation class to be used with DawgDictionary.navigate()
    to find all left parts of words that are possible with
    a particular rack. The results are accumulated by length.
    This calculation is only done once at the start of move
    generation for a particular rack and board.
    """

    is_resumable = True

    def __init__(self, rack: str) -> None:
        super().__init__()
        self._rack = rack
        self._stack: List[Tuple[str, int]] = []
        self._maxleft = len(rack) - 1  # One tile on the anchor itself
        # assert self._maxleft > 0
        self._leftparts: List[Optional[List[LeftPart]]] = [
            None for _ in range(self._maxleft)
        ]
        self._index = 0

    def leftparts(self, length: int) -> Optional[List[LeftPart]]:
        """ Returns a list of leftparts of the length requested """
        return self._leftparts[length - 1] if 0 < length <= self._maxleft else None

    def push_edge(self, firstchar: str) -> bool:
        """ Returns True if the edge should be entered or False if not """
        # Follow all edges that match a letter in the rack
        # (which can be '?', matching all edges)
        if not ((firstchar in self._rack) or ("?" in self._rack)):
            return False
        # Fit: save our rack and move into the edge
        self._stack.append((self._rack, self._index))
        return True

    def accepting(self) -> bool:
        """ Returns False if the navigator does not want more characters """
        # Continue until we have generated all left parts possible from the
        # rack but leaving at least one tile
        return self._index < self._maxleft

    def accepts(self, newchar: str) -> bool:
        """ Returns True if the navigator will accept the new character """
        exact_match = newchar in self._rack
        if (not exact_match) and ("?" not in self._rack):
            # Can't continue with this prefix - we no longer have rack letters matching it
            return False
        # We're fine with this: accept the character and remove from the rack
        self._index += 1
        if exact_match:
            self._rack = self._rack.replace(newchar, "", 1)
        else:
            self._rack = self._rack.replace("?", "", 1)
        return True

    def accept(self, matched: str, final: bool) -> None:
        """ Called to inform the navigator of a match and whether it is a final word """
        # Should not be called, as is_resumable is set to True
        raise NotImplementedError

    def accept_resumable(self, prefix: str, nextnode: int, matched: str) -> None:
        """ Called to inform the navigator of a match and whether it is a final word """
        # Accumulate all possible left parts, by length
        lm = len(matched) - 1
        if self._leftparts[lm] is None:
            self._leftparts[lm] = list()
        # Store the matched word part as well as the remaining part
        # of the prefix of the edge we were on, and the next node.
        # This gives us the ability to resume the navigation later at
        # the saved point, to generate right parts.
        lp = self._leftparts[lm]
        assert lp is not None
        lp.append((matched, self._rack, prefix, nextnode))

    def pop_edge(self) -> bool:
        """ Called when leaving an edge that has been navigated """
        self._rack, self._index = self._stack.pop()
        # We need to visit all outgoing edges, so return True
        return True


class LeftFindNavigator(Navigator):

    """A navigation class to trace a left part that is
    already on the board, and note its ending position in
    the graph.
    """

    is_resumable = True

    def __init__(self, prefix):
        super().__init__()
        # The prefix to the left of the anchor
        self._prefix = prefix
        self._lenp = len(prefix)
        # Prefix index
        self._pix = 0
        self._state = None

    def state(self):
        """ Returns the current state of the navigator """
        return self._state

    def push_edge(self, firstchar):
        """ Returns True if the edge should be entered or False if not """
        # If we are still navigating through the prefix, do a simple compare
        return firstchar == self._prefix[self._pix]

    def accepting(self):
        """ Returns False if the navigator does not want more characters """
        return self._pix < self._lenp

    def accepts(self, newchar):
        """ Returns True if the navigator will accept the new character """
        if self._prefix[self._pix] != newchar:
            # assert False
            return False  # Should not happen - all prefixes should exist in the graph
        # So far, so good: move on
        self._pix += 1
        return True

    def accept(self, matched: str, final: bool) -> None:
        """ Called to inform the navigator of a match and whether it is a final word """
        # Should not be called, as is_resumable is set to True
        raise NotImplementedError

    def accept_resumable(self, prefix, nextnode, matched):
        """ Called to inform the navigator of a match and whether it is a final word """
        if self._pix == self._lenp:
            # Found the left part: save the position (state)
            self._state = (matched, prefix, nextnode)


class Match:

    """ Return codes for the _check() function in ExtendRightNavigator """

    def __init__(self):
        pass

    NO = 0
    BOARD_TILE = 1
    RACK_TILE = 2


class ExtendRightNavigator(Navigator):

    """A navigation class to be used with DawgDictionary.navigate()
    to perform the Appel & Jacobson ExtendRight function. This
    places rack tiles on and to the right of an anchor square, in
    conformance with the cross-checks and the tiles already on
    the board.
    """

    def __init__(self, axis, anchor, rack):
        super().__init__()
        self._axis = axis
        self._rack = rack
        self._anchor = anchor
        # The tile we are placing next
        self._index = anchor
        self._stack = []
        self._wildcard_in_rack = "?" in rack
        # Cache the initial check we do when pushing into an edge
        self._last_check = None
        self._letter_bit = current_alphabet().letter_bit

    def _check(self, ch):
        """Check whether the letter ch could be placed at the
        current square, given the cross-checks and the rack"""
        axis = self._axis
        l_at_sq = axis.letter_at(self._index)
        if l_at_sq != " ":
            # There is a tile already in the square: we must match it exactly
            return Match.BOARD_TILE if ch == l_at_sq else Match.NO
        # Does the current rack allow this letter?
        if not (self._wildcard_in_rack or ch in self._rack):
            return Match.NO
        # Open square: apply cross-check constraints to the rack
        # Would this character pass the cross-checks?
        return (
            Match.RACK_TILE
            if axis.is_open_for(self._index, self._letter_bit[ch])
            else Match.NO
        )

    def push_edge(self, firstchar):
        """ Returns True if the edge should be entered or False if not """
        # We are in the right part: check whether we have a potential match
        self._last_check = self._check(firstchar)
        if self._last_check == Match.NO:
            return False
        # Match: save our rack and our index and move into the edge
        self._stack.append((self._rack, self._index, self._wildcard_in_rack))
        return True

    def accepting(self):
        """ Returns False if the navigator does not want more characters """
        # Continue as long as there is something left to check
        if self._index >= Board.SIZE:
            # Gone off the board edge
            return False
        # Otherwise, continue while we have something on the rack
        # or we're at an occupied square
        return bool(self._rack) or not self._axis.is_empty(self._index)

    def accepts(self, newchar):
        """ Returns True if the navigator will accept the new character """
        # We are on the anchor square or to its right
        # Use the cached check from push_edge if we have one
        match = self._check(newchar) if self._last_check is None else self._last_check
        self._last_check = None
        if match == Match.NO:
            # Something doesn't fit anymore, so we're done with this edge
            return False
        # We're fine with this: accept the character and remove from the rack
        self._index += 1
        if match == Match.RACK_TILE:
            # We used a rack tile: remove it from the rack before continuing
            if newchar in self._rack:
                self._rack = self._rack.replace(newchar, "", 1)
            else:
                # Must be wildcard: remove it
                # assert "?" in self._rack
                self._rack = self._rack.replace("?", "", 1)
            self._wildcard_in_rack = "?" in self._rack
        return True

    def accept(self, matched, final):
        """ Called to inform the navigator of a match and whether it is a final word """
        # pylint: disable=bad-continuation
        if (
            final
            and len(matched) > 1
            and (self._index >= Board.SIZE or self._axis.is_empty(self._index))
        ):

            # Solution found - make a Move object for it and add it to the AutoPlayer's list
            ix = self._index - len(matched)  # The word's starting index within the axis
            row, col = self._axis.coordinate_of(ix)
            xd, yd = self._axis.coordinate_step()
            move = Move(matched, row, col, self._axis.is_horizontal())
            # Fetch the rack as it was at the beginning of move generation
            autoplayer = self._axis.autoplayer
            rack = autoplayer.rack()
            tiles = ""
            for c in matched:
                if self._axis.is_empty(ix):
                    # Empty square that is being covered by this move
                    # Find out whether it is a blank or normal letter tile
                    if c in rack:
                        rack = rack.replace(c, "", 1)
                        tile = c
                        tiles += c
                    else:
                        # Must be a wildcard match
                        rack = rack.replace("?", "", 1)
                        tile = "?"
                        tiles += tile + c
                    # assert row in range(Board.SIZE)
                    # assert col in range(Board.SIZE)
                    # Add this cover to the Move object
                    move.add_validated_cover(Cover(row, col, tile, c))
                else:
                    tiles += c
                ix += 1
                row += xd
                col += yd
            # Note the tiles played in the move
            move.set_tiles(tiles)
            # Check that we've picked off the correct number of tiles
            # assert len(rack) == len(self._rack)
            autoplayer.add_candidate(move)

    def pop_edge(self):
        """ Called when leaving an edge that has been navigated """
        self._rack, self._index, self._wildcard_in_rack = self._stack.pop()
        # Once past the prefix, we need to visit all outgoing edges, so return True
        return True


class AutoPlayer:

    """Implements an automatic, computer-controlled player.
    All legal moves on the board are generated and the
    best move is then selected within the _find_best_move()
    function. This base class has a simple implementation
    of _find_best_move() that always chooses the best-scoring
    move. Other derived classes, such as AutoPlayer_MinMax,
    use more sophisticated heuristics to choose a move.
    """

    # The robot level that uses only common words
    AUTOPLAYER_COMMON = 15
    # The robot level that plays medium-heavy words
    AUTOPLAYER_MEDIUM = 8

    @staticmethod
    def create(state, robot_level: int = 0) -> AutoPlayer:
        """ Create an Autoplayer instance of the desired ability level """
        if robot_level >= AutoPlayer.AUTOPLAYER_COMMON:
            # Create an AutoPlayer that only plays common words
            return AutoPlayer_Common(state)
        if robot_level >= AutoPlayer.AUTOPLAYER_MEDIUM:
            # Create an AutoPlayer that plays medium-heavy words
            return AutoPlayer_Medium(state)
        # Create a normal AutoPlayer using the entire vocabulary
        return AutoPlayer(state)

    def __init__(self, state: State) -> None:

        # List of valid, candidate moves
        self._candidates: List[MoveBase] = []
        self._state = state
        self._board = state.board()
        # The rack that the autoplayer has to work with
        self._rack = state.player_rack().contents()

        # Calculate a bit pattern representation of the rack
        if "?" in self._rack:
            # Wildcard in rack: all letters allowed
            self._rack_bit_pattern = current_alphabet().all_bits_set()
        else:
            # No wildcard: limits the possibilities of covering squares
            self._rack_bit_pattern = current_alphabet().bit_pattern(self._rack)

    def board(self) -> Board:
        """ Return the board """
        return self._board

    def rack(self) -> str:
        """ Return the rack, as a string of tiles """
        return self._rack

    def rack_bit_pattern(self) -> int:
        """ Return the bit pattern corresponding to the rack """
        return self._rack_bit_pattern

    def candidates(self) -> List[MoveBase]:
        """ The list of valid, candidate moves """
        return self._candidates

    def add_candidate(self, move: MoveBase) -> None:
        """ Add a candidate move to the AutoPlayer's list """
        self._candidates.append(move)

    def _axis_from_row(self, row: int) -> Axis:
        """ Create and initialize an Axis from a board row """
        return Axis(self, row, True)  # Horizontal

    def _axis_from_column(self, col: int) -> Axis:
        """ Create and initialize an Axis from a board column """
        return Axis(self, col, False)  # Vertical

    def generate_move(self) -> MoveBase:
        """ Finds and returns a Move object to be played """
        return self._generate_move(depth=1)

    def generate_best_moves(self, max_number: int = 0) -> MoveList:
        """ Returns a list in descending order of the n best moves, or all moves if n <= 0 """
        self._generate_candidates()
        if not self._candidates:
            # No candidates: no best move
            return []
        sorted_candidates = self._score_candidates()
        if max_number <= 0:
            # Return entire list if max_number <= 0
            return sorted_candidates
        # Return the top candidates
        return sorted_candidates[0:max_number]

    def _generate_candidates(self) -> None:
        """ Generate a fresh candidate list """

        self._candidates = []
        # Start by generating all possible permutations of the
        # rack that form left parts of words, ordering them by length
        lpn: Optional[LeftPermutationNavigator]
        if len(self._rack) > 1:
            lpn = LeftPermutationNavigator(self._rack)
            Wordbase.dawg().navigate(lpn)
        else:
            lpn = None

        # Generate moves in one-dimensional space by looking at each axis
        # (row or column) on the board separately

        if self._board.is_empty():
            # Special case for first move: must pass through the starting
            # square, which is an anchor. We choose randomly to find either
            # horizontal or vertical moves. The move lists for both directions
            # are identical, apart from the symmetrical reflection of the coordinates.
            ssq_row, ssq_col = self.board().start_square
            if random.choice((False, True)):
                # Vertical move
                axis = self._axis_from_column(ssq_col)
                axis.init_crosschecks()
                # Mark the starting anchor
                axis.mark_anchor(ssq_row)
            else:
                # Horizontal move
                axis = self._axis_from_row(ssq_row)
                axis.init_crosschecks()
                # Mark the starting anchor
                axis.mark_anchor(ssq_col)
            axis.generate_moves(lpn)
        else:
            # Normal move: go through all 15 (row) + 15 (column) axes and generate
            # valid moves within each of them
            for r in range(Board.SIZE):
                axis = self._axis_from_row(r)
                axis.init_crosschecks()
                axis.generate_moves(lpn)
            for c in range(Board.SIZE):
                axis = self._axis_from_column(c)
                axis.init_crosschecks()
                axis.generate_moves(lpn)

    def _generate_move(self, depth: int) -> MoveBase:
        """ Finds and returns a Move object to be played, eventually weighted by countermoves """

        # Generate a fresh list of candidate moves
        self._generate_candidates()

        # Pick the best move from the candidate list
        move = self._find_best_move(depth)
        if move is not None:
            return move

        # Can't do anything: try exchanging all tiles
        if self._state.is_exchange_allowed():
            return ExchangeMove(self.rack())

        # If we can't exchange tiles, we have to pass
        return PassMove()

    def _score_candidates(self) -> MoveList:
        """ Calculate the score of each candidate """

        scored_candidates = [(m, self._state.score(m)) for m in self._candidates]

        def keyfunc(x: MoveTuple) -> Tuple:
            """Sort moves first by descending score;
            in case of ties prefer shorter words"""
            # More sophisticated logic can be inserted here,
            # including whether triple-word-score opportunities
            # are being opened for the opponent, minimal use
            # of blank tiles, leaving a good vowel/consonant
            # balance on the rack, etc.
            return (-x[1], x[0].num_covers())

        def keyfunc_firstmove(x: MoveTuple) -> Tuple:
            """Special case for first move:
            Sort moves first by descending score, and in case of ties,
            try to go to the upper half of the board for a more open game
            """
            # !!! FIXME: On the Explo board, there is no need to encourage
            # !!! going to the upper half of the board
            m, sc = x
            assert isinstance(m, Move)
            return (-sc, m.row)

        # Sort the candidate moves using the appropriate key function
        if self._board.is_empty():
            # First move
            scored_candidates.sort(key=keyfunc_firstmove)
        else:
            # Subsequent moves
            scored_candidates.sort(key=keyfunc)
        return scored_candidates

    def _pick_candidate(self, scored_candidates: MoveList) -> Optional[MoveBase]:
        """ From a sorted list of >1 scored candidates, pick a move to make """
        return scored_candidates[0][0]

    # pylint: disable=unused-argument
    def _find_best_move(self, depth: int) -> Optional[MoveBase]:
        """ Analyze the list of candidate moves and pick the highest-scoring one """

        if not self._candidates:
            # No moves: must exchange or pass instead
            return None

        if len(self._candidates) == 1:
            # Only one legal move: play it without further complication
            return self._candidates[0]

        return self._pick_candidate(self._score_candidates())


class AutoPlayer_Custom(AutoPlayer):

    """ This subclass of AutoPlayer only plays words from a particular vocabulary """

    # The number of candidate moves to pick from, randomly
    NUM_TO_PICK_FROM: int

    # The custom vocabulary used by this robot
    VOCABULARY: PackedDawgDictionary

    def __init__(self, state: State) -> None:
        super().__init__(state)

    def _pick_candidate(self, scored_candidates: MoveList) -> Optional[MoveBase]:
        """ From a sorted list of >1 scored candidates, pick a move to make """
        # Custom dictionary
        vocab = self.VOCABULARY
        play_one_of = self.NUM_TO_PICK_FROM
        playable_candidates: MoveList = []
        num_candidates = len(scored_candidates)
        # Iterate through the candidates in descending score order
        # until we have enough playable ones or we have exhausted the list
        i = 0  # Candidate index
        p = 0  # Playable index
        while p < play_one_of and i < num_candidates:
            m, score = scored_candidates[i]  # Candidate move
            assert isinstance(m, Move)
            w = m.word()  # The principal word being played
            if len(w) == 2 or w in vocab:
                # This one is playable - but we still won't put it on
                # the candidate list if has the same score as the
                # first (top-scoring) playable word
                if p == 1 and score == playable_candidates[0][1]:
                    pass
                else:
                    playable_candidates.append(scored_candidates[i])
                    p += 1
            i += 1
        # Now we have a list of up to NUM_TO_PICK_FROM playable moves
        if p == 0:
            # No playable move: give up and do an Exchange or Pass instead
            return None
        # Pick a move at random from the playable list
        return playable_candidates[random.randint(0, p - 1)][0]


class AutoPlayer_Medium(AutoPlayer_Custom):

    """ This robot plays one of 8 not-super-rare words """

    # This robot plays one of the 10 top candidate moves
    NUM_TO_PICK_FROM = 10

    # Return the vocabulary of medium-heavy words
    VOCABULARY = Wordbase.dawg_medium()

    def __init__(self, state: State) -> None:
        super().__init__(state)


class AutoPlayer_Common(AutoPlayer_Custom):

    """ This robot only plays words from a list of common words """

    # This robot plays one of the 10 top candidate moves
    NUM_TO_PICK_FROM = 20

    # Return the vocabulary of common words
    VOCABULARY = Wordbase.dawg_common()

    def __init__(self, state: State) -> None:
        super().__init__(state)


class AutoPlayer_MiniMax(AutoPlayer):

    """This subclass of AutoPlayer uses a MiniMax algorithm to
    select a move to play from the list of valid moves.
    """

    def __init__(self, state: State) -> None:
        super().__init__(state)

    def _find_best_move(self, depth: int) -> Optional[MoveBase]:
        """ Analyze the list of candidate moves and pick the best one """

        # assert depth >= 0

        if not self._candidates:
            # No moves: must exchange or pass instead
            return None

        if len(self._candidates) == 1:
            # Only one legal move: play it
            return self._candidates[0]

        # TBD: Consider looking at exchange moves if there are
        # few and weak candidates

        # Calculate the score of each candidate
        scored_candidates = [(m, self._state.score(m)) for m in self._candidates]

        def keyfunc(x: MoveTuple) -> Tuple:
            """Sort moves first by descending score;
            in case of ties prefer shorter words"""
            # More sophisticated logic could be inserted here,
            # including whether triple-word-score opportunities
            # are being opened for the opponent, minimal use
            # of blank tiles, leaving a good vowel/consonant
            # balance on the rack, etc.
            return (-x[1], x[0].num_covers())

        def keyfunc_firstmove(x: MoveTuple) -> Tuple:
            """Special case for first move:
            Sort moves first by descending score, and in case of ties,
            try to go to the upper half of the board for a more open game"""
            m, sc = x
            assert isinstance(m, Move)
            return (-sc, m.row)

        # Sort the candidate moves using the appropriate key function
        if self._board.is_empty():
            # First move
            scored_candidates.sort(key=keyfunc_firstmove)
        else:
            # Subsequent moves
            scored_candidates.sort(key=keyfunc)

        # If we're not going deeper into the minimax analysis,
        # cut the crap and simply return the top scoring move
        if depth == 0:
            return scored_candidates[0][0]

        # Weigh top candidates by alpha-beta testing of potential
        # moves and counter-moves

        # TBD: In the endgame, if we have moves that complete the game
        # (use all rack tiles) we need not consider opponent countermoves

        NUM_TEST_RACKS = 20  # How many random test racks to try for statistical average
        NUM_CANDIDATES = 12  # How many top candidates do we look at with MiniMax?

        weighted_candidates: List[Tuple[MoveBase, int, float]] = []
        min_score: Optional[float] = None

        # pylint: disable=superfluous-parens

        print("Looking at {0} top scoring candidate moves".format(NUM_CANDIDATES))
        # Look at the top scoring candidates
        for m, score in scored_candidates[0:NUM_CANDIDATES]:

            print("Candidate move {0} with raw score {1}".format(m, score))

            # Create a game state where the candidate move has been played
            teststate = State(copy=self._state)  # Copy constructor
            teststate.apply_move(m)

            countermoves = list()

            if teststate.is_game_over():
                # This move finishes the game. The opponent then scores nothing
                # (and in fact we get her tile score, but leave that aside here)
                avg_score = 0.0
                countermoves.append(0)
            else:
                # Loop over NUM_TEST_RACKS random racks to find
                # the average countermove score
                sum_score = 0
                rackscores: Dict[str, int] = dict()
                for _ in range(NUM_TEST_RACKS):
                    # Make sure we test this for a random opponent rack
                    teststate.randomize_and_sort_rack()
                    rack = teststate.player_rack().contents()
                    if rack in rackscores:
                        # We have seen this rack before: fetch its score
                        sc = rackscores[rack]
                    else:
                        # New rack: see how well it would score
                        apl = AutoPlayer_MiniMax(teststate)
                        # Go one level deeper into move generation
                        # pylint: disable=protected-access
                        move = apl._generate_move(depth=depth - 1)
                        # Calculate the score of this random rack based move
                        # but do not apply it to the teststate
                        sc = teststate.score(move)
                        if sc > 100:
                            print(
                                "Countermove rack '{0}' generated move {1} scoring {2}".format(
                                    rack, move, sc
                                )
                            )
                        # Cache the score
                        rackscores[rack] = sc
                    sum_score += sc
                    countermoves.append(sc)
                # Calculate the average score of the countermoves to this candidate
                # TBD: Maybe a median score is better than average?
                avg_score = float(sum_score) / NUM_TEST_RACKS

            print(
                "Average score of {0} countermove racks is {1:.2f}".format(
                    NUM_TEST_RACKS, avg_score
                )
            )
            print(countermoves)

            # Keep track of the lowest countermove score across all candidates as a baseline
            min_score = (
                avg_score
                if (min_score is None) or (avg_score < min_score)
                else min_score
            )
            # Keep track of the weighted candidate moves
            weighted_candidates.append((m, score, avg_score))

        print(f"Lowest score of countermove to all evaluated candidates is {min_score}")
        # Sort the candidates by the plain score after subtracting the effect of
        # potential countermoves, measured as the countermove score in excess of
        # the lowest countermove score found
        min_score_float = cast(float, min_score)
        weighted_candidates.sort(
            key=lambda x: float(x[1]) - (x[2] - min_score_float), reverse=True
        )

        print(
            "AutoPlayer_MinMax: Rack '{0}' generated {1} candidate moves:".format(
                self._rack, len(scored_candidates)
            )
        )
        # Show top 20 candidates
        for m, sc, wsc in weighted_candidates:
            print(
                "Move {0} score {1} weighted {2:.2f}".format(
                    m, sc, float(sc) - (wsc - min_score_float)
                )
            )
        # Return the highest-scoring candidate
        return weighted_candidates[0][0]
