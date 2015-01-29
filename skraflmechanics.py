# -*- coding: utf-8 -*-

""" Skraflmechanics - the inner workings of a SCRABBLE(tm) game server

    Author: Vilhjalmur Thorsteinsson, 2014

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

from random import randint
from languages import Alphabet
from skraflpermuter import WordDatabase


class Manager:

    # A singleton instance of the WordDatabase class, used by
    # all Manager instances throughout a server session
    _word_db = None

    def __init__(self):
        if Manager._word_db is None:
            # The word database will be lazily loaded from file upon first use
            Manager._word_db = WordDatabase()

    @staticmethod
    def word_db():
        if Manager._word_db is None:
            # The word database will be lazily loaded from file upon first use
            Manager._word_db = WordDatabase()
        return Manager._word_db


class Board:

    """ Represents the characteristics and the contents of a Scrabble board.
    """

    # A standard Scrabble board is 15 x 15 squares
    SIZE = 15

    # The rows are identified by letter
    ROWIDS = u"ABCDEFGHIJKLMNO"

    # Board squares with word scores (1=normal/single, 2=double, 3=triple word score)
    _wordscore = [
        "311111131111113",
        "121111111111121",
        "112111111111211",
        "111211111112111",
        "111121111121111",
        "111111111111111",
        "111111111111111",
        "311111121111113",
        "111111111111111",
        "111111111111111",
        "111121111121111",
        "111211111112111",
        "112111111111211",
        "121111111111121",
        "311111131111113"]

    # Board squares with letter scores (1=normal/single, 2=double, 3=triple letter score)
    _letterscore = [
        "111211111112111",
        "111113111311111",
        "111111212111111",
        "211111121111112",
        "111111111111111",
        "131113111311131",
        "112111212111211",
        "111211111112111",
        "112111212111211",
        "131113111311131",
        "111111111111111",
        "211111121111112",
        "111111212111111",
        "111113111311111",
        "111211111112111"]

    @staticmethod
    def short_coordinate(horiz, row, col):
        # RC if horizontal move, or CR if vertical. R is A,B,C... C is 1,2,3...
        return Board.ROWIDS[row] + str(col + 1) if horiz else str(col + 1) + Board.ROWIDS[row]

    def __init__(self, copy = None):

        if copy is None:
            # Store letters on the board in list of strings
            self._letters = [u' ' * Board.SIZE for _ in range(Board.SIZE)]
            # Store tiles on the board in list of strings
            self._tiles = [u' ' * Board.SIZE for _ in range(Board.SIZE)]
            # The two counts below should always stay in sync
            self._numletters = 0
            self._numtiles = 0
        else:
            # Copy constructor: initialize from another Board
            self._letters = copy._letters[:]
            self._tiles = copy._tiles[:]
            self._numletters = copy._numletters
            self._numtiles = copy._numtiles

    def is_empty(self):
        """ Is the board empty, i.e. contains no tiles? """
        # One of those checks should actually be enough
        return self._numletters == 0 and self._numtiles == 0

    def is_covered(self, row, col):
        """ Is the specified square already covered (taken)? """
        return self.letter_at(row, col) != u' '

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
        assert letter is not None
        assert len(letter) == 1
        prev = self.letter_at(row, col)
        if prev == letter:
            # Unchanged square: we're done
            return
        if prev == u' ' and letter != u' ':
            # Putting a letter into a previously empty square
            self._numletters += 1
        self._letters[row] = self._letters[row][0:col] + letter + self._letters[row][col + 1:]

    def set_tile(self, row, col, tile):
        """ Set the tile at the specified co-ordinate """
        assert tile is not None
        assert len(tile) == 1
        prev = self.tile_at(row, col)
        if prev == tile:
            # Unchanged square: we're done
            return
        if prev == u' ' and tile != u' ':
            # Putting a tile into a previously empty square
            self._numtiles += 1
        self._tiles[row] = self._tiles[row][0:col] + tile + self._tiles[row][col + 1:]

    def enum_tiles(self):
        """ Enumerate the tiles on the board with their coordinates """
        for x in range(Board.SIZE):
            for y in range(Board.SIZE):
                t = self.tile_at(x, y)
                if t != u' ':
                    yield (x, y, t, self.letter_at(x,y))

    def adjacent(self, row, col, xd, yd, getter):
        """ Return the letters or tiles adjacent to the given square, in the direction (xd, yd) """
        result = u''
        row += xd
        col += yd
        while row in range(Board.SIZE) and col in range(Board.SIZE):
            ltr = getter(row, col)
            if ltr == u' ':
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
        l = [u"   1 2 3 4 5 6 7 8 9 0 1 2 3 4 5"]
        for y, row in enumerate(self._letters):
            l.append(Board.ROWIDS[y] + u': ' + \
                u' '.join([u'.' if c == u' ' else c for c in row]))
        return u'\n'.join(l)

    @staticmethod
    def wordscore(row, col):
        """ Returns the word score factor of the indicated square, 1, 2 or 3 """
        return int(Board._wordscore[row][col])

    @staticmethod
    def letterscore(row, col):
        """ Returns the letter score factor of the indicated square, 1, 2 or 3 """
        return int(Board._letterscore[row][col])

        
class Bag:

    """ Represents a bag of tiles """

    # The sort order for displaying the bag, with blank tiles last
    SORT_ORDER = Alphabet.order + u'?'

    def __init__(self, copy = None):

        if copy is None:
            # Get a full bag from the Alphabet; this varies between languages
            self._tiles = Alphabet.full_bag()
        else:
            # Copy constructor: initialize from another Bag
            self._tiles = copy._tiles

    def draw_tile(self):
        """ Draw a single tile from the bag """
        if self.is_empty():
            return None
        tile = self._tiles[randint(0, len(self._tiles) - 1)]
        self._tiles = self._tiles.replace(tile, u'', 1)
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
        return self.num_tiles() == len(Alphabet.full_bag())

    def allows_exchange(self):
        """ Does the bag contain enough tiles to allow exchange? """
        return self.num_tiles() >= Rack.MAX_TILES

    def subtract_board(self, board):
        """ Subtract all tiles on the board from the bag """
        board_tiles = u''.join(tile for row, col, tile, letter in board.enum_tiles())
        self._tiles = Alphabet.string_subtract(self._tiles, board_tiles)

    def subtract_rack(self, rack):
        """ Subtract all tiles in the rack from the bag """
        self._tiles = Alphabet.string_subtract(self._tiles, rack)


class Rack:

    """ Represents a player's rack of tiles """

    MAX_TILES = 7

    def __init__(self, copy = None):

        if copy is None:
            self._tiles = u''
        else:
            # Copy constructor: initialize from another Rack
            self._tiles = copy._tiles

    def remove_tile(self, tile):
        """ Remove a tile from the rack """
        self._tiles = self._tiles.replace(tile, u'', 1)

    def replenish(self, bag):
        """ Draw tiles from the bag until we have 7 tiles or the bag is empty """
        while len(self._tiles) < Rack.MAX_TILES and not bag.is_empty():
            self._tiles += bag.draw_tile()

    def contents(self):
        """ Return the contents of the rack """
        return self._tiles

    def details(self):
        """ Return the detailed contents of the rack, i.e. tiles and their scores """
        return [(t, Alphabet.scores[t]) for t in self._tiles]

    def num_tiles(self):
        """ Return the number of tiles in the rack """
        return len(self._tiles)

    def is_empty(self):
        """ Is the rack empty? """
        return self.num_tiles() == 0

    def set_tiles(self, tiles):
        """ Set the contents of the rack """
        self._tiles = u"" if tiles is None else tiles

    def contains(self, tiles):
        """ Check whether the rack contains all tiles in the tiles string """
        # (Quick and dirty, not time-critical)
        temp = self._tiles
        for c in tiles:
            temp = temp.replace(c, u'', 1)
        return len(self._tiles) - len(temp) == len(tiles)

    def exchange(self, bag, tiles):
        """ Exchange the given tiles with the bag """
        if not bag.allows_exchange():
            # Need seven tiles in the bag to be allowed to exchange
            return False
        # First remove the tiles from the rack and replenish it
        removed = u''
        for c in tiles:
            if c in self._tiles:
                # Be careful and only remove tiles that actually were there
                self.remove_tile(c)
                removed += c
        self.replenish(bag)
        # Then return the old tiles to the bag
        bag.return_tiles(removed)
        return True

    def randomize_and_sort(self, bag):
        """ Return all rack tiles back to the bag and draw a fresh set """
        if bag.is_empty():
            # Can't randomize - would just draw same tiles back
            return
        n = self.num_tiles()
        bag.return_tiles(self._tiles)
        tiles = []
        while len(tiles) < n and not bag.is_empty():
            tiles.append(bag.draw_tile())
        # Return the tiles sorted in alphabetical order
        def keyfunc(x):
            return (Alphabet.order + u"?").index(x)
        tiles.sort(key = keyfunc)
        self._tiles = u''.join(tiles)


class State:

    """ Represents the state of a game at a particular point.
        Contains the current board, the racks, scores, etc.
    """

    def __init__(self, drawtiles = True, copy = None):

        if copy is None:
            self._board = Board()
            self._player_to_move = 0
            self._scores = [0, 0] # "Pure" scores from moves on the board
            self._adj_scores = [0, 0] # Adjustments (deltas) made at the end of the game
            self._player_names = [u"", u""]
            self._num_passes = 0 # Number of consecutive Pass moves
            self._num_moves = 0 # Number of moves made
            self._game_resigned = False
            self._racks = [Rack(), Rack()]
            # Initialize a fresh, full bag of tiles
            self._bag = Bag()
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
            self._bag = Bag(copy._bag)

    def load_board(self, board):
        """ Load a Board into this state """
        self._board = board

    def check_legality(self, move):
        """ Is the move legal in this state? """
        if move is None:
            return Error.NULL_MOVE
        return move.check_legality(self)

    def apply_move(self, move, shallow = False):
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
            if not shallow:
                self.player_rack().replenish(self._bag)
            # It's the other player's move
            self._player_to_move = 1 - self._player_to_move
        return True

    def score(self, move):
        """ Calculate the score of the move """
        return move.score(self._board)

    def scores(self):
        """ Return the current score for both players """
        return tuple(self._scores)

    def final_scores(self):
        """ Return the final scores including adjustments, if any """
        f0 = max(self._scores[0] + self._adj_scores[0], 0)
        f1 = max(self._scores[1] + self._adj_scores[1], 0)
        return (f0, f1)

    def num_moves(self):
        """ Return the number of moves made so far """
        return self._num_moves

    def set_player_name(self, index, name):
        """ Set the name of the player whose index is given, 0 or 1 """
        self._player_names[index] = name

    def player_name(self, index):
        """ Return the name of the player with the given index, 0 or 1 """
        return self._player_names[index]

    def player_to_move(self):
        """ Return the index of the player whose move it is, 0 or 1. """
        return self._player_to_move

    def player_rack(self):
        """ Return the Rack object for the player whose turn it is """
        return self._racks[self._player_to_move]

    def randomize_and_sort_rack(self):
        """ Randomize the tiles on the current player's rack """
        self.player_rack().randomize_and_sort(self._bag)

    def resign_game(self):
        """ Cause the game to end by resigning from it """
        self._game_resigned = True

    def rack(self, index):
        """ Return the contents of the rack (indexed by 0 or 1) """
        return self._racks[index].contents()

    def rack_details(self, index):
        """ Return the contents of the rack (indexed by 0 or 1) """
        return self._racks[index].details()

    def set_rack(self, index, tiles):
        """ Set the contents of the rack (indexed by 0 or 1) """
        self._racks[index].set_tiles(u"" if tiles is None else tiles)

    def board(self):
        """ Return the Board object of this state """
        return self._board

    def bag(self):
        """ Return the current Bag """
        return self._bag

    def recalc_bag(self):
        """ Recalculate the bag by subtracting from it the tiles on the board and in the racks """
        assert self._bag.is_full()
        self._bag.subtract_board(self._board)
        self._bag.subtract_rack(self.rack(0))
        self._bag.subtract_rack(self.rack(1))

    def display_bag(self, player):
        """ Returns the current bag plus the rack of the opponent """
        displaybag = self._bag.contents() + self.rack(1 - player)
        return u''.join(sorted(displaybag, key=lambda ch: Bag.SORT_ORDER.index(ch)))

    def is_game_over(self):
        """ The game is over if either rack is empty or if both players have made zero-score moves 3 times in a row """
        return self._racks[0].is_empty() or self._racks[1].is_empty() or \
            (self._num_passes >= 6) or self._game_resigned

    def finalize_score(self, overtime_adjustment = None):
        """ When game is completed, calculate the final score adjustments """

        if self._game_resigned:
            # In case of a resignation, the resigning player has already lost all points
            return

        # Handle losing a game on overtime
        oa = overtime_adjustment
        sc = self._scores
        adj = self._adj_scores
        if oa and any(oa[ix] <= -100 for ix in range(2)):
            # One of the players lost on overtime
            player = 0 if oa[0] <= -100 else 1
            # Subtract 100 points from the player
            adj[player] = - min(100, sc[player])
            # If not enough to make the other player win, add to the other player
            if sc[player] + adj[player] >= sc[1 - player]:
                adj[1 - player] = sc[player] + adj[player] + 1 - sc[1 - player]
            # There is no consideration of rack leave in this case
            return

        if any(self._racks[ix].is_empty() for ix in range(2)):
            # Normal win by one of the players
            for ix in range(2):
                # Add double the score of the opponent's tiles (will be zero for the losing player)
                adj[ix] = 2 * Alphabet.score(self.rack(1 - ix))
        else:
            # Game expired by passes
            for ix in range(2):
                # Subtract the score of the player's own tiles
                adj[ix] = - Alphabet.score(self.rack(ix))

        # Apply overtime adjustment
        if oa:
            for ix in range(2):
                adj[ix] += oa[ix]

    def is_exchange_allowed(self):
        """ Is an ExchangeMove allowed? """
        return self._bag.allows_exchange()

    def add_pass(self):
        """ Add a pass to the count of consecutive pass moves """
        self._num_passes += 1

    def reset_passes(self):
        """ Reset the count of consecutive passes """
        self._num_passes = 0

    def __str__(self):
        return self._board.__str__() + \
            u"\n{0} {1} vs {2} {3}".format(self._player_names[0], self._scores[0],
                self._player_names[1], self._scores[1]) + \
            u"\n'{0}' vs '{1}'".format(self.rack(0), self.rack(1))


class Cover:

    """ Represents a covering of a square by a tile """

    def __init__(self, row, col, tile, letter):
        self.row = row
        self.col = col
        self.tile = tile
        self.letter = letter


class Error:

    # Error return codes from Move.check_legality()
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
    GAME_OVER = 16

    @staticmethod
    def errortext(errcode):
        return [u"LEGAL", 
            u"NULL_MOVE", 
            u"FIRST_MOVE_NOT_IN_CENTER", 
            u"DISJOINT", 
            u"NOT_ADJACENT", 
            u"SQUARE_ALREADY_OCCUPIED", 
            u"HAS_GAP",
            u"WORD_NOT_IN_DICTIONARY",
            u"CROSS_WORD_NOT_IN_DICTIONARY",
            u"TOO_MANY_TILES_PLAYED",
            u"TILE_NOT_IN_RACK",
            u"EXCHANGE_NOT_ALLOWED",
            u"TOO_MANY_TILES_EXCHANGED",
            u"OUT_OF_SYNC",
            u"LOGIN_REQUIRED",
            u"WRONG_USER",
            u"GAME_OVER"][errcode]


class Move:

    """ Represents a move by a player """

    # Bonus score for playing all 7 tiles in one move
    BINGO_BONUS = 50

    def __init__(self, word, row, col, horiz=True):
        # A list of squares covered by the play, i.e. actual tiles
        # laid down on the board
        self._covers = []
        # Number of letters in word formed (this may be >= len(self._covers))
        self._numletters = 0 if word is None else len(word)
        # The word formed
        self._word = word
        # The tiles used to form the word. '?' tiles are followed by the letter they represent.
        self._tiles = None
        # Starting row and column of word formed
        self._row = row
        self._col = col
        # Is the word horizontal or vertical?
        self._horizontal = horiz
        # Cached score of this move
        self._score = None

    def set_tiles(self, tiles):
        """ Set the tiles string once it is known """
        self._tiles = tiles

    def num_covers(self):
        """ Number of empty squares covered by this move """
        return len(self._covers)

    def details(self):
        """ Return a list of tuples describing this move """
        return [(Board.ROWIDS[c.row] + str(c.col + 1), # Coordinate
            c.tile, c.letter, # Tile and letter
            Alphabet.scores[c.tile]) # Score
            for c in self._covers]

    def summary(self, board):
        """ Return a summary of the move, as a tuple: (coordinate, tiles, score) """
        return (self.short_coordinate(), self._tiles, self.score(board))

    def short_coordinate(self):
        """ Return the coordinate of the move in 'Scrabble notation',
            i.e. row letter + column number for horizontal moves or
            column number + row letter for vertical ones """
        return Board.short_coordinate(self._horizontal, self._row, self._col)

    def __str__(self):
        """ Return the standard move notation of a coordinate followed by the word formed """
        return self.short_coordinate() + u":'" + self._word + u"'"

    def add_cover(self, row, col, tile, letter):
        """ Add a placement of a tile on a board square to this move """
        # Sanity check the input
        if row < 0 or row >= Board.SIZE:
            return False
        if col < 0 or col >= Board.SIZE:
            return False
        if (tile is None) or len(tile) != 1:
            return False
        if (letter is None) or len(letter) != 1 or (letter not in Alphabet.order):
            return False
        if tile != u'?' and tile != letter:
            return False
        if len(self._covers) >= Rack.MAX_TILES:
            # Already have 7 tiles being played
            return False
        self._covers.append(Cover(row, col, tile, letter))
        return True

    def add_validated_cover(self, cover):
        """ Add an already validated Cover object to this move """
        self._covers.append(cover)
        # Find out automatically whether this is a horizontal or vertical move
        if len(self._covers) == 2:
            self._horizontal = self._covers[0].row == cover.row

    def make_covers(self, board, tiles):
        """ Create a cover list out of a tile string """

        self.set_tiles(tiles)

        def enum_covers(tiles):
            """ Generator to enumerate through a tiles string, yielding (tile, letter) tuples """
            ix = 0
            while ix < len(tiles):
                if tiles[ix] == u'?':
                    # Wildcard tile: must be followed by its meaning
                    ix += 1
                    yield (u'?', tiles[ix])
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
        assert row - self._row == self._numletters * xd
        assert col - self._col == self._numletters * yd

    def check_legality(self, state):
        """ Check whether this move is legal on the board """

        # Must cover at least one square
        if len(self._covers) < 1:
            return Error.NULL_MOVE
        if len(self._covers) > Rack.MAX_TILES:
            return Error.TOO_MANY_TILES_PLAYED
        if state.is_game_over():
            return Error.GAME_OVER

        rack = state.player_rack()
        board = state.board()
        row = 0
        col = 0
        horiz = True
        vert = True
        first = True
        # All tiles played must be in the rack
        played = u''.join([c.tile for c in self._covers])
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
            self._horizontal = len(board.letters_left(row, col)) + len(board.letters_right(row, col)) >= \
                len(board.letters_above(row, col)) + len(board.letters_below(row, col))
            horiz = self._horizontal
            vert = not horiz
        # The move is purely horizontal or vertical
        if horiz:
            self._covers.sort(key = lambda x: x.col) # Sort in ascending column order
            self._horizontal = True
        else:
            self._covers.sort(key = lambda x: x.row) # Sort in ascending row order
            self._horizontal = False
        # Check whether eventual missing squares in the move sequence are already covered
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
                    assert vert
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
        self._word = u''
        self._tiles = u''
        cix = 0

        for ix in range(self._numletters):

            def add(cix):
                ltr = self._covers[cix].letter
                tile = self._covers[cix].tile
                self._word += ltr
                self._tiles += tile + (ltr if tile == u'?' else u'')

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

        # Check whether the word is in the dictionary
        if self._word not in Manager.word_db():
            # print(u"Word '{0}' not found in dictionary".format(self._word))
            return (Error.WORD_NOT_IN_DICTIONARY, self._word)
        # Check that the play is adjacent to some previously placed tile
        # (unless this is the first move, i.e. the board is empty)
        if board.is_empty():
            # Must go through the center square
            center = False
            for c in self._covers:
                if c.row == Board.SIZE // 2 and c.col == Board.SIZE // 2:
                    center = True
                    break
            if not center:
                return Error.FIRST_MOVE_NOT_IN_CENTER
        else:
            # Must be adjacent to something already on the board
            if not any([board.has_adjacent(c.row, c.col) for c in self._covers]):
                return Error.NOT_ADJACENT
            # Check all cross words formed by the new tiles
            for c in self._covers:
                if self._horizontal:
                    cross = board.letters_above(c.row, c.col) + c.letter + board.letters_below(c.row, c.col)
                else:
                    cross = board.letters_left(c.row, c.col) + c.letter + board.letters_right(c.row, c.col)
                if len(cross) > 1 and cross not in Manager.word_db():
                    return (Error.CROSS_WORD_NOT_IN_DICTIONARY, cross)
        # All checks pass: the play is legal
        return Error.LEGAL

    def score(self, board):
        """ Calculate the score of this move, which is assumed to be legal """

        # Check for cached score
        if self._score is not None:
            return self._score
        # Sum of letter scores
        total = 0
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

        # Tally the score of the primary word
        for ix in range(self._numletters):
            c = self._covers[cix] if cix < numcovers else None
            if c and (c.col == col) and (c.row == row):
                # This is one of the new tiles
                lscore = Alphabet.scores[c.tile]
                lscore *= Board.letterscore(row, col)
                wsc *= Board.wordscore(row, col)
                cix += 1
            else:
                # This is a tile that was already on the board
                # lscore = Alphabet.scores[self._word[ix]]
                tile = board.tile_at(row, col)
                lscore = Alphabet.scores[tile]
            sc += lscore
            row += xd
            col += yd

        total = sc * wsc

        # Tally the scores of words formed across the primary word
        for c in self._covers:
            if self._horizontal:
                cross = board.tiles_above(c.row, c.col) + board.tiles_below(c.row, c.col)
            else:
                cross = board.tiles_left(c.row, c.col) + board.tiles_right(c.row, c.col)
            if cross:
                sc = Alphabet.scores[c.tile]
                sc *= Board.letterscore(c.row, c.col)
                wsc = Board.wordscore(c.row, c.col)
                sc += sum(Alphabet.scores[tile] for tile in cross)
                total += sc * wsc
        # Add the bingo bonus of 50 points for playing all (seven) tiles
        if numcovers == Rack.MAX_TILES:
            total += Move.BINGO_BONUS
        # Cache the calculated score
        self._score = total
        return total

    def apply(self, state, shallow = False):
        """ Apply this move, assumed to be legal, to the board """
        board = state.board()
        rack = state.player_rack()
        for c in self._covers:
            board.set_letter(c.row, c.col, c.letter)
            board.set_tile(c.row, c.col, c.tile)
            if not shallow:
                rack.remove_tile(c.tile)
        state.reset_passes()


class ExchangeMove:

    """ Represents an exchange move, where tiles are returned to the bag
        and new tiles drawn instead """

    def __init__(self, tiles):
        self._tiles = tiles

    def __str__(self):
        """ Return a readable description of the move """
        return u"Exchanged {0}".format(len(self._tiles))

    def check_legality(self, state):
        """ Check whether this move is legal on the board """
        if state.bag().num_tiles() < Rack.MAX_TILES:
            return Error.EXCHANGE_NOT_ALLOWED
        if len(self._tiles) > Rack.MAX_TILES:
            return Error.TOO_MANY_TILES_EXCHANGED
        # All checks pass: the play is legal
        return Error.LEGAL

    def summary(self, board):
        """ Return a summary of the move, as a tuple: (coordinate, word, score) """
        return (u"", u"EXCH " + self._tiles, 0)

    def details(self):
        """ Return a tuple list describing tiles committed to the board by this move """
        return [] # No tiles

    def score(self, board):
        """ Calculate the score of this move, which is assumed to be legal """
        # An exchange move does not affect the score
        return 0

    def num_covers(self):
        """ Return the number of tiles played in this move """
        return 0

    def apply(self, state, shallow = False):
        """ Apply this move, assumed to be legal, to the current game state """
        if not shallow:
            state.player_rack().exchange(state.bag(), self._tiles)
        state.add_pass() # An exchange counts towards the pass count


class PassMove:

    """ Represents a pass move, where the player does nothing """

    def __init__(self):
        pass

    def __str__(self):
        """ Return the standard move notation of a coordinate followed by the word formed """
        return u"Pass"

    def summary(self, board):
        """ Return a summary of the move, as a tuple: (coordinate, word, score) """
        return (u"", u"PASS", 0)

    def details(self):
        """ Return a tuple list describing tiles committed to the board by this move """
        return [] # No tiles

    def check_legality(self, state):
        """ Check whether this move is legal on the board """
        # Always legal
        return Error.LEGAL

    def score(self, board):
        """ Calculate the score of this move, which is assumed to be legal """
        # A pass move does not affect the score
        return 0

    def num_covers(self):
        """ Return the number of tiles played in this move """
        return 0

    def apply(self, state, shallow = False):
        """ Apply this move, assumed to be legal, to the current game state """
        # Increment the number of consecutive Pass moves
        state.add_pass()


class ResignMove:

    """ Represents a resign move, where the player forfeits the game """

    def __init__(self, forfeited_points):
        self._forfeited_points = forfeited_points

    def __str__(self):
        """ Return the standard move notation of a coordinate followed by the word formed """
        return u"Resign"

    def summary(self, board):
        """ Return a summary of the move, as a tuple: (coordinate, word, score) """
        return (u"", u"RSGN", - self._forfeited_points)

    def details(self):
        """ Return a tuple list describing tiles committed to the board by this move """
        return [] # No tiles

    def check_legality(self, state):
        """ Check whether this move is legal on the board """
        # Always legal
        return Error.LEGAL

    def score(self, board):
        """ Calculate the score of this move, which is assumed to be legal """
        # A resignation loses all points
        return - self._forfeited_points

    def num_covers(self):
        """ Return the number of tiles played in this move """
        return 0

    def apply(self, state, shallow = False):
        """ Apply this move, assumed to be legal, to the current game state """
        # Resign the game, causing is_game_over() to become True
        state.resign_game()

