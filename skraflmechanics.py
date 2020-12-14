"""

    Skraflmechanics - the inner workings of a SCRABBLE(tm) game server

    Copyright (C) 2020 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The GNU General Public License, version 3, applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module contains classes that implement various
    mechanics for a SCRABBLE(tm)-like game, including the
    board itself, the players, their racks, moves,
    scoring, etc.

    Algorithms for automatic (computer) play are found
    in skraflplayer.py

    Note: SCRABBLE is a registered trademark. This software or its author
    are in no way affiliated with or endorsed by the owners or licensees
    of the SCRABBLE trademark.

"""

# pylint: disable=too-many-lines

from __future__ import annotations

from typing import List, Tuple, Iterator, Union, Optional, Type

import abc
from random import SystemRandom
from functools import cached_property

from dawgdictionary import Wordbase
from languages import TileSet, Alphabet, current_alphabet, alphabet_for_locale


# Type definitions
SummaryTuple = Tuple[str, str, int]
MoveSummaryTuple = Tuple[int, SummaryTuple]
DetailTuple = Tuple[str, str, str, int]

# !!! DEBUG ONLY: Set to True to use an extra small bag for testing
# _DEBUG_MANUAL_WORDCHECK = True
_DEBUG_MANUAL_WORDCHECK = False

# Board squares with word/letter scores
# ' '=normal/single, '2'=double, '3'=triple score
_WSC = {
    "standard": [
        "3      3      3",
        " 2           2 ",
        "  2         2  ",
        "   2       2   ",
        "    2     2    ",
        "               ",
        "               ",
        "3      2      3",
        "               ",
        "               ",
        "    2     2    ",
        "   2       2   ",
        "  2         2  ",
        " 2           2 ",
        "3      3      3",
    ],
    "explo": [
        "3      3      3",
        "               ",
        "  2         2  ",
        "   2      2    ",
        "    2          ",
        "               ",
        "      2      2 ",
        "3      2      3",
        "        2      ",
        "            2  ",
        "   2      2    ",
        "           2   ",
        "  2      2     ",
        "      2      2 ",
        "3      3      3",
    ]
}

_LSC = {
    "standard": [
        "   2       2   ",
        "     3   3     ",
        "      2 2      ",
        "2      2      2",
        "               ",
        " 3   3   3   3 ",
        "  2   2 2   2  ",
        "   2       2   ",
        "  2   2 2   2  ",
        " 3   3   3   3 ",
        "               ",
        "2      2      2",
        "      2 2      ",
        "     3   3     ",
        "   2       2   ",
    ],
    "explo": [
        "    2      2   ",
        " 2   3  2    3 ",
        "      2  2     ",
        "   2   3       ",
        "2          3  2",
        " 3   2   3  2  ",
        "  2       2    ",
        "   3       2   ",
        " 2             ",
        "  2  3   2     ",
        "      2      3 ",
        "2   3  2      2",
        "     2      2  ",
        " 3        3    ",
        "    2      2   ",
    ],
}

# For each board type, convert the word and letter score strings to integer arrays
_xlt = lambda arr: [[1 if c == " " else int(c) for c in row] for row in arr]
_WORDSCORE = { key: _xlt(val) for key, val in _WSC.items() }
_LETTERSCORE = { key: _xlt(val) for key, val in _LSC.items() }


class Board:

    """Represents the characteristics and the contents of a Scrabble board."""

    # A standard Scrabble board is 15 x 15 squares
    SIZE = 15

    # The rows are identified by letter
    ROWIDS = "ABCDEFGHIJKLMNO"

    @staticmethod
    def short_coordinate(horiz, row, col):
        """RC if horizontal move, or CR if vertical.
        R is A,B,C... C is 1,2,3..."""
        return (
            Board.ROWIDS[row] + str(col + 1)
            if horiz
            else str(col + 1) + Board.ROWIDS[row]
        )

    def __init__(self, copy=None, board_type=None):

        # pylint: disable=protected-access
        # noinspection PyProtectedMember
        if copy is None:
            # Store letters on the board in list of strings
            self._letters = [" " * Board.SIZE for _ in range(Board.SIZE)]
            # Store tiles on the board in list of strings
            self._tiles = [" " * Board.SIZE for _ in range(Board.SIZE)]
            # The two counts below should always stay in sync
            self._numletters = 0
            self._numtiles = 0
            self._board_type = board_type or "standard"
        else:
            # Copy constructor: initialize from another Board
            self._letters = copy._letters[:]
            self._tiles = copy._tiles[:]
            self._numletters = copy._numletters
            self._numtiles = copy._numtiles
            self._board_type = copy._board_type or "standard"
        self._wordscore = _WORDSCORE[self._board_type]
        self._letterscore = _LETTERSCORE[self._board_type]

    @cached_property
    def start_square(self) -> Tuple[int, int]:
        """ Return the starting square of this board as a (row, col) tuple """
        if self._board_type == "explo":
            # For 'explo', the starting square is C3
            return (2, 2)
        # For the standard board, the starting square is H8
        return (Board.SIZE // 2, Board.SIZE // 2)

    @property
    def board_type(self) -> str:
        """ Return the board type, i.e. 'standard' or 'explo' """
        return self._board_type

    def is_empty(self):
        """ Is the board empty, i.e. contains no tiles? """
        # One of those checks should actually be enough
        return self._numletters == 0 and self._numtiles == 0

    def is_covered(self, row, col):
        """ Is the specified square already covered (taken)? """
        return self._letters[row][col] != " "

    def has_adjacent(self, row, col):
        """ Check whether there are any tiles on the board adjacent to this square """
        if row > 0 and self.is_covered(row - 1, col):
            return True
        if row < Board.SIZE - 1 and self.is_covered(row + 1, col):
            return True
        if col > 0 and self.is_covered(row, col - 1):
            return True
        if col < Board.SIZE - 1 and self.is_covered(row, col + 1):
            return True
        return False

    def letter_at(self, row, col):
        """ Return the letter at the specified co-ordinate """
        return self._letters[row][col]

    def tile_at(self, row, col):
        """ Return the tile at the specified co-ordinate (may be '?' for blank tile) """
        return self._tiles[row][col]

    def set_letter(self, row, col, letter):
        """ Set the letter at the specified co-ordinate """
        # assert letter is not None
        # assert len(letter) == 1
        prev = self._letters[row][col]
        if prev == letter:
            # Unchanged square: we're done
            return
        if prev == " " and letter != " ":
            # Putting a letter into a previously empty square
            self._numletters += 1
        elif prev != " " and letter == " ":
            # Removing a letter from a previously filled square
            self._numletters -= 1
        r = self._letters[row]
        self._letters[row] = r[0:col] + letter + r[col + 1 :]

    def set_tile(self, row, col, tile):
        """ Set the tile at the specified co-ordinate """
        # assert tile is not None
        # assert len(tile) == 1
        prev = self._tiles[row][col]
        if prev == tile:
            # Unchanged square: we're done
            return
        if prev == " " and tile != " ":
            # Putting a tile into a previously empty square
            self._numtiles += 1
        elif prev != " " and tile == " ":
            # Removing a tile from a previously filled square
            self._numtiles -= 1
        r = self._tiles[row]
        self._tiles[row] = r[0:col] + tile + r[col + 1 :]

    def enum_tiles(self):
        """ Enumerate the tiles on the board with their coordinates """
        for x in range(Board.SIZE):
            for y in range(Board.SIZE):
                t = self.tile_at(x, y)
                if t != " ":
                    yield (x, y, t, self.letter_at(x, y))

    @staticmethod
    def adjacent(row, col, xd, yd, getter):
        """ Return the letters or tiles adjacent to the given square, in the direction (xd, yd) """
        result = ""
        row += xd
        col += yd
        while row in range(Board.SIZE) and col in range(Board.SIZE):
            ltr = getter(row, col)
            if ltr == " ":
                # Empty square: we're done
                break
            if xd + yd < 0:
                # Going up or to the left: add to the beginning
                result = ltr + result
            else:
                # Going down or to the right: add to the end
                result += ltr
            row += xd
            col += yd
        return result

    def letters_above(self, row, col):
        """ Return the letters immediately above the given square, if any """
        return self.adjacent(row, col, -1, 0, self.letter_at)

    def letters_below(self, row, col):
        """ Return the letters immediately below the given square, if any """
        return self.adjacent(row, col, 1, 0, self.letter_at)

    def letters_left(self, row, col):
        """ Return the letters immediately to the left of the given square, if any """
        return self.adjacent(row, col, 0, -1, self.letter_at)

    def letters_right(self, row, col):
        """ Return the letters immediately to the right of the given square, if any """
        return self.adjacent(row, col, 0, 1, self.letter_at)

    def tiles_above(self, row, col):
        """ Return the tiles immediately above the given square, if any """
        return self.adjacent(row, col, -1, 0, self.tile_at)

    def tiles_below(self, row, col):
        """ Return the tiles immediately below the given square, if any """
        return self.adjacent(row, col, 1, 0, self.tile_at)

    def tiles_left(self, row, col):
        """ Return the tiles immediately to the left of the given square, if any """
        return self.adjacent(row, col, 0, -1, self.tile_at)

    def tiles_right(self, row, col):
        """ Return the tiles immediately to the right of the given square, if any """
        return self.adjacent(row, col, 0, 1, self.tile_at)

    def __str__(self):
        """ Simple text dump of the contents of the board """
        board = ["   1 2 3 4 5 6 7 8 9 0 1 2 3 4 5"]
        for y, row in enumerate(self._letters):
            board.append(
                Board.ROWIDS[y] + ": " + " ".join(["." if c == " " else c for c in row])
            )
        return "\n".join(board)

    def wordscore(self, row, col):
        """ Returns the word score factor of the indicated square, 1, 2 or 3 """
        return self._wordscore[row][col]

    def letterscore(self, row, col):
        """ Returns the letter score factor of the indicated square, 1, 2 or 3 """
        return self._letterscore[row][col]


class Bag:

    """ Represents a bag of tiles """

    # The random number generator to use to draw tiles
    RNG = SystemRandom()

    def __init__(
        self,
        tileset: Optional[Type[TileSet]],
        copy: Optional[Bag] = None,
        debug: bool = False,
    ) -> None:
        # pylint: disable=protected-access
        # noinspection PyProtectedMember
        self._tileset = tileset
        if copy is None:
            # Get a full bag from the requested tile set
            assert tileset is not None
            if debug:
                # Small bag for debugging endgame cases
                self._tiles = "aaábdðefgiiíklmnnóprrsstuuúæ"
            else:
                self._tiles = tileset.full_bag()
            self._size = len(self._tiles)
        else:
            # Copy constructor: initialize from another Bag
            self._tiles = copy._tiles
            self._size = copy._size
            self._tileset = copy._tileset

    def draw_tile(self):
        """ Draw a single tile from the bag """
        if self.is_empty():
            return None
        tile = self._tiles[Bag.RNG.randint(0, len(self._tiles) - 1)]
        self._tiles = self._tiles.replace(tile, "", 1)
        return tile

    def return_tiles(self, tiles):
        """ Return one or more tiles to the bag """
        self._tiles += tiles

    def contents(self):
        """ Return the contents of the bag """
        return self._tiles

    def set_contents(self, tiles):
        """ Set the contents of the bag """
        self._tiles = tiles

    def num_tiles(self):
        """ Return the number of tiles in the bag """
        return len(self._tiles)

    def is_empty(self):
        """ Returns True if the bag is empty, i.e. all tiles have been drawn """
        return not self._tiles

    def is_full(self):
        """ Returns True if the bag is full, i.e. no tiles have been drawn """
        return self.num_tiles() == self._size

    def allows_exchange(self):
        """ Does the bag contain enough tiles to allow exchange? """
        return self.num_tiles() >= Rack.MAX_TILES

    @property
    def alphabet(self) -> Alphabet:
        """ Return the alphabet that is associated with this bag """
        assert self._tileset is not None
        return self._tileset.alphabet

    def subtract_board(self, board):
        """ Subtract all tiles on the board from the bag """
        board_tiles = "".join(tile for row, col, tile, letter in board.enum_tiles())
        self._tiles = self.alphabet.string_subtract(self._tiles, board_tiles)

    def subtract_rack(self, rack):
        """ Subtract all tiles in the rack from the bag """
        self._tiles = self.alphabet.string_subtract(self._tiles, rack)


class Rack:

    """ Represents a player's rack of tiles """

    MAX_TILES = 7

    def __init__(self, copy: Optional[Rack] = None) -> None:

        # pylint: disable=protected-access
        if copy is None:
            self._tiles = ""
        else:
            # Copy constructor: initialize from another Rack
            self._tiles = copy._tiles

    def remove_tile(self, tile: str) -> None:
        """ Remove a tile from the rack """
        self._tiles = self._tiles.replace(tile, "", 1)

    def replenish(self, bag: Bag) -> None:
        """ Draw tiles from the bag until we have 7 tiles or the bag is empty """
        while len(self._tiles) < Rack.MAX_TILES and not bag.is_empty():
            self._tiles += bag.draw_tile()

    def contents(self) -> str:
        """ Return the contents of the rack """
        return self._tiles

    def details(self, tileset: Type[TileSet]) -> List[Tuple[str, int]]:
        """ Return the detailed contents of the rack, i.e. tiles and their scores """
        return [(t, tileset.scores[t]) for t in self._tiles]

    def num_tiles(self) -> int:
        """ Return the number of tiles in the rack """
        return len(self._tiles)

    def is_empty(self) -> bool:
        """ Is the rack empty? """
        return self.num_tiles() == 0

    def set_tiles(self, tiles: Optional[str]) -> None:
        """ Set the contents of the rack """
        self._tiles = tiles or ""

    def contains(self, tiles: str) -> bool:
        """ Check whether the rack contains all tiles in the tiles string """
        # (Quick and dirty, not time-critical)
        temp = self._tiles
        for c in tiles:
            temp = temp.replace(c, "", 1)
        return len(self._tiles) - len(temp) == len(tiles)

    def exchange(self, bag: Bag, tiles: str) -> bool:
        """ Exchange the given tiles with the bag """
        if not bag.allows_exchange():
            # Need seven tiles in the bag to be allowed to exchange
            return False
        # First remove the tiles from the rack and replenish it
        removed = ""
        for c in tiles:
            if c in self._tiles:
                # Be careful and only remove tiles that actually were there
                self.remove_tile(c)
                removed += c
        self.replenish(bag)
        # Then return the old tiles to the bag
        bag.return_tiles(removed)
        return True

    def randomize_and_sort(self, bag: Bag) -> None:
        """ Return all rack tiles back to the bag and draw a fresh set """
        if bag.is_empty():
            # Can't randomize - would just draw same tiles back
            return
        n = self.num_tiles()
        bag.return_tiles(self._tiles)
        tiles: List[str] = []
        while len(tiles) < n and not bag.is_empty():
            tiles.append(bag.draw_tile())
        # Return the tiles sorted in alphabetical order
        tiles.sort(key=bag.alphabet.all_tiles.index)
        self._tiles = "".join(tiles)


class State:

    """ Represents the state of a game at a particular point.
        Contains the current board, the racks, scores, etc. """

    def __init__(
        self,
        tileset: Optional[Type[TileSet]] = None,
        manual_wordcheck: bool = False,
        drawtiles: bool = True,
        copy: Optional[State] = None,
        locale: Optional[str] = None,
        board_type: Optional[str] = None,
    ):

        # pylint: disable=protected-access
        if copy is None:
            self._board = Board(board_type=board_type)
            self._player_to_move = 0
            self._scores: List[int] = [0, 0]  # "Pure" scores from moves on the board
            # Adjustments (deltas) made at the end of the game
            self._adj_scores = [0, 0]
            self._player_names = ["", ""]
            self._num_passes = 0  # Number of consecutive Pass moves
            self._num_moves = 0  # Number of moves made
            self._game_resigned = False
            self._racks = [Rack(), Rack()]
            self._manual_wordcheck = manual_wordcheck
            self._board_type = board_type or "standard"
            self._locale = locale or "is_IS"
            # The score a challenge would get if made (0 if not challengeable)
            self._challenge_score = 0
            # The rack before the last challengeable move
            self._last_rack: Optional[str] = None
            # The covers laid down in the last challengeable move
            self._last_covers = None
            # Initialize a fresh, full bag of tiles
            self._tileset = tileset
            if manual_wordcheck and _DEBUG_MANUAL_WORDCHECK:
                self._bag = Bag(tileset, debug=True)
            else:
                self._bag = Bag(tileset)
            if drawtiles:
                # Draw the racks from the bag
                for rack in self._racks:
                    rack.replenish(self._bag)
        else:
            # Copy constructor: initialize a State from another State
            self._board = Board(copy._board)
            self._player_to_move = copy._player_to_move
            self._scores = copy._scores[:]
            self._adj_scores = copy._adj_scores[:]
            self._player_names = copy._player_names[:]
            self._num_passes = copy._num_passes
            self._num_moves = copy._num_moves
            self._game_resigned = copy._game_resigned
            self._racks = [Rack(copy._racks[0]), Rack(copy._racks[1])]
            self._manual_wordcheck = copy._manual_wordcheck
            self._challenge_score = copy._challenge_score
            self._last_rack = copy._last_rack
            self._last_covers = copy._last_covers
            self._tileset = copy._tileset
            self._locale = copy._locale
            self._board_type = copy._board_type
            self._bag = Bag(tileset=None, copy=copy._bag)

    def load_board(self, board):
        """ Load a Board into this state """
        self._board = board

    def check_legality(self, move: MoveBase) -> Union[int, Tuple[int, str]]:
        """ Is the move legal in this state? """
        if move is None:
            return Error.NULL_MOVE
        return move.check_legality(self)

    def apply_move(self, move: MoveBase, shallow: bool = False) -> bool:
        """ Apply the given move, assumed to be legal, to this state """
        # A shallow apply is one that does not modify the racks or the bag.
        # It is used when loading game state from persistent storage.
        if not shallow and self.is_game_over():
            # Game is over, moves are not accepted any more
            return False
        # Update the player's score
        self._scores[self._player_to_move] += self.score(move)
        # Apply the move to the board state
        move.apply(self, shallow)
        # Increment the move count
        self._num_moves += 1
        if not (self._game_resigned or self._num_passes >= 6):
            # Game is still ongoing:
            # Draw new tiles if required
            if (not shallow) and move.replenish():
                self.player_rack().replenish(self._bag)
        # It's the other player's move (i.e. if the game is not over by now)
        self._player_to_move = 1 - self._player_to_move
        return True

    @property
    def tileset(self) -> Optional[Type[TileSet]]:
        """ Return the tileset for this game state """
        return self._tileset

    @property
    def manual_wordcheck(self) -> bool:
        """ Using manual wordcheck instead of automatic? """
        return self._manual_wordcheck

    @property
    def board_type(self) -> str:
        """ The type of the board being used """
        return self._board_type

    @property
    def locale(self) -> str:
        """ The locale being used """
        return self._locale

    def score(self, move: MoveBase) -> int:
        """ Calculate the score of the move """
        return move.score(self)

    def scores(self) -> Tuple[int, int]:
        """ Return the current score for both players """
        return self._scores[0], self._scores[1]

    def final_scores(self) -> Tuple[int, int]:
        """ Return the final scores including adjustments, if any """
        f0 = max(self._scores[0] + self._adj_scores[0], 0)
        f1 = max(self._scores[1] + self._adj_scores[1], 0)
        return (f0, f1)

    def num_moves(self) -> int:
        """ Return the number of moves made so far """
        return self._num_moves

    def set_player_name(self, index: int, name: str) -> None:
        """ Set the name of the player whose index is given, 0 or 1 """
        self._player_names[index] = name

    def player_name(self, index: int) -> str:
        """ Return the name of the player with the given index, 0 or 1 """
        return self._player_names[index]

    def player_to_move(self) -> int:
        """ Return the index of the player whose move it is, 0 or 1. """
        return self._player_to_move

    def player_rack(self) -> Rack:
        """ Return the Rack object for the player whose turn it is """
        return self._racks[self._player_to_move]

    def randomize_and_sort_rack(self) -> None:
        """ Randomize the tiles on the current player's rack """
        self.player_rack().randomize_and_sort(self._bag)

    def resign_game(self) -> None:
        """ Cause the game to end by resigning from it """
        self._game_resigned = True
        self.clear_challengeable()

    def is_resigned(self) -> bool:
        """ Returns True if the game has been ended by resignation """
        return self._game_resigned

    @property
    def last_rack(self) -> Optional[str]:
        """ Return the rack as it was before the last/challengeable move """
        return self._last_rack

    @property
    def last_covers(self):
        """ Return the covers of the last/challengeable move """
        return self._last_covers

    @property
    def challenge_score(self):
        """ The score of a challenge move, if made """
        return self._challenge_score

    def is_challengeable(self) -> bool:
        """ Is the last move made in the game challengeable? """
        return self._challenge_score != 0

    def clear_challengeable(self) -> None:
        """ Last move is not challengeable """
        self._last_rack = None
        self._last_covers = None
        self._challenge_score = 0

    def set_challengeable(self, score, covers, last_rack):
        """ Set the challengeable state, with the given covers being laid down """
        if score and self.manual_wordcheck:
            self._challenge_score = score
            # logging.info("State.set_challengeable: last_rack is {0}"
            # .format(last_rack))
            self._last_rack = last_rack
            self._last_covers = covers

    def rack(self, index: int) -> str:
        """ Return the contents of the rack (indexed by 0 or 1) """
        return self._racks[index].contents()

    def rack_details(self, index: int):
        """ Return the contents of the rack (indexed by 0 or 1) """
        assert self._tileset is not None
        return self._racks[index].details(self._tileset)

    def set_rack(self, index: int, tiles: str) -> None:
        """ Set the contents of the rack (indexed by 0 or 1) """
        self._racks[index].set_tiles("" if tiles is None else tiles)

    def board(self) -> Board:
        """ Return the Board object of this state """
        return self._board

    def bag(self) -> Bag:
        """ Return the current Bag """
        return self._bag

    def recalc_bag(self) -> None:
        """Recalculate the bag by subtracting from it the tiles on the board
        and in the racks"""
        # assert self._bag.is_full()
        self._bag.subtract_board(self._board)
        self._bag.subtract_rack(self.rack(0))
        self._bag.subtract_rack(self.rack(1))

    def display_bag(self, player: int) -> str:
        """ Returns the current bag plus the rack of the opponent """
        displaybag = self._bag.contents() + self.rack(1 - player)
        alphabet = alphabet_for_locale(self.locale)
        sort_order = alphabet.all_tiles
        return "".join(sorted(displaybag, key=sort_order.index))

    def is_game_over(self) -> bool:
        """The game is over if either rack is empty or if both players
        have made zero-score moves 3 times in a row"""
        if self._num_passes >= 6 or self._game_resigned:
            return True
        if self.is_challengeable():
            # If the last move is challengeable, the game is not over,
            # even if one of the racks is empty
            return False
        return any(r.is_empty() for r in self._racks)

    def is_last_challenge(self) -> bool:
        """ Is the game waiting for a potential challenge of the last move? """
        return self.is_challengeable() and any(r.is_empty() for r in self._racks)

    def finalize_score(self, lost_on_overtime=None, overtime_adjustment=None):
        """ When game is completed, calculate the final score adjustments """

        if self._game_resigned:
            # In case of a resignation, the resigning player
            # has already lost all points
            return

        sc = self._scores
        adj = self._adj_scores

        if lost_on_overtime is not None:
            # One of the players lost on overtime
            player = lost_on_overtime
            # Subtract 100 points from the player
            adj[player] = -min(100, sc[player])
            # If not enough to make the other player win, add to the other player
            if sc[player] + adj[player] >= sc[1 - player]:
                adj[1 - player] = sc[player] + adj[player] + 1 - sc[1 - player]
            # There is no consideration of rack leave in this case
            return

        assert self._tileset is not None

        if any(r.is_empty() for r in self._racks):
            # Normal win by one of the players
            for ix in range(2):
                # Add double the score of the opponent's tiles
                # (will be zero for the losing player)
                adj[ix] = 2 * self._tileset.score(self.rack(1 - ix))
        else:
            # Game expired by passes
            for ix in range(2):
                # Subtract the score of the player's own tiles
                adj[ix] = -self._tileset.score(self.rack(ix))

        # Apply overtime adjustment, if any
        if overtime_adjustment is not None:
            for ix in range(2):
                adj[ix] += overtime_adjustment[ix]

    def is_exchange_allowed(self) -> bool:
        """ Is an ExchangeMove allowed? """
        return self._bag.allows_exchange()

    def add_pass(self) -> None:
        """ Add a pass to the count of consecutive pass moves """
        self._num_passes += 1
        self.clear_challengeable()

    def reset_passes(self) -> None:
        """ Reset the count of consecutive passes """
        self._num_passes = 0

    def __str__(self) -> str:
        tomove0 = "-->" if self._player_to_move == 0 else ""
        tomove1 = "-->" if self._player_to_move == 1 else ""
        return (
            self._board.__str__()
            + "\n{4}{0} {1} vs {5}{2} {3}".format(
                self._player_names[0],
                self._scores[0],
                self._player_names[1],
                self._scores[1],
                tomove0,
                tomove1,
            )
            + "\n'{0}' vs '{1}'".format(self.rack(0), self.rack(1))
        )


class Cover:

    """ Represents a covering of a square by a tile """

    # pylint: disable=too-few-public-methods

    def __init__(self, row, col, tile, letter):
        self.row = row
        self.col = col
        self.tile = tile
        self.letter = letter


class Error:

    """ Error return codes from Move.check_legality() """

    # pylint: disable=too-few-public-methods

    def __init__(self):
        pass

    LEGAL = 0
    NULL_MOVE = 1
    FIRST_MOVE_NOT_IN_CENTER = 2
    DISJOINT = 3
    NOT_ADJACENT = 4
    SQUARE_ALREADY_OCCUPIED = 5
    HAS_GAP = 6
    WORD_NOT_IN_DICTIONARY = 7
    CROSS_WORD_NOT_IN_DICTIONARY = 8
    TOO_MANY_TILES_PLAYED = 9
    TILE_NOT_IN_RACK = 10
    EXCHANGE_NOT_ALLOWED = 11
    TOO_MANY_TILES_EXCHANGED = 12
    OUT_OF_SYNC = 13
    LOGIN_REQUIRED = 14
    WRONG_USER = 15
    GAME_NOT_FOUND = 16
    GAME_NOT_OVERDUE = 17
    SERVER_ERROR = 18
    NOT_MANUAL_WORDCHECK = 19
    MOVE_NOT_CHALLENGEABLE = 20
    ONLY_PASS_OR_CHALLENGE = 21
    USER_MUST_BE_FRIEND = 22
    # Insert new error codes above this line
    # GAME_OVER is always last and with a fixed code (also used in netskrafl.js)
    GAME_OVER = 99

    @staticmethod
    def errortext(errcode):
        """ Return a string identifier corresponding to an error code """
        if errcode == Error.GAME_OVER:
            # Special case
            return "GAME_OVER"
        return [
            "LEGAL",
            "NULL_MOVE",
            "FIRST_MOVE_NOT_IN_CENTER",
            "DISJOINT",
            "NOT_ADJACENT",
            "SQUARE_ALREADY_OCCUPIED",
            "HAS_GAP",
            "WORD_NOT_IN_DICTIONARY",
            "CROSS_WORD_NOT_IN_DICTIONARY",
            "TOO_MANY_TILES_PLAYED",
            "TILE_NOT_IN_RACK",
            "EXCHANGE_NOT_ALLOWED",
            "TOO_MANY_TILES_EXCHANGED",
            "OUT_OF_SYNC",
            "LOGIN_REQUIRED",
            "WRONG_USER",
            "GAME_NOT_FOUND",
            "GAME_NOT_OVERDUE",
            "SERVER_ERROR",
            "NOT_MANUAL_WORDCHECK",
            "MOVE_NOT_CHALLENGEABLE",
            "ONLY_PASS_OR_CHALLENGE",
            "USER_MUST_BE_FRIEND",
        ][errcode]


class MoveBase(abc.ABC):

    """ Abstract base class for the various types of moves """

    def __init__(self) -> None:
        pass

    # pylint: disable=unused-argument

    # noinspection PyUnusedLocal
    def details(self, state: State) -> List:
        """ Return a tuple list describing tiles committed
            to the board by this move """
        return []  # No tiles

    # noinspection PyUnusedLocal
    def check_legality(self, state: State) -> Union[int, Tuple[int, str]]:
        """ Check whether this move is legal on the board """
        # Always legal
        return Error.LEGAL

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def score(self, state: State) -> int:
        """ Calculate the score of this move, which is assumed to be legal """
        # A pass move does not affect the score
        return 0

    # noinspection PyMethodMayBeStatic
    def num_covers(self) -> int:
        """ Return the number of tiles played in this move """
        return 0

    @property
    def is_bingo(self) -> bool:
        """ Return True if bingo move (all tiles laid down) """
        return False

    def replenish(self) -> bool:
        """ Return True if the player's rack should be replenished after the move """
        return False

    @abc.abstractmethod
    def apply(self, state: State, shallow: bool = False) -> None:
        """ Should be overridden in derived classes """
        raise NotImplementedError

    @abc.abstractmethod
    def summary(self, state: State) -> SummaryTuple:
        """ Return a summary of the move, as a tuple: (coordinate, tiles, score) """
        raise NotImplementedError

    @property
    def needs_response_move(self) -> bool:
        """ Does this move call for a ResponseMove to be generated? """
        # Only True for ChallengeMove instances
        return False


class Move(MoveBase):

    """ Represents a move by a player """

    # Bonus score for playing all 7 tiles in one move
    BINGO_BONUS = 50
    # If an opponent challenges a valid move, the player gets a bonus
    INCORRECT_CHALLENGE_BONUS = 10

    def __init__(self, word: str, row: int, col: int, horiz: bool=True) -> None:
        super(Move, self).__init__()
        # A list of squares covered by the play, i.e. actual tiles
        # laid down on the board
        self._covers: List[Cover] = []
        # Number of letters in word formed (this may be >= len(self._covers))
        self._numletters = 0 if word is None else len(word)
        # The word formed
        self._word = word
        # The tiles used to form the word. '?' tiles are followed
        # by the letter they represent.
        self._tiles: Optional[str] = None
        # Starting row and column of word formed
        self._row = row
        self._col = col
        # Is the word horizontal or vertical?
        self._horizontal = horiz
        # Cached score of this move
        self._score: Optional[int] = None
        # Cached vocabulary DAWG
        self._dawg = Wordbase.dawg()

    def set_tiles(self, tiles: str) -> None:
        """ Set the tiles string once it is known """
        self._tiles = tiles

    def replenish(self) -> bool:
        """ Return True if the player's rack should be replenished after the move """
        return True

    def num_covers(self) -> int:
        """ Number of empty squares covered by this move """
        return len(self._covers)

    @property
    def is_bingo(self) -> bool:
        """ Return True if bingo move (all tiles laid down) """
        return self.num_covers() == Rack.MAX_TILES

    @property
    def row(self) -> int:
        """ Return the starting row of this move """
        return self._row

    def covers(self) -> List[Cover]:
        """ Return the list of covered squares """
        return self._covers

    def word(self) -> str:
        """ Return the word formed by this move """
        return self._word

    def details(self, state: State) -> List[DetailTuple]:
        """ Return a list of tuples describing this move """
        assert isinstance(state, State)
        assert state.tileset is not None
        scores = state.tileset.scores
        return [
            (
                Board.ROWIDS[c.row] + str(c.col + 1),  # Coordinate
                c.tile,
                c.letter,  # Tile and letter
                scores[c.tile],  # Score
            )
            for c in self._covers
        ]

    def summary(self, state: State) -> SummaryTuple:
        """ Return a summary of the move, as a tuple: (coordinate, tiles, score) """
        assert isinstance(state, State)
        return (self.short_coordinate(), self._tiles or "", self.score(state))

    def short_coordinate(self) -> str:
        """ Return the coordinate of the move,
            i.e. row letter + column number for horizontal moves or
            column number + row letter for vertical ones """
        return Board.short_coordinate(self._horizontal, self._row, self._col)

    def __str__(self) -> str:
        """ Return the standard move notation of a coordinate
            followed by the word formed """
        return self.short_coordinate() + ":'" + self._word + "'"

    def add_cover(self, row: int, col: int, tile: str, letter: str) -> bool:
        """ Add a placement of a tile on a board square to this move """
        # Sanity check the input
        if row < 0 or row >= Board.SIZE:
            return False
        if col < 0 or col >= Board.SIZE:
            return False
        if (tile is None) or len(tile) != 1:
            return False
        if (letter is None) or len(letter) != 1 or (letter not in current_alphabet().order):
            return False
        if tile != "?" and tile != letter:
            return False
        if len(self._covers) >= Rack.MAX_TILES:
            # Already have 7 tiles being played
            return False
        self._covers.append(Cover(row, col, tile, letter))
        return True

    def add_validated_cover(self, cover: Cover) -> None:
        """ Add an already validated Cover object to this move """
        self._covers.append(cover)
        # Find out automatically whether this is a horizontal or vertical move
        if len(self._covers) == 2:
            self._horizontal = self._covers[0].row == cover.row

    def make_covers(self, board: Board, tiles: str) -> None:
        """ Create a cover list out of a tile string """

        self.set_tiles(tiles)

        def enum_covers(tiles: str) -> Iterator[Tuple[str, str]]:
            """ Generator to enumerate through a tiles string,
                yielding (tile, letter) tuples """
            ix = 0
            while ix < len(tiles):
                if tiles[ix] == "?":
                    # Wildcard tile: must be followed by its meaning
                    ix += 1
                    yield ("?", tiles[ix])
                else:
                    # Normal letter tile
                    yield (tiles[ix], tiles[ix])
                ix += 1

        row, col = self._row, self._col
        xd, yd = (0, 1) if self._horizontal else (1, 0)
        for tile, letter in enum_covers(tiles):
            if not board.is_covered(row, col):
                # This is a fresh tile being laid down on the board
                self._covers.append(Cover(row, col, tile, letter))
            row += xd
            col += yd
        # Sanity checks: we've enumerated correctly through the laid-down word
        # assert row - self._row == self._numletters * xd
        # assert col - self._col == self._numletters * yd

    def check_legality(self, state: State) -> Union[int, Tuple[int, str]]:
        """ Check whether this move is legal on the board """

        # Must cover at least one square
        if len(self._covers) < 1:
            return Error.NULL_MOVE
        if len(self._covers) > Rack.MAX_TILES:
            return Error.TOO_MANY_TILES_PLAYED
        if state.is_game_over():
            return Error.GAME_OVER
        if state.is_last_challenge():
            # Last tile move on the board: the player can only pass or challenge
            return Error.ONLY_PASS_OR_CHALLENGE

        rack = state.player_rack()
        board = state.board()
        row = 0
        col = 0
        horiz = True
        vert = True
        first = True
        # All tiles played must be in the rack
        played = "".join([c.tile for c in self._covers])
        if not rack.contains(played):
            return Error.TILE_NOT_IN_RACK
        # The tiles covered by the move must be purely horizontal or purely vertical
        for c in self._covers:
            if first:
                row = c.row
                col = c.col
                first = False
            else:
                if c.row != row:
                    horiz = False
                if c.col != col:
                    vert = False
        if (not horiz) and (not vert):
            # Spread all over: not legal
            return Error.DISJOINT
        # If only one cover, use the orientation of the longest word formed
        if len(self._covers) == 1:
            # In the case of a tied length, we use horizontal
            self._horizontal = (
                len(board.letters_left(row, col)) + len(board.letters_right(row, col))
            ) >= (
                len(board.letters_above(row, col)) + len(board.letters_below(row, col))
            )
            horiz = self._horizontal
        # The move is purely horizontal or vertical
        if horiz:
            self._covers.sort(key=lambda x: x.col)  # Sort in ascending column order
            self._horizontal = True
        else:
            self._covers.sort(key=lambda x: x.row)  # Sort in ascending row order
            self._horizontal = False
        # Check whether eventual missing squares in the move sequence
        # are already covered
        row = 0
        col = 0
        first = True
        for c in self._covers:
            if board.is_covered(c.row, c.col):
                # We already have a tile in the square: illegal play
                return Error.SQUARE_ALREADY_OCCUPIED
            # If there is a gap between this cover and the last one,
            # make sure all intermediate squares are covered
            if first:
                self._row = c.row
                self._col = c.col
                first = False
            else:
                if horiz:
                    # Horizontal: check squares within row
                    for ix in range(col + 1, c.col):
                        if not board.is_covered(c.row, ix):
                            # Found gap: illegal play
                            return Error.HAS_GAP
                else:
                    # Vertical: check squares within column
                    for ix in range(row + 1, c.row):
                        if not board.is_covered(ix, c.col):
                            # Found gap: illegal play
                            return Error.HAS_GAP
            row = c.row
            col = c.col
        # Find the start and end of the word that is being formed, including
        # tiles aready on the board
        if horiz:
            # Look for the beginning
            while self._col > 0 and board.is_covered(self._row, self._col - 1):
                self._col -= 1
            # Look for the end
            while col + 1 < Board.SIZE and board.is_covered(self._row, col + 1):
                col += 1
            # Now we know the length
            self._numletters = col - self._col + 1
        else:
            # Look for the beginning
            while self._row > 0 and board.is_covered(self._row - 1, self._col):
                self._row -= 1
            # Look for the end
            while row + 1 < Board.SIZE and board.is_covered(row + 1, self._col):
                row += 1
            # Now we know the length
            self._numletters = row - self._row + 1

        # Assemble the resulting word
        self._word = ""
        self._tiles = ""

        def add(cix):
            """ Add a cover's letter and tile to the word and tiles strings """
            ltr = self._covers[cix].letter
            tile = self._covers[cix].tile
            self._word += ltr
            self._tiles += tile + (ltr if tile == "?" else "")

        cix = 0

        for ix in range(self._numletters):

            if horiz:
                if cix < len(self._covers) and self._col + ix == self._covers[cix].col:
                    # This is one of the new letters
                    add(cix)
                    cix += 1
                else:
                    # This is a letter that was already on the board
                    ltr = board.letter_at(self._row, self._col + ix)
                    self._word += ltr
                    self._tiles += ltr
            else:
                if cix < len(self._covers) and self._row + ix == self._covers[cix].row:
                    # This is one of the new letters
                    add(cix)
                    cix += 1
                else:
                    # This is a letter that was already on the board
                    ltr = board.letter_at(self._row + ix, self._col)
                    self._word += ltr
                    self._tiles += ltr

        def is_valid_word(word):
            """ Check whether a word is in the dictionary,
                unless this is a manual game """
            return True if state.manual_wordcheck else word in self._dawg

        # Check whether the word is in the dictionary
        if not is_valid_word(self._word):
            return (Error.WORD_NOT_IN_DICTIONARY, self._word)

        # Check that the play is adjacent to some previously placed tile
        # (unless this is the first move, i.e. the board is empty)
        if board.is_empty():
            # First tile move: must go through the starting square
            ssq = board.start_square
            for c in self._covers:
                if (c.row, c.col) == ssq:
                    break
            else:
                return Error.FIRST_MOVE_NOT_IN_CENTER
        else:
            # Must be adjacent to something already on the board
            if not any([board.has_adjacent(c.row, c.col) for c in self._covers]):
                return Error.NOT_ADJACENT
            # Check all cross words formed by the new tiles
            for c in self._covers:
                if self._horizontal:
                    cross = (
                        board.letters_above(c.row, c.col)
                        + c.letter
                        + board.letters_below(c.row, c.col)
                    )
                else:
                    cross = (
                        board.letters_left(c.row, c.col)
                        + c.letter
                        + board.letters_right(c.row, c.col)
                    )
                if len(cross) > 1 and not is_valid_word(cross):
                    return (Error.CROSS_WORD_NOT_IN_DICTIONARY, cross)

        # All checks pass: the play is legal
        return Error.LEGAL

    def check_words(self, board: Board) -> List[str]:
        """ Do simple word validation on this move, returning
            a list of invalid words formed """

        invalid: List[str] = []

        # Check whether the main word is in the dictionary
        if self._word not in self._dawg:
            invalid.append(self._word)

        # Check all cross words formed by the new tiles
        for c in self._covers:
            if self._horizontal:
                cross = (
                    board.letters_above(c.row, c.col)
                    + c.letter
                    + board.letters_below(c.row, c.col)
                )
            else:
                cross = (
                    board.letters_left(c.row, c.col)
                    + c.letter
                    + board.letters_right(c.row, c.col)
                )
            if len(cross) > 1 and cross not in self._dawg:
                invalid.append(cross)

        return invalid  # Returns an empty list if all words are valid

    def score(self, state: State) -> int:
        """ Calculate the score of this move, which is assumed to be legal """

        assert isinstance(state, State)

        # Check for cached score
        if self._score is not None:
            return self._score
        # Sum of letter scores
        sc = 0
        # Word score multiplier
        wsc = 1
        # Cover index
        cix = 0
        # Number of tiles freshly covered
        numcovers = len(self._covers)
        # Coordinate and step
        row, col = self._row, self._col
        xd, yd = (0, 1) if self._horizontal else (1, 0)

        assert state.tileset is not None
        scores = state.tileset.scores
        board = state.board()

        # Tally the score of the primary word
        for _ in range(self._numletters):
            c = self._covers[cix] if cix < numcovers else None
            if c and (c.col == col) and (c.row == row):
                # This is one of the new tiles
                lscore = scores[c.tile]
                lscore *= board.letterscore(row, col)
                wsc *= board.wordscore(row, col)
                cix += 1
            else:
                # This is a tile that was already on the board
                tile = board.tile_at(row, col)
                lscore = scores[tile]
            sc += lscore
            row += xd
            col += yd

        total = sc * wsc

        # Tally the scores of words formed across the primary word
        for c in self._covers:
            if self._horizontal:
                cross = board.tiles_above(c.row, c.col) + board.tiles_below(
                    c.row, c.col
                )
            else:
                cross = board.tiles_left(c.row, c.col) + board.tiles_right(c.row, c.col)
            if cross:
                sc = scores[c.tile]
                sc *= board.letterscore(c.row, c.col)
                wsc = board.wordscore(c.row, c.col)
                sc += sum(scores[tile] for tile in cross)
                total += sc * wsc
        # Add the bingo bonus of 50 points for playing all (seven) tiles
        if numcovers == Rack.MAX_TILES:
            total += Move.BINGO_BONUS
        # Cache the calculated score
        self._score = total
        return total

    def apply(self, state: State, shallow: bool = False) -> None:
        """ Apply this move, assumed to be legal, to the board """
        board = state.board()
        rack = state.player_rack()
        last_rack = rack.contents()  # The rack as it stood before this move
        # logging.info("Move.apply: last_rack set to {0}".format(last_rack))
        for c in self._covers:
            board.set_letter(c.row, c.col, c.letter)
            board.set_tile(c.row, c.col, c.tile)
            if not shallow:
                rack.remove_tile(c.tile)
        state.reset_passes()
        if state.manual_wordcheck:
            # A normal tile-play move is challengeable
            invalid = self.check_words(board)
            if invalid:
                # The move contains one or more invalid words:
                # a challenge would give a negative score for the player
                chall_score = -int(self.score(state))
            else:
                # Nothing wrong with the move: a challenge would give
                # the player a bonus
                chall_score = self.INCORRECT_CHALLENGE_BONUS
            state.set_challengeable(chall_score, self._covers, last_rack)
        else:
            # Automatic wordcheck: not challengeable
            state.clear_challengeable()


class ExchangeMove(MoveBase):

    """ Represents an exchange move, where tiles are returned to the bag
        and new tiles drawn instead """

    def __init__(self, tiles: str) -> None:
        super(ExchangeMove, self).__init__()
        self._tiles = tiles

    def __str__(self) -> str:
        """ Return a readable description of the move """
        return "Exchanged {0}".format(len(self._tiles))

    def replenish(self) -> bool:
        """ Return True if the player's rack should be replenished after the move """
        return False

    def check_legality(self, state: State) -> Union[int, Tuple[int, str]]:
        """ Check whether this move is legal on the board """
        if state.bag().num_tiles() < Rack.MAX_TILES:
            return Error.EXCHANGE_NOT_ALLOWED
        if len(self._tiles) > Rack.MAX_TILES:
            return Error.TOO_MANY_TILES_EXCHANGED
        if state.is_last_challenge():
            # Last tile move on the board: the player can only pass or challenge
            return Error.ONLY_PASS_OR_CHALLENGE
        # All checks pass: the play is legal
        return Error.LEGAL

    # noinspection PyUnusedLocal
    # pylint: disable=unused-argument
    def summary(self, state: State) -> SummaryTuple:
        """ Return a summary of the move, as a tuple: (coordinate, word, score) """
        return ("", "EXCH " + self._tiles, 0)

    def apply(self, state: State, shallow: bool = False) -> None:
        """ Apply this move, assumed to be legal, to the current game state """
        if not shallow:
            state.player_rack().exchange(state.bag(), self._tiles)
        state.add_pass()  # An exchange counts towards the pass count
        # An exchange move is not challengeable
        state.clear_challengeable()


class ChallengeMove(MoveBase):

    """ Represents a challenge move, where the last move played by the
        opponent is challenged.

        If the challenge is correct, the opponent
        loses the points he got for the wrong word.

        Move sequence for a correct challenge:

        [wrong move, score=X]    CHALL score=0
        RESP score=-X            [next move by challenger]

        If the challenge is incorrect, the opponent gets a 10 point
        bonus but the challenger does not lose his turn.

        Move sequence for an incorrect challenge:

        [correct move, score=X]  CHALL score=0
        RESP score=10            [next move by challenger]

    """

    def __str__(self) -> str:
        """ Return a readable description of the move """
        return "Challenge"

    @property
    def needs_response_move(self) -> bool:
        """ Does this move call for a ResponseMove to be generated? """
        # Only True for ChallengeMove instances, not other moves
        return True

    def replenish(self) -> bool:
        """ Return True if the player's rack should be replenished after the move """
        return False

    def check_legality(self, state: State) -> Union[int, Tuple[int, str]]:
        """ Check whether a challenge is allowed """
        if not state.manual_wordcheck:
            # Challenges are only allowed in manual wordcheck games
            return Error.NOT_MANUAL_WORDCHECK
        # Check whether a word was laid down in the last move
        if not state.is_challengeable():
            return Error.MOVE_NOT_CHALLENGEABLE
        # All checks pass: the play is legal
        return Error.LEGAL

    # noinspection PyUnusedLocal
    # pylint: disable=unused-argument
    # noinspection PyMethodMayBeStatic
    def summary(self, state: State) -> SummaryTuple:
        """ Return a summary of the move, as a tuple: (coordinate, word, score) """
        return ("", "CHALL", 0)

    def apply(self, state: State, shallow: bool = False) -> None:
        """ Apply this move, assumed to be legal, to the current game state """
        # We do not change the challengeable state here
        pass


class ResponseMove(MoveBase):

    """ Represents a response to a challenge move """

    def __init__(self) -> None:
        super().__init__()
        self._score: Optional[int] = None
        self._num_covers = 0

    def __str__(self) -> str:
        """ Return a readable description of the move """
        return "Response"

    def replenish(self) -> bool:
        """ Return True if the player's rack should be replenished after the move """
        return False

    def check_legality(self, state: State) -> Union[int, Tuple[int, str]]:
        """ Check whether a challenge is allowed """
        if not state.manual_wordcheck:
            # Challenges are only allowed in manual wordcheck games
            return Error.NOT_MANUAL_WORDCHECK
        if not state.is_challengeable():
            # The challengeable state should still be set from the ChallengeMove
            return Error.MOVE_NOT_CHALLENGEABLE
        # All checks pass: the play is legal
        return Error.LEGAL

    # noinspection PyUnusedLocal
    # pylint: disable=unused-argument
    def summary(self, state: State) -> SummaryTuple:
        """ Return a summary of the move, as a tuple: (coordinate, word, score) """
        assert self._score is not None
        return ("", "RESP", self._score)

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def score(self, state: State) -> int:
        """ Calculate the score of this move, which is assumed to be legal """
        if self._score is None:
            self._score = state.challenge_score
            # logging.info("Setting score of ResponseMove to {0}".format(self._score))
            assert self._score != 0
        return self._score

    # noinspection PyMethodMayBeStatic
    def num_covers(self) -> int:
        """ Return the number of tiles played in this move """
        return self._num_covers

    def apply(self, state: State, shallow: bool = False) -> None:
        """ Apply this move, assumed to be legal, to the current game state """
        if self.score(state) < 0:
            # Successful challenge
            board = state.board()
            # Remove the last move from the board
            last_covers = state.last_covers
            self._num_covers = -len(last_covers)  # Negative cover count
            for c in last_covers:
                board.set_letter(c.row, c.col, " ")
                board.set_tile(c.row, c.col, " ")
            if not shallow:
                # Reset the opponent's rack to what it was before the move
                bag = state.bag()
                rack = state.player_rack()
                # Return all the current tiles to the bag
                bag.return_tiles(rack.contents())
                # Draw all the previous tiles from the bag
                # logging.info("ResponseMove.apply: setting rack to {0}"
                # .format(state.last_rack))
                rack.set_tiles(state.last_rack)
                bag.subtract_rack(rack.contents())
        state.clear_challengeable()


class PassMove(MoveBase):

    """ Represents a pass move, where the player does nothing """

    def __str__(self):
        """ Return a readable string describing the move """
        return "Pass"

    def replenish(self):
        """ Return True if the player's rack should be replenished after the move """
        return False

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    # pylint: disable=unused-argument
    def summary(self, board):
        """ Return a summary of the move, as a tuple: (coordinate, word, score) """
        return ("", "PASS", 0)

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def apply(self, state, shallow=False):
        """ Apply this move, assumed to be legal, to the current game state """
        # Increment the number of consecutive Pass moves
        state.add_pass()  # Clears the challengeable flag


class ResignMove(MoveBase):

    """ Represents a resign move, where the player forfeits the game """

    def __init__(self, forfeited_points):
        super(ResignMove, self).__init__()
        self._forfeited_points = forfeited_points

    def __str__(self):
        """ Return the standard move notation of a coordinate
            followed by the word formed """
        return "Resign"

    def replenish(self):
        """ Return True if the player's rack should be replenished after the move """
        return False

    # pylint: disable=unused-argument
    def summary(self, board):
        """ Return a summary of the move, as a tuple: (coordinate, word, score) """
        return ("", "RSGN", -self._forfeited_points)

    def score(self, state):
        """ Calculate the score of this move, which is assumed to be legal """
        # A resignation loses all points
        return -self._forfeited_points

    # noinspection PyMethodMayBeStatic
    def apply(self, state, shallow=False):
        """ Apply this move, assumed to be legal, to the current game state """
        # Resign the game, causing is_game_over() to become True
        state.resign_game()  # Clears the challengeable flag
