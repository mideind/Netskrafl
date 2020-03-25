/*

	Game.js

	The Game class, as used in the single-page UI

  Copyright (C) 2015-2018 Miðeind ehf.
  Author: Vilhjalmur Thorsteinsson

  The GNU General Public License, version 3, applies to this software.
  For further information, see https://github.com/vthorsteinsson/Netskrafl

*/

var ROWIDS = "ABCDEFGHIJKLMNO";
var BOARD_SIZE = ROWIDS.length;

function coord(row, col) {
  // Return the co-ordinate string for the given 0-based row and col
  if (row < 0 || row >= 15 || col < 0 || col >= 15)
    return null;
  return ROWIDS[row] + (col + 1).toString();
}

function toVector(co) {
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

var Game = (function() {

"use strict";

// Constants

var RACK_SIZE = 7;
var GAME_OVER = 99; /* Error code corresponding to the Error class in skraflmechanics.py */

// Original Icelandic bag
var OLD_TILESCORE = {
   'a': 1, 'á': 4, 'b': 6, 'd': 4, 'ð': 2, 'e': 1, 'é': 6, 'f': 3, 'g': 2,
   'h': 3, 'i': 1, 'í': 4, 'j': 5, 'k': 2, 'l': 2, 'm': 2, 'n': 1, 'o': 3,
   'ó': 6, 'p': 8, 'r': 1, 's': 1, 't': 1, 'u': 1, 'ú': 8, 'v': 3, 'x': 10,
   'y': 7, 'ý': 9, 'þ': 4, 'æ': 5, 'ö': 7, '?': 0
};

// New Icelandic bag
var NEW_TILESCORE = {
   'a': 1, 'á': 3, 'b': 5, 'd': 5, 'ð': 2, 'e': 3, 'é': 7, 'f': 3, 'g': 3,
   'h': 4, 'i': 1, 'í': 4, 'j': 6, 'k': 2, 'l': 2, 'm': 2, 'n': 1, 'o': 5,
   'ó': 3, 'p': 5, 'r': 1, 's': 1, 't': 2, 'u': 2, 'ú': 4, 'v': 5, 'x': 10,
   'y': 6, 'ý': 5, 'þ': 7, 'æ': 4, 'ö': 6, '?': 0
};

var WORDSCORE = [
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
   "311111131111113"
];

var LETTERSCORE = [
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
   "111211111112111"
];


function Game(uuid, game) {
  // Add extra data and methods to our game model object
  this.uuid = uuid;
  // console.log("Game " + uuid + " loaded");
  this.zombie = false; // !!! TBD
  // Create a local storage object for this game
  this.localStorage = new LocalStorage(uuid);
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
  this.update(game);
}

Game.prototype.update = function(game) {
  // Update the game state with new data from the server
  if (game.num_moves <= this.moves.length)
    // This is probably a starting notification from Firebase,
    // not adding a new move but repeating the last move made: ignore it
    // !!! TODO: If the last move was by the opponent, highlight it
    return;
  this.over = game.result == GAME_OVER;
  if (this.over || !game.result)
    this.currentError = this.currentMessage = null;
  else {
    this.currentError = game.result;
    this.currentMessage = game.msg;
  }
  // Copy game JSON properties over to this object
  for (var key in game)
    if (game.hasOwnProperty(key))
      this[key] = game[key];
  if (game.newmoves !== undefined && game.newmoves.length > 0)
    // Add the newmoves list, if any, to the list of moves
    this.moves = this.moves.concat(game.newmoves);
  this.newmoves = undefined;
  this.localturn = !this.over && ((this.moves.length % 2) == this.player);
  this.isFresh = true;
  this.congratulate = this.over && this.player !== undefined &&
    (this.scores[this.player] > this.scores[1 - this.player]);
  if (this.currentError === null) {
    // Generate a dictionary of tiles currently on the board,
    // from the moves already made
    this.placeTiles();
    if (this.succ_chall) {
      // Successful challenge: reset the rack
      // (this updates the score as well)
      this.resetRack();
    }
    else
      this.updateScore();
  }
};

Game.prototype.setSelectedTab = function(sel) {
  // Set the currently selected tab
  this.sel = sel;
};

Game.prototype.tilescore = function(tile) {
  return this.newbag ? NEW_TILESCORE[tile] : OLD_TILESCORE[tile];
};

Game.prototype.loadGames = function() {
  // Load the list of other games being played by this player
  return m.request({
    method: "POST",
    url: "/gamelist",
    data: { zombie: false }
  })
  .then(function(result) {
    if (!result || result.result !== 0)
      this.gamelist = [];
    else
      this.gamelist = result.gamelist;
  }.bind(this));
};

Game.prototype.loadMessages = function() {
  // Load chat messages for this game
  this.messages = []; // Prevent double loading
  return m.request({
    method: "POST",
    url: "/chatload",
    data: { channel: "game:" + this.uuid }
  })
  .then(function(result) {
    if (result.ok)
      this.messages = result.messages || [];
    else
      this.messages = [];
    // !!! TODO: The following is too simplistic;
    // !!! we should check for a new message from the
    // !!! opponent that comes after the last message-seen
    // !!! marker
    this.chatShown = this.messages.length == 0;
  }.bind(this));
};

Game.prototype.sendMessage = function(msg) {
  // Send a chat message
  return m.request({
    method: "POST",
    url: "/chatmsg",
    data: { channel: "game:" + this.uuid, msg: msg }
  })
  .then(function(result) {
    // The updated chat comes in via a Firebase notification
  });
};

Game.prototype.sendChatSeenMarker = function() {
  // Send a 'chat message seen' marker to the server
  this.sendMessage("");
  // The user has now seen all chat messages
  this.chatShown = true;
};

Game.prototype.addChatMessage = function(from_userid, msg, ts) {
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

Game.prototype.markChatShown = function() {
  // Note that the user has seen all pending chat messages
  if (!this.chatShown) {
    this.chatShown = true;
    return true;
  }
  return false;
};

Game.prototype.setUserPref = function(pref) {
  // Set a user preference
  return m.request({
    method: "POST",
    url: "/setuserpref",
    data: pref
  })
  .then(function(result) {
    // No response required
  });
};

Game.prototype.placeMove = function(player, co, tiles) {
  // Place an entire move into the tiles dictionary
  var vec = toVector(co);
  var col = vec.col;
  var row = vec.row;
  var nextBlank = false;
  for (var i = 0; i < tiles.length; i++) {
    var tile = tiles[i];
    if (tile == '?') {
      nextBlank = true;
      continue;
    }
    var sq = coord(row, col);
    var letter = tile;
    if (nextBlank)
      tile = '?';
    var tscore = this.tilescore(tile);
    // Place the tile, if it wasn't there already (moves may duplicate tiles that
    // were previously on the board)
    if (!(sq in this.tiles))
      this.tiles[sq] = {
        player: player,
        tile: tile,
        letter: letter,
        score: tscore,
        draggable: false,
        freshtile: false,
        index: 0,
        xchg: false
      };
    col += vec.dx;
    row += vec.dy;
    nextBlank = false;
  }
};

Game.prototype.placeTiles = function() {
  // Make a tile dictionary for the game
  this.tiles = { };
  this.numTileMoves = 0;
  var mlist = this.moves;
  var i, sq;
  for (i = 0; i < mlist.length; i++) {
    var player = mlist[i][0];
    var co = mlist[i][1][0];
    var tiles = mlist[i][1][1];
    var score = mlist[i][1][2];
    // !!! TBD: handle successful challenges
    if (co != "") {
      this.placeMove(player, co, tiles);
      this.numTileMoves++;
    }
  }
  // Mark the opponent's last move
  mlist = this.lastmove;
  if (mlist !== undefined && mlist.length)
    for (i = 0; i < mlist.length; i++) {
      sq = mlist[i][0];
      if (this.tiles[sq] === undefined)
        throw "Tile from lastmove not in square " + sq;
      this.tiles[sq].freshtile = true;
      this.tiles[sq].index = i;
    }
  // Also put the rack tiles into this.tiles
  for (i = 0; i < this.rack.length; i++) {
    sq = 'R' + (i + 1).toString();
    var tile = this.rack[i][0];
    var letter = (tile == '?') ? ' ' : tile;
    var tscore = this.rack[i][1];
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

Game.prototype.moveTile = function(from, to) {
  // Move a tile between cells/slots
  var fromTile = this.tiles[from];
  delete this.tiles[from];
  if (to in this.tiles) {
    // Dropping to an occupied slot in the rack:
    // create space in the rack
    var dest = parseInt(to.slice(1));
    var empty = dest + 1;
    var j;
    // Try to find an empty slot to the right of the drop destination
    while (('R' + empty.toString()) in this.tiles)
      empty++;
    if (empty <= RACK_SIZE) {
      // Found empty slot after the tile:
      // move the intervening tiles to the right
      for (j = empty; j > dest; j--)
        this.tiles['R' + j.toString()] = this.tiles['R' + (j-1).toString()];
    }
    else {
      // No empty slots after the tile: try to find one to the left
      empty = dest - 1;
      while (('R' + empty.toString()) in this.tiles)
        empty--;
      if (empty < 1)
        throw "No place in rack to drop tile";
      for (j = empty; j < dest; j++)
        this.tiles['R' + j.toString()] = this.tiles['R' + (j+1).toString()];
    }
  }
  if (to[0] == 'R' && fromTile.tile == '?')
    // Putting a blank tile back into the rack: erase its meaning
    fromTile.letter = ' ';
  this.tiles[to] = fromTile;
  // Clear error message, if any
  this.currentError = this.currentMessage = null;
  // Update the current word score
  this.updateScore();
};

Game.prototype.attemptMove = function(from, to) {
  if (to == from)
    // No move
    return;
  if (to in this.tiles && to[0] != 'R')
    throw "Square " + to + " occupied";
  if (!(from in this.tiles))
    throw "No tile at " + from;
  var tile = this.tiles[from];
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

Game.prototype.placeBlank = function(letter) {
  // Assign a meaning to a blank tile that is being placed on the board
  if (this.askingForBlank === null)
    return;
  var from = this.askingForBlank.from;
  var to = this.askingForBlank.to;
  // We must assign the tile letter before moving it
  // since moveTile() calls updateScore() which in turn does a /wordcheck
  this.tiles[from].letter = letter;
  this.moveTile(from, to);
  this.askingForBlank = null;
};

Game.prototype.tilesPlaced = function() {
  // Return a list of coordinates of tiles that the user has
  // placed on the board by dragging from the rack
  var r = [];
  for (var sq in this.tiles)
    if (this.tiles.hasOwnProperty(sq) && sq[0] != 'R' && this.tiles[sq].draggable)
      // Found a non-rack tile that is not glued to the board
      r.push(sq);
  return r;
};

Game.prototype.sendMove = function(moves) {
  // Send a move to the server
  this.moveInProgress = true;
  return m.request({
    method: "POST",
    url: "/submitmove",
    data: { moves: moves, mcount: this.moves.length, uuid: this.uuid }
  })
  .then(function(result) {
    this.moveInProgress = false;
    this.update(result);
  }.bind(this))
  .catch(function(e) {
    this.moveInProgress = false;
    this.currentError = "server";
    this.currentMessage = e;
  }.bind(this));
};

Game.prototype.submitMove = function() {
  // Send a tile move to the server
  var t = this.tilesPlaced();
  var moves = [];
  this.selectedSq = null; // Currently selected (blinking) square
  for (var i = 0; i < t.length; i++) {
    var sq = t[i];
    var tile = this.tiles[sq];
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
  var i, sq;
  this.showingDialog = "exchange";
  this.selectedSq = null; // Currently selected (blinking) square
  // Remove the xchg flag from all tiles in the rack
  for (i = 1; i <= RACK_SIZE; i++) {
    sq = "R" + i;
    if (sq in this.tiles)
      this.tiles[sq].xchg = false;
  }
};

Game.prototype.submitResign = function() {
  // Show a resign prompt
  this.showingDialog = "resign";
  this.selectedSq = null; // Currently selected (blinking) square
};

Game.prototype.confirmPass = function(yes) {
  // Handle reply to pass confirmation prompt
  this.showingDialog = null;
  if (yes)
    this.sendMove([ "pass" ]);
};

Game.prototype.confirmChallenge = function(yes) {
  // Handle reply to challenge confirmation prompt
  this.showingDialog = null;
  if (yes)
    this.sendMove([ "chall" ]);
};

Game.prototype.confirmExchange = function(yes) {
  // Handle reply to exchange confirmation prompt
  var i, sq, exch = "";
  this.showingDialog = null;
  for (i = 1; i <= RACK_SIZE; i++) {
    sq = "R" + i;
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

Game.prototype.confirmResign = function(yes) {
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
  var i, rackTileId;
  for (i = 1; i <= RACK_SIZE; i++) {
    rackTileId = "R" + i.toString();
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
  for (i = 1; i <= RACK_SIZE; i++) {
    rackTileId = "R" + i.toString();
    if (array[i-1] === null)
      delete this.tiles[rackTileId];
    else
      this.tiles[rackTileId] = array[i-1];
  }
  this.saveTiles();
};

Game.prototype.saveTiles = function() {
  // Save the current unglued tile configuration to local storage
  // !!! TODO
};

Game.prototype._resetRack = function() {
  // Recall all unglued tiles into the rack
  var t = this.tilesPlaced();
  if (t.length) {
    var i = 1;
    for (var j = 0; j < t.length; j++) {
      while (("R" + i.toString()) in this.tiles)
        i++;
      var sq = "R" + i.toString();
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
      m.request({
        method: "POST",
        url: "/wordcheck",
        data: { word: scoreResult.word, words: scoreResult.words }
      })
      .then(function(result) {
        if (result && result.word == wordToCheck) {
          this.wordGood = result.ok;
          this.wordBad = !result.ok;
        }
      }.bind(this));
    }
  }
};

Game.prototype.wordScore = function(row, col) {
  return parseInt(WORDSCORE[row].charAt(col));
};

Game.prototype.letterScore = function(row, col) {
  return parseInt(LETTERSCORE[row].charAt(col));
};

Game.prototype.tileAt = function(row, col) {
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
  this.tilesPlaced().forEach(function(sq) {
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
  }.bind(this));
  if (numtiles == 0)
    return undefined;
  if (minrow != maxrow && mincol != maxcol)
    // Not a pure horizontal or vertical move
    return undefined;
  var x = mincol, y = minrow;
  var dx = 0, dy = 0;
  if (minrow != maxrow)
    dy = 1; // Vertical
  else
  if (mincol == maxcol && (this.tileAt(minrow - 1, mincol) !== null || this.tileAt(minrow + 1, mincol) !== null))
    // Single tile: if it has tiles above or below, consider this a vertical move
    dy = 1;
  else
    dx = 1; // Horizontal
  // Find the beginning of the word
  while (this.tileAt(y - dy, x - dx) !== null) {
    x -= dx;
    y -= dy;
  }
  var t = null;
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
    if (null === this.tileAt(7, 7))
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
  var t = null;
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

var _hasLocal = null; // Is HTML5 local storage supported by the browser?

function LocalStorage(uuid) {

  function hasLocalStorage() {
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

  if (!hasLocalStorage())
    // No local storage available: return an object with null functions
    return {
      clearTiles: function() { },
      saveTiles: function() { }
    };

  return {
    getLocalTile: function(ix) {
      return localStorage[uuid + ".tile." + ix + ".t"];
    },
    getLocalTileSq: function(ix) {
      return localStorage[uuid + ".tile." + ix + ".sq"];
    },
    setLocalTile: function(ix, t) {
      localStorage[uuid + ".tile." + ix + ".t"] = t;
    },
    setLocalTileSq: function(ix, sq) {
      localStorage[uuid + ".tile." + ix + ".sq"] = sq;
    },
    clearTiles: function() {
      // Clean up local storage when game is over
      try {
        for (var i = 1; i <= RACK_SIZE; i++) {
          localStorage.removeItem(uuid + ".tile." + i + ".sq");
          localStorage.removeItem(uuid + ".tile." + i + ".t");
        }
      }
      catch (e) {
      }
    },
    saveTiles: function() {
      /* Save tile locations in local storage */
      try {
        var i = 1;
        $("div.racktile").each(function() {
          // Ignore the clone created during dragging
          if (!$(this).hasClass("ui-draggable-dragging")) {
            var sq = $(this).parent().attr("id");
            var t = $(this).data("tile");
            if (t !== null && t !== undefined) {
              if (t == '?' && sq[0] != 'R')
                /* Blank tile on the board: add its meaning */
                t += $(this).data("letter");
              this.setLocalTileSq(i, sq);
              this.setLocalTile(i, t);
              i++;
            }
          }
        });
        while (i <= RACK_SIZE) {
           this.setLocalTileSq(i, "");
           this.setLocalTile(i, "");
           i++;
        }
      }
      catch (e) {
      }
    }
  };
}

return Game;

} ());

