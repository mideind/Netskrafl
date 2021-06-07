/*

	Game.ts

	The Game class, as used in the single-page UI

  Copyright (C) 2021 Miðeind ehf.
  Author: Vilhjalmur Thorsteinsson

  The GNU Affero General Public License, version 3, applies to this software.
  For further information, see https://github.com/vthorsteinsson/Netskrafl

*/

export { Game, coord, toVector };

import { m } from "./mithril.js";

// Global constants
const ROWIDS = "ABCDEFGHIJKLMNO";
const BOARD_SIZE = ROWIDS.length;
const RACK_SIZE = 7;
const MAX_OVERTIME = 10 * 60.0; /* Maximum overtime before a player loses the game, 10 minutes in seconds */

function coord(row: number, col: number): string {
  // Return the co-ordinate string for the given 0-based row and col
  if (row < 0 || row >= BOARD_SIZE || col < 0 || col >= BOARD_SIZE)
    return null;
  return ROWIDS[row] + (col + 1);
}

function toVector(co: string): { col: number, row: number, dx: number, dy: number } {
  // Convert a co-ordinate string to a 0-based row, col and direction vector
  var dx = 0, dy = 0;
  var col = 0;
  var row = ROWIDS.indexOf(co[0]);
  if (row >= 0) {
    /* Horizontal move */
    col = parseInt(co.slice(1)) - 1;
    dx = 1;
  }
  else {
    /* Vertical move */
    row = ROWIDS.indexOf(co.slice(-1));
    col = parseInt(co) - 1;
    dy = 1;
  }
  return { col: col, row: row, dx: dx, dy: dy };
}

function forEachElement(selector: string, func: (elem: Element) => void) {
  // Emulate jQuery's $.each()
  const elems = document.querySelectorAll(selector);
  let i = 0;
  if (elems)
    for (; i < elems.length; i++)
      func(elems[i]);
}

function arrayEqual(a, b) {
  // Return true if arrays a and b are equal
  if (a.length != b.length)
    return false;
  for (let i = 0; i < a.length; i++)
    if (a[i] != b[i])
      return false;
  return true;
}

// A wrapper class around HTML5 local storage, if available

var LocalStorage = (function() {

  var _hasLocal = null; // Is HTML5 local storage supported by the browser?

  function hasLocalStorage(): boolean {
    // Return true if HTML5 local storage is supported by the browser
    if (_hasLocal === null)
      try {
        _hasLocal = ('localStorage' in window) &&
          (window.localStorage !== null) &&
          (window.localStorage !== undefined);
      } catch (e) {
        _hasLocal = false;
      }
    return _hasLocal;
  }

  function LocalStorage(uuid: string) {

    // Constructor for local storage associated with a particular game

    var prefix = "game." + uuid;

    return {
      getLocalTile: function(ix: number) {
        return window.localStorage[prefix + ".tile." + ix + ".t"];
      },
      getLocalTileSq: function(ix: number) {
        return window.localStorage[prefix + ".tile." + ix + ".sq"];
      },
      setLocalTile: function(ix: number, t: string) {
        window.localStorage[prefix + ".tile." + ix + ".t"] = t;
      },
      setLocalTileSq: function(ix: number, sq: string) {
        window.localStorage[prefix + ".tile." + ix + ".sq"] = sq;
      },
      clearTiles: function() {
        // Clean up local storage when game is over
        try {
          for (let i = 1; i <= RACK_SIZE; i++) {
            window.localStorage.removeItem(prefix + ".tile." + i + ".sq");
            window.localStorage.removeItem(prefix + ".tile." + i + ".t");
          }
        }
        catch (e) {
        }
      },
      saveTiles: function(tilesPlaced) {
        // Save tile locations in local storage
        let i;
        for (i = 0; i < tilesPlaced.length; i++) {
          // Store this placed tile in local storage
          let sq = tilesPlaced[i].sq;
          let tile = tilesPlaced[i].tile;
          // Set the placed tile's square
          this.setLocalTileSq(i + 1, sq);
          // Set the letter (or ?+letter if undefined)
          this.setLocalTile(i + 1, tile);
        }
        // Erase all remaining positions in local storage
        for (; i < RACK_SIZE; i++) {
          this.setLocalTileSq(i + 1, "");
          this.setLocalTile(i + 1, "");
        }
      },
      loadTiles: function() {
        // Return the saved tile locations
        var sq, tile;
        var tp = [];
        for (let i = 0; i < RACK_SIZE; i++) {
          sq = this.getLocalTileSq(i + 1);
          tile = this.getLocalTile(i + 1);
          if (sq && tile)
            tp.push({sq: sq, tile: tile});
        }
        return tp;
      }
    };
  }

  function NoLocalStorage(uuid: string) {
    // Constructor for a dummy local storage instance,
    // when no local storage is available
    return {
      clearTiles: function () {
      },
      saveTiles: function (tilesPlaced) {
      },
      loadTiles: function () {
      }
    };
  }

  // Choose and return a constructor function depending on
  // whether HTML5 local storage is available
  return hasLocalStorage() ? LocalStorage : NoLocalStorage;

} ());

// A class for games

var Game = (function() {

  // Constants

  const GAME_OVER = 99; // Error code corresponding to the Error class in skraflmechanics.py

  const BOARD = {
    standard: {
      WORDSCORE: [
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
        "3      3      3"
      ],
      LETTERSCORE: [
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
        "   2       2   "
      ]
    },
    explo: {
      WORDSCORE: [
        "3      3      3",
        "        2      ",
        "  2      2     ",
        "   2           ",
        "    2          ",
        "     2      2  ",
        "      2      2 ",
        "3             3",
        " 2      2      ",
        "  2      2     ",
        "          2    ",
        "           2   ",
        "     2         ",
        "      2        ",
        "3      3      3"
      ],
      LETTERSCORE: [
        "    2      2   ",
        " 3   2       3 ",
        "      3     2  ",
        "       2  3   2",
        "2          3   ",
        " 2       2     ",
        "  3     2      ",
        "   2       2   ",
        "      2     3  ",
        "     2   2   2 ",
        "   3          2",
        "2   3  2       ",
        "  2     3   2  ",
        " 3       2   3 ",
        "   2      2    "
      ]
    }
  };

  function Game(uuid: string, game) {
    // Game constructor
    // Add extra data and methods to our game model object
    this.uuid = uuid;
    // console.log("Game " + uuid + " loaded");
    this.zombie = false; // !!! FIXME
    this.gamelist = null; // No gamelist loaded yet
    this.messages = null;
    this.wordBad = false;
    this.wordGood = false;
    this.currentScore = undefined;
    this.showingDialog = null; // No dialog presently shown
    this.moveInProgress = false; // Is the server processing a move?
    this.askingForBlank = null;
    this.currentError = null;
    this.currentMessage = null;
    this.isFresh = false;
    this.numTileMoves = 0;
    this.chatShown = true; // False if the user has not seen all chat messages
    this.congratulate = false; // Show congratulation message if true
    this.selectedSq = null; // Currently selected (blinking) square
    this.sel = "movelist"; // By default, show the movelist tab
    this.moves = [];
    this.tiles = {};
    this.lastmove = undefined;
    this.autoplayer = [false, false];
    this.scores = [0, 0];
    this.bag = "";
    this.locale = "is_IS";
    this.alphabet = "";
    this.stats = null; // Game review statistics
    // Timed game clock stuff
    this.interval = null; // Game clock interval timer
    this.time_info = null; // Information about elapsed time
    this.time_info = { duration: 1.0, elapsed: [25.0, 15.0]}; // !!! DEBUG!
    this.penalty0 = 0;
    this.penalty1 = 0;
    this.timeBase = null; // Game time base
    this.runningOut0 = false;
    this.runningOut1 = false;
    this.blinking0 = false;
    this.blinking1 = false;
    this.clockText0 = "";
    this.clockText1 = "";
    // Create a local storage object for this game
    this.localStorage = LocalStorage(uuid);
    // Note: the following attributes have Python naming conventions,
    // since they are copied directly from JSON-encoded Python objects
    this.tile_scores = {};
    // Default to the standard board for the Icelandic locale
    this.board_type = "standard";
    this.centerSquare = "H8";
    this.centerCoord = [7, 7]; // row, col
    this.two_letter_words = [[], []];
    // Load previously saved tile positions from
    // local storage, if any
    var savedTiles = this.localStorage.loadTiles();
    this.init(game);
    // Put tiles in the same position as they were
    // when the player left the game
    this.restoreTiles(savedTiles);
    if (!this.over && this.isTimed())
      // Ongoing timed game: start the clock
      this.startClock();
  }

  Game.prototype.init = function(game) {
    // Initialize the game state with data from the server
    // !!! FIXME: If the last move was by the opponent, highlight it
    // Check whether the game is over, or whether there was an error
    this.over = game.result == GAME_OVER;
    if (this.over || game.result === 0)
      this.currentError = this.currentMessage = null;
    else {
      // Nonzero game.result: something is wrong
      this.currentError = game.result || "server";
      this.currentMessage = game.msg || "";
      return;
    }
    // Copy game JSON properties over to this object
    for (let key in game)
      if (game.hasOwnProperty(key))
        this[key] = game[key];
    if (game.newmoves !== undefined && game.newmoves.length > 0)
      // Add the newmoves list, if any, to the list of moves
      this.moves = this.moves.concat(game.newmoves);
    // Don't keep the new moves lying around
    this.newmoves = undefined;
    this.localturn = !this.over && ((this.moves.length % 2) == this.player);
    this.isFresh = true;
    this.two_letter_words = game.two_letter_words || [[], []];
    this.centerSquare = this.board_type == "explo" ? "C3" : "H8";
    this.centerCoord = this.board_type == "explo" ? [2, 2] : [7, 7];
    this.congratulate = this.over && this.player !== undefined &&
      (this.scores[this.player] > this.scores[1 - this.player]);
    if (this.currentError === null)
      // Generate a dictionary of tiles currently on the board,
      // from the moves already made. Also highlights the most recent
      // opponent move (contained in this.lastmove)
      this.placeTiles();
  };

  Game.prototype.update = function(game) {
    // Update the game state with data from the server,
    // either after submitting a move to the server or
    // after receiving a move notification via the Firebase listener
    if (game.num_moves !== undefined && game.num_moves <= this.moves.length)
      // This is probably a starting notification from Firebase,
      // not adding a new move but repeating the last move made: ignore it
      return;
    // Stop highlighting the previous opponent move, if any
    for (let sq in this.tiles)
      if (this.tiles.hasOwnProperty(sq))
        this.tiles[sq].freshtile = false;
    this.init(game);
    if (this.currentError === null) {
      if (this.succ_chall) {
        // Successful challenge: reset the rack
        // (this updates the score as well)
        this.resetRack();
      }
      else {
        this.updateScore();
      }
    }
    this.saveTiles();
    if (this.isTimed())
      this.resetClock();
  };

  Game.prototype.notifyUserChange = function(newNick: string) {
    // The user information may have been changed:
    // perform any updates that may be necessary
    if (this.player !== undefined)
      // The player nickname may have been changed
      this.nickname[this.player] = newNick;
  };

  Game.prototype.setSelectedTab = function(sel: number) {
    // Set the currently selected tab
    this.sel = sel;
  };

  Game.prototype.tilescore = function(tile: string) {
    // Note: The Python naming convention of tile_score is intentional
    return this.tile_scores[tile];
  };

  Game.prototype.twoLetterWords = function() {
    // Note: The Python naming convention of two_letter_words is intentional
    return this.two_letter_words;
  };

  Game.prototype.isTimed = function(): boolean {
    // Return True if this is a timed game
    return this.time_info && this.time_info.duration >= 1.0;
  };

  Game.prototype.updateClock = function() {
    var txt0 = this.calcTimeToGo(0);
    var txt1 = this.calcTimeToGo(1);
    this.clockText0 = txt0;
    this.clockText1 = txt1;
    // If less than two minutes left, indicate that time is running out
    this.runningOut0 = (txt0[0] == "-" || txt0 <= "02:00");
    this.runningOut1 = (txt1[0] == "-" || txt1 <= "02:00");
    // If less than 30 seconds left, make the clock digits blink
    this.blinking0 = (this.runningOut0 && txt0 >= "00:00" && txt0 <= "00:30" && this.player == 0);
    this.blinking1 = (this.runningOut1 && txt1 >= "00:00" && txt1 <= "00:30" && this.player == 1);
    m.redraw();
  };

  Game.prototype.resetClock = function() {
    // Set a new time base after receiving an update from the server
    this.timeBase = new Date();
    this.updateClock();
    if (this.over) {
      // Game over: reset stuff
      if (this.interval) {
        window.clearInterval(this.interval);
        this.interval = null;
      }
      this.blinking0 = false;
      this.blinking1 = false;
      this.runningOut0 = false;
      this.runningOut1 = false;
    }
  };

  Game.prototype.startClock = function() {
    // Start the clock running, after loading a timed game
    this.resetClock();
    if (!this.interval) {
      this.interval = window.setInterval(
        () => { this.updateClock(); },
        500 // milliseconds, i.e. 0.5 seconds
      );
    }
  };

  Game.prototype.cleanup = function () {
    /* Clean up any resources owned by this game object */
    if (this.interval) {
      window.clearInterval(this.interval);
      this.interval = null;
    }
  };

  Game.prototype.calcTimeToGo = function(player: 0 | 1) {
    /* Return the time left for a player in a nice MM:SS format */
    var gameTime = this.time_info
    var elapsed = gameTime.elapsed[player];
    var gameOver = this.over;
    if (!gameOver && (this.moves.length % 2) == player) {
      // This player's turn: add the local elapsed time
      var now = new Date();
      elapsed += (now.getTime() - this.timeBase.getTime()) / 1000;
      if (elapsed - gameTime.duration * 60.0 > MAX_OVERTIME) {
        // 10 minutes overtime has passed:
        // The player has lost - do this the brute force way and refresh the page
        // to get the server's final verdict
        // !!! TODO
        // reloadInterval = window.setInterval(reloadPage, 500);  // Do this in half a sec
      }
    }
    // The overtime is max 10 minutes - at that point you lose
    var timeToGo = Math.max(gameTime.duration * 60.0 - elapsed, -MAX_OVERTIME);
    var absTime = Math.abs(timeToGo);
    var min = Math.floor(absTime / 60.0);
    var sec = Math.floor(absTime - min * 60.0);
    if (gameOver) {
      // We already got a correct score from the server
      this.penalty0 = 0;
      this.penalty1 = 0;
    }
    else
    if (timeToGo < 0.0) {
      // We're into overtime: calculate the score penalty
      if (player === 0)
        this.penalty0 = -10 * Math.floor((min * 60 + sec + 59) / 60);
      else
        this.penalty1 = -10 * Math.floor((min * 60 + sec + 59) / 60);
    }
    return (timeToGo < 0.0 ? "-" : "") +
       ("0" + min.toString()).slice(-2) + ":" + ("0" + sec.toString()).slice(-2);
  };

  Game.prototype.displayScore = function(player: 0 | 1): number {
    // Return the score to be displayed, which is the current
    // actual game score minus accrued time penalty, if any, in a timed game
    return Math.max(
      this.scores[player] + (player == 0 ? this.penalty0 : this.penalty1), 0
    )
  };

  Game.prototype.loadGames = function() {
    // Load the list of other games being played by this player
    return m.request(
      {
        method: "POST",
        url: "/gamelist",
        body: { zombie: false }
      }
    ).then((result) => {
      if (!result || result.result !== 0)
        this.gamelist = [];
      else
        this.gamelist = result.gamelist;
    });
  };

  Game.prototype.loadMessages = function() {
    // Load chat messages for this game
    this.messages = []; // Prevent double loading
    return m.request(
      {
        method: "POST",
        url: "/chatload",
        body: { channel: "game:" + this.uuid }
      }
    ).then((result) => {
      if (result.ok)
        this.messages = result.messages || [];
      else
        this.messages = [];
      // !!! FIXME: The following is too simplistic;
      // !!! we should check for a new message from the
      // !!! opponent that comes after the last message-seen
      // !!! marker
      this.chatShown = this.messages.length === 0;
    });
  };

  Game.prototype.loadStats = function() {
    // Load statistics about a game
    this.stats = undefined; // Error/in-progress status
    return m.request(
      {
        method: "POST",
        url: "/gamestats",
        body: { game: this.uuid }
      }
    ).then((json) => {
      // Save the incoming game statistics in the stats property
      if (!json || json.result === undefined)
        return;
      if (json.result !== 0 && json.result !== GAME_OVER)
        return;
      // Success: assign the stats
      this.stats = json;
    });
  };

  Game.prototype.sendMessage = function(msg: string) {
    // Send a chat message
    return m.request(
      {
        method: "POST",
        url: "/chatmsg",
        body: { channel: "game:" + this.uuid, msg: msg }
      }
    ).then((result) => {
      // The updated chat comes in via a Firebase notification
    });
  };

  Game.prototype.sendChatSeenMarker = function() {
    // Send a 'chat message seen' marker to the server
    this.sendMessage("");
    // The user has now seen all chat messages
    this.chatShown = true;
  };

  Game.prototype.addChatMessage = function(from_userid: string, msg: string, ts: string) {
    // Add a new chat message to the message list
    if (this.messages !== null) {
      // Do not add messages unless the message list has been
      // properly initialized from the server. This means that
      // we skip the initial chat message update that happens
      // immediately as we add a listener to the chat path.
      this.messages.push({ from_userid: from_userid, msg: msg, ts: ts });
      if (this.sel != "chat" && msg != "")
        // We have a new chat message that the user hasn't seen yet
        this.chatShown = false;
    }
  };

  Game.prototype.markChatShown = function(): boolean {
    // Note that the user has seen all pending chat messages
    if (!this.chatShown) {
      this.chatShown = true;
      return true;
    }
    return false;
  };

  Game.prototype.placeMove = function(player: 0 | 1, co: string, tiles: string, highlight: boolean) {
    // Place an entire move into the tiles dictionary
    let vec = toVector(co);
    let col = vec.col;
    let row = vec.row;
    let nextBlank = false;
    for (let i = 0; i < tiles.length; i++) {
      let tile = tiles[i];
      if (tile == '?') {
        nextBlank = true;
        continue;
      }
      let sq = coord(row, col);
      let letter = tile;
      if (nextBlank)
        tile = '?';
      let tscore = this.tilescore(tile);
      // Place the tile, if it isn't there already
      if (!(sq in this.tiles)) {
        this.tiles[sq] = {
          player: player,
          tile: tile,
          letter: letter,
          score: tscore,
          draggable: false,
          freshtile: false,
          index: 0, // Index of this tile within the move, for animation purposes
          xchg: false,
        };
        if (highlight) {
          // Highlight the tile
          if (player == this.player)
            this.tiles[sq].highlight = 0; // Local player color
          else
            this.tiles[sq].highlight = 1; // Remote player color
        }
      }
      col += vec.dx;
      row += vec.dy;
      nextBlank = false;
    }
  };

  Game.prototype.setRack = function(rack) {
    // Set the current rack
    this.rack = rack;
  };

  Game.prototype.placeTiles = function(move: number, noHighlight: boolean) {
    // Make a tile dictionary for the game.
    // If move is given, it is an index of the
    // last move in the move list that should be
    // shown on the board.
    this.tiles = {};
    this.numTileMoves = 0;
    let mlist = this.moves;
    let sq;
    let last = (move !== undefined) ? move : mlist.length;

    function successfullyChallenged(ix: number): boolean {
      // Was the move with index ix successfully challenged?
      if (ix + 2 >= last)
        // The move list is too short for a response move
        return false;
      let mv = mlist[ix + 2];
      let co = mv[1][0];
      let tiles = mv[1][1];
      if (co != "")
        // The player's next move is a normal tile move
        return false;
      let score = mv[1][2];
      // Return true if this was a challenge response with a negative score
      // (i.e. a successful challenge)
      return (tiles == "RESP") && (score < 0);
    }

    for (let i = 0; i < last; i++) {
      let mv = mlist[i];
      let player = mv[0];
      let co = mv[1][0];
      let tiles = mv[1][1];
      if (co != "" && !successfullyChallenged(i)) {
        // Unchallenged tile move: place it on the board
        let highlight = (move !== undefined) && (i == move - 1) && !noHighlight;
        this.placeMove(player, co, tiles, highlight);
        this.numTileMoves++;
      }
    }
    // If it's our turn, mark the opponent's last move
    // The type of this.lastmove corresponds to DetailTuple on the server side
    mlist = this.lastmove;
    if (mlist !== undefined && mlist.length && this.localturn)
      for (let i = 0; i < mlist.length; i++) {
        sq = mlist[i][0];
        if (!(sq in this.tiles))
          throw "Tile from lastmove not in square " + sq;
        this.tiles[sq].freshtile = true;
        this.tiles[sq].index = i; // Index of tile within move, for animation purposes
      }
    // Also put the rack tiles into this.tiles
    for (let i = 0; i < this.rack.length; i++) {
      sq = 'R' + (i + 1);
      let tile = this.rack[i][0];
      let letter = (tile == '?') ? ' ' : tile;
      let tscore = this.rack[i][1];
      this.tiles[sq] = {
        player: this.player,
        tile: tile,
        letter: letter,
        score: tscore,
        draggable: true,
        freshtile: false,
        index: 0,
        xchg: false
      };
    }
  };

  Game.prototype._moveTile = function(from: string, to: string) {
    // Low-level function to move a tile between cells/slots
    if (from == to)
      // Nothing to do
      return;
    let fromTile = this.tiles[from];
    if (fromTile === undefined)
      throw "Moving from an empty square";
    delete this.tiles[from];
    if (to in this.tiles) {
      if (to.charAt(0) != "R")
        throw "Dropping to an occupied square";
      // Dropping to an occupied slot in the rack:
      // create space in the rack
      let dest = parseInt(to.slice(1));
      let empty = dest + 1;
      // Try to find an empty slot to the right of the drop destination
      while (('R' + empty) in this.tiles)
        empty++;
      if (empty <= RACK_SIZE) {
        // Found empty slot after the tile:
        // move the intervening tiles to the right
        for (let j = empty; j > dest; j--)
          this.tiles['R' + j] = this.tiles['R' + (j - 1)];
      }
      else {
        // No empty slots after the tile: try to find one to the left
        empty = dest - 1;
        while (('R' + empty) in this.tiles)
          empty--;
        if (empty < 1)
          throw "No place in rack to drop tile";
        for (let j = empty; j < dest; j++)
          this.tiles['R' + j] = this.tiles['R' + (j + 1)];
      }
    }
    if (to[0] == 'R' && fromTile.tile == '?')
    // Putting a blank tile back into the rack: erase its meaning
      fromTile.letter = ' ';
    this.tiles[to] = fromTile;
  };

  Game.prototype.moveTile = function(from: string, to: string) {
    // High-level function to move a tile between cells/slots
    this._moveTile(from, to);
    // Clear error message, if any
    this.currentError = this.currentMessage = null;
    // Update the current word score
    this.updateScore();
    // Update the local storage
    this.saveTiles();
  };

  Game.prototype.attemptMove = function(from: string, to: string) {
    if (to == from)
      // No move
      return;
    if (to in this.tiles && to[0] != 'R')
      throw "Square " + to + " occupied";
    if (!(from in this.tiles))
      throw "No tile at " + from;
    let tile = this.tiles[from];
    if (to[0] != 'R' && tile.tile == '?' && tile.letter == ' ') {
      // Dropping a blank tile on the board:
      // postpone the move and ask for its meaning
      this.askingForBlank = { from: from, to: to };
      return;
    }
    // Complete the move
    this.moveTile(from, to);
  };

  Game.prototype.cancelBlankDialog = function() {
    // Cancel the dialog asking for the meaning of the blank tile
    this.askingForBlank = null;
  };

  Game.prototype.placeBlank = function(letter: string) {
    // Assign a meaning to a blank tile that is being placed on the board
    if (this.askingForBlank === null)
      return;
    let from = this.askingForBlank.from;
    let to = this.askingForBlank.to;
    // We must assign the tile letter before moving it
    // since moveTile() calls updateScore() which in turn does a /wordcheck
    this.tiles[from].letter = letter;
    this.moveTile(from, to);
    this.askingForBlank = null;
  };

  Game.prototype.tilesPlaced = function(): string[] {
    // Return a list of coordinates of tiles that the user has
    // placed on the board by dragging from the rack
    let r: string[] = [];
    for (let sq in this.tiles)
      if (this.tiles.hasOwnProperty(sq) &&
        sq[0] != 'R' && this.tiles[sq].draggable)
        // Found a non-rack tile that is not glued to the board
        r.push(sq);
    return r;
  };

  Game.prototype.sendMove = function(moves) {
    // Send a move to the server
    this.moveInProgress = true;
    return m.request(
      {
        method: "POST",
        url: "/submitmove",
        body: { moves: moves, mcount: this.moves.length, uuid: this.uuid }
      }
    ).then((result) => {
        this.moveInProgress = false;
        // The update() function also handles error results
        this.update(result);
      }
    ).catch((e) => {
        this.moveInProgress = false;
        this.currentError = "server";
        this.currentMessage = e;
      }
    );
  };

  Game.prototype.submitMove = function() {
    // Send a tile move to the server
    let t = this.tilesPlaced();
    let moves = [];
    this.selectedSq = null; // Currently selected (blinking) square
    for (let i = 0; i < t.length; i++) {
      let sq = t[i];
      let tile = this.tiles[sq];
      moves.push(sq + "=" + tile.tile + (tile.tile == '?' ? tile.letter : ""));
    }
    if (moves.length > 0)
      this.sendMove(moves);
  };

  Game.prototype.submitPass = function() {
    // Show a pass confirmation prompt
    this.showingDialog = "pass";
    this.selectedSq = null; // Currently selected (blinking) square
  };

  Game.prototype.submitChallenge = function() {
    // Show a challenge confirmation prompt
    this.showingDialog = "chall";
    this.selectedSq = null; // Currently selected (blinking) square
  };

  Game.prototype.submitExchange = function() {
    // Show an exchange prompt
    this.showingDialog = "exchange";
    this.selectedSq = null; // Currently selected (blinking) square
    // Remove the xchg flag from all tiles in the rack
    for (let i = 1; i <= RACK_SIZE; i++) {
      let sq = "R" + i;
      if (sq in this.tiles)
        this.tiles[sq].xchg = false;
    }
  };

  Game.prototype.submitResign = function() {
    // Show a resign prompt
    this.showingDialog = "resign";
    this.selectedSq = null; // Currently selected (blinking) square
  };

  Game.prototype.confirmPass = function(yes: boolean) {
    // Handle reply to pass confirmation prompt
    this.showingDialog = null;
    if (yes)
      this.sendMove([ "pass" ]);
  };

  Game.prototype.confirmChallenge = function(yes: boolean) {
    // Handle reply to challenge confirmation prompt
    this.showingDialog = null;
    if (yes)
      this.sendMove([ "chall" ]);
  };

  Game.prototype.confirmExchange = function(yes: boolean) {
    // Handle reply to exchange confirmation prompt
    let exch = "";
    this.showingDialog = null;
    for (let i = 1; i <= RACK_SIZE; i++) {
      let sq = "R" + i;
      if (sq in this.tiles && this.tiles[sq].xchg) {
        // This tile is marked for exchange
        exch += this.tiles[sq].tile;
        this.tiles[sq].xchg = false;
      }
    }
    if (yes && exch.length > 0)
      // Send the exchange move to the server
      this.sendMove([ "exch=" + exch ]);
  };

  Game.prototype.confirmResign = function(yes: boolean) {
    // Handle reply to resignation confirmation prompt
    this.showingDialog = null;
    if (yes)
      this.sendMove([ "rsgn" ]);
  };

  Game.prototype.rescrambleRack = function() {
    // Reorder the rack randomly. Bound to the Backspace key.
    this.selectedSq = null; // Currently selected (blinking) square
    if (this.showingDialog !== null)
      return;
    this._resetRack();
    var array = [];
    var rackTileId;
    for (let i = 1; i <= RACK_SIZE; i++) {
      rackTileId = "R" + i;
      if (rackTileId in this.tiles)
        array.push(this.tiles[rackTileId]);
      else
        array.push(null);
    }
    var currentIndex = array.length, temporaryValue, randomIndex;
    // Fisher-Yates (Knuth) shuffle algorithm
    while (0 !== currentIndex) {
      randomIndex = Math.floor(Math.random() * currentIndex);
      currentIndex -= 1;
      temporaryValue = array[currentIndex];
      array[currentIndex] = array[randomIndex];
      array[randomIndex] = temporaryValue;
    }
    for (let i = 1; i <= RACK_SIZE; i++) {
      rackTileId = "R" + i;
      if (array[i-1] === null)
        delete this.tiles[rackTileId];
      else
        this.tiles[rackTileId] = array[i-1];
    }
    this.saveTiles();
  };

  Game.prototype.saveTiles = function() {
    // Save the current unglued tile configuration to local storage
    var tp = [];
    var sq: string, t, tile: string;
    var tilesPlaced = this.tilesPlaced();
    for (let i = 0; i < tilesPlaced.length; i++) {
      sq = tilesPlaced[i];
      t = this.tiles[sq];
      tile = t.tile;
      // For blank tiles, store their meaning as well
      if (tile == "?")
        tile += t.letter;
      tp.push({sq: sq, tile: tile});
    }
    // Also save tiles remaining in the rack
    for (let i = 1; i <= RACK_SIZE; i++) {
      sq = "R" + i;
      if (sq in this.tiles)
        tp.push({sq: sq, tile: this.tiles[sq].tile});
    }
    this.localStorage.saveTiles(tp);
  };

  Game.prototype.restoreTiles = function(savedTiles) {
    // Restore the tile positions that were previously stored
    // in local storage
    if (!savedTiles.length)
      // Nothing to do
      return;
    var tile;
    var savedLetters = [];
    var rackLetters = [];
    var rackTiles = {};
    // First, check that the saved tiles match the current rack
    for (let i = 0; i < savedTiles.length; i++)
      savedLetters.push(savedTiles[i].tile.charAt(0));
    for (let i = 1; i <= RACK_SIZE; i++)
      if (("R" + i) in this.tiles)
        rackLetters.push(this.tiles["R" + i].tile.charAt(0));
    savedLetters.sort();
    rackLetters.sort();
    if (!arrayEqual(savedLetters, rackLetters))
      // We don't have the same rack as when the state was saved:
      // give up
      return;
    // Save the original rack and delete the rack tiles
    // from the board
    for (let j = 1; j <= RACK_SIZE; j++)
      if (("R" + j) in this.tiles) {
        rackTiles["R" + j] = this.tiles["R" + j];
        delete this.tiles["R" + j];
      }
    // Attempt to move the saved tiles from the saved rack to
    // their saved positions. Note that there are several corner
    // cases, for instance multiple instances of the same letter tile,
    // that make this code less than straightforward.
    for (let i = 0; i < savedTiles.length; i++) {
      let saved_sq = savedTiles[i].sq;
      if (!(saved_sq in this.tiles)) {
        // The saved destination square is empty:
        // find the tile in the saved rack and move it there
        tile = savedTiles[i].tile;
        for (let sq in rackTiles)
          if (rackTiles.hasOwnProperty(sq) &&
            rackTiles[sq].tile == tile.charAt(0)) {
            // Found the tile (or its equivalent) in the rack: move it
            if (tile.charAt(0) == "?")
              if (saved_sq.charAt(0) == "R")
                // Going to the rack: no associated letter
                rackTiles[sq].letter = " ";
              else
                // Going to a board square: associate the originally
                // chosen and saved letter
                rackTiles[sq].letter = tile.charAt(1);
            // ...and assign it
            this.tiles[saved_sq] = rackTiles[sq];
            delete rackTiles[sq];
            break;
          }
      }
    }
    // Allocate any remaining tiles to free slots in the rack
    let j = 1;
    for (let sq in rackTiles)
      if (rackTiles.hasOwnProperty(sq)) {
        // Look for a free slot in the rack
        while(("R" + j) in this.tiles)
          j++;
        if (j <= RACK_SIZE)
          // Should always be true unless something is very wrong
          this.tiles["R" + j] = rackTiles[sq];
      }
    // The local storage may have been cleared before calling
    // restoreTiles() so we must ensure that it is updated
    this.saveTiles();
    // Show an updated word status and score
    this.updateScore();
  };

  Game.prototype._resetRack = function() {
    // Recall all unglued tiles into the rack
    var t = this.tilesPlaced();
    if (t.length) {
      let i = 1;
      for (let j = 0; j < t.length; j++) {
        // Find a free slot in the rack
        while (("R" + i) in this.tiles)
          i++;
        var sq = "R" + i;
        // Recall the tile
        this.tiles[sq] = this.tiles[t[j]];
        delete this.tiles[t[j]];
        if (this.tiles[sq].tile == '?')
          // Erase the meaning of the blank tile
          this.tiles[sq].letter = ' ';
        i++;
      }
      // Update score
      this.updateScore();
    }
    // Reset current error message, if any
    this.currentError = null;
  };

  Game.prototype.resetRack = function() {
    // Recall all unglued tiles into the rack
    this.selectedSq = null; // Currently selected (blinking) square
    this._resetRack();
    this.saveTiles();
  };

  Game.prototype.updateScore = function() {
    // Re-calculate the current word score
    var scoreResult = this.calcScore();
    this.wordGood = false;
    this.wordBad = false;
    if (scoreResult === undefined)
      this.currentScore = undefined;
    else {
      this.currentScore = scoreResult.score;
      var wordToCheck = scoreResult.word;
      if (!this.manual) {
        m.request(
          {
            method: "POST",
            url: "/wordcheck",
            body: { locale: this.locale, word: scoreResult.word, words: scoreResult.words }
          }
        ).then((result) => {
            if (result && result.word == wordToCheck) {
              this.wordGood = result.ok;
              this.wordBad = !result.ok;
            }
          }
        );
      }
    }
  };

  Game.prototype.wordScore = function(row: number, col: number): number {
    // Return the word score multiplier at the given coordinate
    // on the game's board
    var wsc = BOARD[this.board_type].WORDSCORE;
    return parseInt(wsc[row].charAt(col)) || 1;
  };

  Game.prototype.letterScore = function(row: number, col: number): number {
    // Return the letter score multiplier at the given coordinate
    // on the game's board
    var lsc = BOARD[this.board_type].LETTERSCORE;
    return parseInt(lsc[row].charAt(col)) || 1;
  };

  Game.prototype.squareType = function(row: number, col: number): string {
    // Return the square type, or "" if none
    var wsc = this.wordScore(row, col);
    if (wsc == 2)
      return "dw"; // Double word
    if (wsc == 3)
      return "tw"; // Triple word
    var lsc = this.letterScore(row, col);
    if (lsc == 2)
      return "dl"; // Double letter
    if (lsc == 3)
      return "tl"; // Triple letter
    return ""; // Plain square
  };

  Game.prototype.squareClass = function(coord: string): string {
    // Given a coordinate in string form, return the square's type/class
    if (!coord || coord[0] == "R")
      return undefined;
    var vec = toVector(coord);
    return this.squareType(vec.row, vec.col) || undefined;
  };

  Game.prototype.tileAt = function(row: number, col: number) {
    return this.tiles[coord(row, col)] || null;
  };

  Game.prototype.calcScore = function() {
    // Calculate the score for the tiles that have been laid on the board in the current move
    var score = 0, crossScore = 0;
    var wsc = 1;
    var minrow = BOARD_SIZE, mincol = BOARD_SIZE;
    var maxrow = 0, maxcol = 0;
    var numtiles = 0, numcrosses = 0;
    var word = "";
    var words = [];
    this.tilesPlaced().forEach((sq) => {
      // Tile on the board
      var row = ROWIDS.indexOf(sq.charAt(0));
      var col = parseInt(sq.slice(1)) - 1;
      var t = this.tiles[sq];
      score += t.score * this.letterScore(row, col);
      numtiles++;
      wsc *= this.wordScore(row, col);
      if (row < minrow)
        minrow = row;
      if (col < mincol)
        mincol = col;
      if (row > maxrow)
        maxrow = row;
      if (col > maxcol)
        maxcol = col;
    });
    if (!numtiles)
      return undefined;
    if (minrow != maxrow && mincol != maxcol)
      // Not a pure horizontal or vertical move
      return undefined;
    var x = mincol, y = minrow;
    var dx = 0, dy = 0;
    if (minrow != maxrow)
      dy = 1; // Vertical
    else
    if (mincol == maxcol &&
      (this.tileAt(minrow - 1, mincol) !== null || this.tileAt(minrow + 1, mincol) !== null))
      // Single tile: if it has tiles above or below, consider this a vertical move
      dy = 1;
    else
      dx = 1; // Horizontal
    // Find the beginning of the word
    while (this.tileAt(y - dy, x - dx) !== null) {
      x -= dx;
      y -= dy;
    }
    var t;
    // Find the end of the word
    while ((t = this.tileAt(y, x)) !== null) {
      if (t.draggable) {
        // Add score for cross words
        var csc = this.calcCrossScore(y, x, 1 - dy, 1 - dx);
        if (csc.score >= 0) {
          // There was a cross word there (it can score 0 if blank)
          crossScore += csc.score;
          numcrosses++;
          words.push(csc.word);
        }
      }
      else {
        // This is a tile that was previously on the board
        score += t.score;
        numcrosses++;
      }
      // Accumulate the word being formed
      word += t.letter;
      x += dx;
      y += dy;
    }
    if (this.numTileMoves === 0) {
      // First move that actually lays down tiles must go through center square
      var c = this.centerCoord;
      if (null === this.tileAt(c[0], c[1]))
        // No tile in the center square
        return undefined;
    }
    else
    if (!numcrosses)
      // Not first move, and not linked with any word on the board
      return undefined;
    // Check whether word is consecutive
    // (which it is not if there is an empty square before the last tile)
    if (dx && (x <= maxcol))
      return undefined;
    if (dy && (y <= maxrow))
      return undefined;
    words.push(word);
    return { word: word, words: words,
      score: score * wsc + crossScore + (numtiles == RACK_SIZE ? 50 : 0) };
  };

  Game.prototype.calcCrossScore = function(oy, ox, dy, dx) {
    // Calculate the score contribution of a cross word
    var score = 0;
    var hascross = false;
    var x = ox, y = oy;
    var word = "";
    // Find the beginning of the word
    while (this.tileAt(y - dy, x - dx) !== null) {
      x -= dx;
      y -= dy;
    }
    var t;
    // Find the end of the word
    while ((t = this.tileAt(y, x)) !== null) {
      var sc = t.score;
      if (x == ox && y == oy)
        sc *= this.letterScore(y, x);
      else
        hascross = true;
      word += t.letter;
      score += sc;
      x += dx;
      y += dy;
    }
    if (!hascross)
      return { score: -1, word: "" };
    return { score: score * this.wordScore(oy, ox), word: word };
  };

  return Game;

} ());

