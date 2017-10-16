/*

   Netskrafl.js
   Client-side script functions for board.html, the game board page

   Copyright (C) 2015-2017 Miðeind ehf.
   Author: Vilhjalmur Thorsteinsson

   The GNU General Public License, version 3, applies to this software.
   For further information, see https://github.com/vthorsteinsson/Netskrafl

*/

// Constants

var ROWIDS = "ABCDEFGHIJKLMNO";
var BOARD_SIZE = 15;
var RACK_SIZE = 7;
var BAG_TILES_PER_LINE = 19;
var BLANK_TILES_PER_LINE = 6;
var MAX_CHAT_MESSAGES = 250; // Max number of chat messages per game
var LEGAL_LETTERS = "aábdðeéfghiíjklmnoóprstuúvxyýþæö";

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

// Default to the old bag
var TILESCORE = OLD_TILESCORE;

var WORDSCORE = new Array(
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
   "311111131111113");

var LETTERSCORE = new Array(
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
   "111211111112111");

var GAME_OVER = 99; /* Error code corresponding to the Error class in skraflmechanics.py */

var MAX_OVERTIME = 10 * 60.0; /* Maximum overtime before a player loses the game, 10 minutes in seconds */

/* Global variables */

var numMoves = 0, numTileMoves = 0; // Moves in total, vs. moves with tiles actually laid down
var leftTotal = 0, rightTotal = 0; // Accumulated scores - incremented in appendMove()
var newestMove = { }; // The last move made in the game (empty dict if not tile move)
var newestTileMove = { }; // The last tile move made in the game
var gameTime = null, gameTimeBase = null; // Game timing info, i.e. duration and elapsed time
var clockIval = null; // Clock interval timer
var scoreLeft = 0, scoreRight = 0;
var penaltyLeft = 0, penaltyRight = 0; // Current overtime penalty score
var gameOver = false;
var initializing = true; // True while loading initial move list and setting up
var _hasLocal = null; // Is HTML5 local storage supported by the browser?
var _localPrefix = null; // Prefix of local storage for this game
var uiFullscreen = true; // Displaying the full screen UI?


function hasLocalStorage() {
   /* Return true if HTML5 local storage is supported by the browser */
   if (_hasLocal === null)
      try {
         _hasLocal = ('localStorage' in window) &&
            (window.localStorage !== null) &&
            (window.localStorage !== undefined);
         if (_hasLocal)
            _localPrefix = "game." + gameId();
      } catch (e) {
         _hasLocal = false;
      }
   return _hasLocal;
}

function getLocalTile(ix) {
   return localStorage[_localPrefix + ".tile." + ix + ".t"];
}

function getLocalTileSq(ix) {
   return localStorage[_localPrefix + ".tile." + ix + ".sq"];
}

function setLocalTile(ix, t) {
   localStorage[_localPrefix + ".tile." + ix + ".t"] = t;
}

function setLocalTileSq(ix, sq) {
   localStorage[_localPrefix + ".tile." + ix + ".sq"] = sq;
}

function clearTiles() {
   /* Clean up local storage when game is over */
   if(!hasLocalStorage())
      return;
   try {
      for (var i = 1; i <= RACK_SIZE; i++) {
         localStorage.removeItem(_localPrefix + ".tile." + i + ".sq");
         localStorage.removeItem(_localPrefix + ".tile." + i + ".t");
      }
   }
   catch (e) {
   }
}

function saveTiles() {
   /* Save tile locations in local storage */
   if(!hasLocalStorage())
      return;
   try {
      var i = 1;
      $("div.racktile").each(function() {
         // Ignore the clone created during dragging
         if (!$(this).hasClass("ui-draggable-dragging")) {
            var sq = $(this).parent().attr("id");
            var t = $(this).data("tile");
            if (t !== null && t !== undefined) {
               if (t == '?' && sq.charAt(0) != 'R')
                  /* Blank tile on the board: add its meaning */
                  t += $(this).data("letter");
               setLocalTileSq(i, sq);
               setLocalTile(i, t);
               i++;
            }
         }
      });
      while (i <= RACK_SIZE) {
         setLocalTileSq(i, "");
         setLocalTile(i, "");
         i++;
      }
   }
   catch (e) {
   }
}

function arrayEqual(a, b) {
   /* Return true if arrays a and b are equal */
   if (a.length != b.length)
      return false;
   for (var i = 0; i < a.length; i++)
      if (a[i] != b[i])
         return false;
   return true;
}

function restoreTiles() {
   /* Restore tile locations from local storage */
   if (!hasLocalStorage())
      return;
   try {
      /* First check whether the rack matches by comparing sorted arrays */
      var i, sq, t, rackTileId, rackTile;
      var lcs = [];
      for (i = 1; i <= RACK_SIZE; i++) {
         t = getLocalTile(i);
         if ((typeof t === "string") && t.length)
            lcs.push(t.charAt(0));
      }
      if (!lcs.length)
         // Nothing stored, so nothing to restore
         return;
      lcs.sort();
      var rack = [];
      for (i = 1; i <= RACK_SIZE; i++) {
         rackTileId = "R" + i.toString();
         rackTile = document.getElementById(rackTileId);
         if (rackTile && rackTile.firstChild)
            /* There is a tile in this rack slot */
            rack.push($(rackTile.firstChild).data("tile"));
      }
      rack.sort();
      if (!arrayEqual(lcs, rack))
         /* Local storage tiles not identical to current rack: do not restore */
         return;
      /* Same tiles: restore them by moving from the rack if possible */
      /* Start by emptying the rack */
      for (i = 1; i <= RACK_SIZE; i++)
         placeTile("R" + i, "", "", 0);
      var backToRack = [];
      var letter, tile, el;
      for (i = 1; i <= RACK_SIZE; i++) {
         t = getLocalTile(i);
         if ((typeof t === "string") && t.length) {
            sq = getLocalTileSq(i);
            if ((typeof sq !== "string") || !sq.length)
               continue;
            el = document.getElementById(sq);
            if (el && el.firstChild)
               // Already a tile there: push it back to the rack
               backToRack.push(t);
            else {
               // Put this tile into the stored location for it
               tile = t;
               letter = t;
               if (t.charAt(0) == '?') {
                  // Blank tile
                  tile = '?';
                  if (t.length >= 2)
                     // We have info about the meaning of the blank tile
                     letter = t.charAt(1);
               }
               placeTile(sq, tile, letter, TILESCORE[tile]);
               // Do additional stuff to make this look like a proper rack tile
               $("#" + sq).children().eq(0).addClass("racktile").data("tile", tile);
               if (tile == '?' && letter != tile)
                  // Blank tile that has been dragged to the board: include its meaning
                  $("#" + sq).children().eq(0).data("letter", letter);
            }
         }
      }
      // Place any remaining tiles back into the rack at the first available position
      for (i = 0; i < backToRack.length; i++) {
         t = backToRack[i];
         tile = t.charAt(0);
         // We don't need to worry about the meaning of blank tiles here
         sq = firstEmptyRackSlot();
         if (sq !== null)
            placeTile(sq, tile, tile, TILESCORE[tile]);
      }
   }
   catch (e) {
      // Corruption of the local storage should not
      // jeopardize the game script, so we silently catch
      // all exceptions here
   }
}

function coord(row, col) {
   /* Return the co-ordinate string for the given 0-based row and col */
   return ROWIDS.charAt(row) + (col + 1).toString();
}

function toVector(co) {
   /* Convert a co-ordinate string to a 0-based row, col and direction vector */
   var dx = 0, dy = 0;
   var col = 0;
   var row = ROWIDS.indexOf(co.charAt(0));
   if (row >= 0) {
      /* Horizontal move */
      col = parseInt(co.slice(1)) - 1;
      dx = 1;
   }
   else {
      /* Vertical move */
      row = ROWIDS.indexOf(co.charAt(co.length - 1));
      col = parseInt(co) - 1;
      dy = 1;
   }
   return { col: col, row: row, dx: dx, dy: dy };
}

function tileAt(row, col) {
   /* Returns the tile element within a square, or null if none */
   if (row < 0 || col < 0 || row >= BOARD_SIZE || col >= BOARD_SIZE)
      return null;
   var el = document.getElementById(coord(row, col));
   if (!el || !el.firstChild)
      return null;
   /* Avoid a false positive here if the child DIV is the clone being dragged */
   if ($(el.firstChild).hasClass("ui-draggable-dragging"))
      return null;
   return el.firstChild;
}

var reloadInterval = null;

function reloadPage() {
   window.clearInterval(reloadInterval);
   reloadInterval = null;
   window.location.reload(true); // Bypass cache
}

function calcTimeToGo(player) {
   /* Return the time left for a player in a nice MM:SS format */
   var elapsed = gameTime.elapsed[player];
   if (!gameOver && ((numMoves % 2) == player)) {
      // This player's turn: add the local elapsed time
      var now = new Date();
      elapsed += (now.getTime() - gameTimeBase.getTime()) / 1000;
      if (elapsed - gameTime.duration * 60.0 > MAX_OVERTIME) {
         // 10 minutes overtime has passed:
         // The player has lost - do this the brute force way and refresh the page
         // to get the server's final verdict
         reloadInterval = window.setInterval(reloadPage, 500);  // Do this in half a sec
      }
   }
   // The overtime is max 10 minutes - at that point you lose
   var timeToGo = Math.max(gameTime.duration * 60.0 - elapsed, -MAX_OVERTIME);
   var absTime = Math.abs(timeToGo);
   var min = Math.floor(absTime / 60.0);
   var sec = Math.floor(absTime - min * 60.0);
   if (gameOver) {
      // We already got a correct score from the server
      penaltyLeft = 0;
      penaltyRight = 0;
   }
   else
   if (timeToGo < 0.0) {
      // We're into overtime: calculate the score penalty
      if (player === 0)
         penaltyLeft = -10 * Math.floor((min * 60 + sec + 59) / 60);
      else
         penaltyRight = -10 * Math.floor((min * 60 + sec + 59) / 60);
   }
   return (timeToGo < 0.0 ? "-" : "") +
      ("0" + min.toString()).slice(-2) + ":" + ("0" + sec.toString()).slice(-2);
}

function updateScores() {
   /* Display the current score including overtime penalty, if any */
   var displayLeft = Math.max(scoreLeft + penaltyLeft, 0);
   var displayRight = Math.max(scoreRight + penaltyRight, 0);
   $(".scoreleft").text(displayLeft);
   $(".scoreright").text(displayRight);
}

var runningOut0 = false, blinking0 = false;
var runningOut1 = false, blinking1 = false;

function updateClock() {
   /* Show the current remaining time for both players */
   var txt0 = calcTimeToGo(0);
   var txt1 = calcTimeToGo(1);
   $("h3.clockleft").text(txt0);
   $("h3.clockright").text(txt1);
   // Check whether time is running out - and display accordingly
   if (txt0 <= "02:00" && !runningOut0) {
      $("h3.clockleft").addClass("running-out");
      runningOut0 = true;
   }
   if (txt1 <= "02:00" && !runningOut1) {
      $("h3.clockright").addClass("running-out");
      runningOut1 = true;
   }
   var locp = localPlayer();
   // If less than 30 seconds remaining, blink
   if (runningOut0 && txt0 >= "00:00" && txt0 <= "00:30" && locp === 0) {
      $("h3.clockleft").toggleClass("blink");
      blinking0 = true;
   }
   if (runningOut1 && txt1 >= "00:00" && txt1 <= "00:30" && locp === 1) {
      $("h3.clockright").toggleClass("blink");
      blinking1 = true;
   }
   // Remove blinking once we're into overtime
   if (txt0.charAt(0) == "-" && blinking0) {
      $("h3.clockleft").removeClass("blink");
      blinking0 = false;
   }
   if (txt1.charAt(0) == "-" && blinking1) {
      $("h3.clockright").removeClass("blink");
      blinking1 = false;
   }
   if (gameOver || penaltyLeft !== 0 || penaltyRight !== 0)
      // If we are applying an overtime penalty to the scores, update them in real-time
      updateScores();
}

function resetClock(newGameTime) {
   /* Set a new time base after receiving an update from the server */
   gameTime = newGameTime;
   gameTimeBase = new Date();
   updateClock();
   if (gameOver) {
      // Game over: stop updating the clock
      if (clockIval) {
         window.clearInterval(clockIval);
         clockIval = null;
      }
      // Stop blinking, if any
      $("h3.clockleft").removeClass("blink");
      $("h3.clockright").removeClass("blink");
   }
}

function showClock() {
   /* This is a timed game: show the clock stuff */
   $(".clockleft").css("display", "inline-block");
   $(".clockright").css("display", "inline-block");
   $(".clockface").css("display", "block");
   $("div.right-area").addClass("with-clock");
   $("div.chat-area").addClass("with-clock");
   $("div.twoletter-area").addClass("with-clock");
}

function startClock(igt) {
   /* Start the clock ticking - called from initSkrafl() */
   resetClock(igt);
   // Make sure the clock ticks reasonably regularly, once per second
   // According to Nyquist, we need a refresh interval of no more than 1/2 second
   if (!gameOver)
      clockIval = window.setInterval(updateClock, 500);
}

function placeTile(sq, tile, letter, score) {
   /* Place a given tile in a particular square, either on the board or in the rack */
   if (tile.length === 0) {
      /* Erasing tile */
      $("#"+sq).html("");
      return;
   }
   var attr;
   if (sq.charAt(0) == "R") {
      /* Placing a tile into the rack */
      attr = "class='tile racktile'";
      letter = (tile == "?") ? "&nbsp;" : tile;
   }
   else
      /* Normal board tile */
      attr = "class='tile'";
   $("#"+sq).html("<div " + attr + ">" + letter +
      "<div class='letterscore'>" + score + "</div></div>");
   var elem = $("#"+sq).children().eq(0);
   elem.data("score", score);
   if (sq.charAt(0) == "R") {
      /* Store associated data with rack tiles */
      elem.data("tile", tile);
   }
   else
   if (tile == '?') {
      /* Blank tile used as a letter: use different foreground color */
      elem.addClass("blanktile");
   }
}

function removeNewestTileMove() {
   // Successful challenge: retract the tiles placed in the last tile move
   for (var nsq in newestTileMove)
      if (newestTileMove.hasOwnProperty(nsq))
         placeTile(nsq, "", "", 0); // Erase tile
}

function placeMove(player, co, tiles, score) {
   /* Place an entire move on the board, returning a dictionary of the tiles actually added */
   var placed = { };
   if (co !== "") {
      var vec = toVector(co);
      var col = vec.col;
      var row = vec.row;
      var nextBlank = false;
      for (var i = 0; i < tiles.length; i++) {
         var tile = tiles.charAt(i);
         if (tile == '?') {
            nextBlank = true;
            continue;
         }
         var sq = coord(row, col);
         if (tileAt(row, col) === null) {
            /* No tile already in the square: place the new one */
            var letter = tile;
            if (nextBlank)
               tile = '?';
            var tscore = TILESCORE[tile];
            placeTile(sq, tile, letter, tscore);
            placed[sq] = { tile: tile, letter: letter, score: tscore };
         }
         col += vec.dx;
         row += vec.dy;
         nextBlank = false;
      }
      // Remember the last tile move
      newestTileMove = placed;
   }
   else
   if (tiles == "RESP" && score < 0)
      removeNewestTileMove();
   // Remember the last move
   newestMove = placed;
}

function colorOf(player) {
   /* Return the highlight color of tiles for the given player index */
   var lcp = localPlayer();
   if (lcp == -1)
      // Looking at a game between third parties: player 0 is the "local" player by convention
      return player === 0 ? "0" : "1";
   return player == lcp ? "0" : "1";
}

function localTurn() {
   /* Is it this player's turn to move? */
   return (numMoves % 2) == localPlayer();
}

function highlightNewestMove(playerColor) {
   /* Show the newest move on the board in the player's color */
   if (!newestMove)
      // newestMove must be set when the board was initialized
      return;
   for (var nsq in newestMove)
      if (newestMove.hasOwnProperty(nsq)) {
         var tileDiv = $("#"+nsq).children().eq(0);
         if (tileDiv !== null)
            tileDiv.addClass("highlight" + playerColor);
      }
}

var tempTiles = null;

function showBestMove(ev) {
   /* Show a move from the best move list on the board */
   var co = ev.data.coord;
   var tiles = ev.data.tiles;
   var playerColor = ev.data.player;
   var vec = toVector(co);
   var col = vec.col;
   var row = vec.row;
   var nextBlank = false;
   var tileDiv = null;
   var nsq = null;
   if (ev.data.show) {
      /* Clear the list of temporary tiles added */
      tempTiles = { };
      /* Hide the most recent move */
      for (nsq in newestMove)
         if (newestMove.hasOwnProperty(nsq))
            placeTile(nsq, "", "", 0);
      /* Show the score difference */
      var scoreBest = parseInt($(this).find("span.score").eq(0).text());
      var scoreMove = parseInt($("div.score").eq(0).text());
      var scoreDiff = (scoreMove - scoreBest).toString();
      if (scoreMove > scoreBest) {
         scoreDiff = "+" + scoreDiff;
      }
      $("div.scorediff").text(scoreDiff);
      $("div.scorediff").toggleClass("posdiff", scoreMove >= scoreBest);
      $("div.scorediff").css("visibility", "visible");
   }
   for (var i = 0; i < tiles.length; i++) {
      var tile = tiles.charAt(i);
      if (tile == '?') {
         nextBlank = true;
         continue;
      }
      var sq = coord(row, col);
      var letter = tile;
      if (nextBlank)
         tile = '?';
      tileDiv = tileAt(row, col);
      if (tileDiv === null && ev.data.show) {
         /* No tile in the square: add it temporarily & highlight it */
         placeTile(sq, tile, letter, TILESCORE[tile]);
         tempTiles[sq] = true;
         tileDiv = tileAt(row, col);
         $(tileDiv).addClass("highlight" + playerColor);
      }
      else
      if (tileDiv !== null && !ev.data.show && tempTiles[sq])
         /* This tile was added temporarily: remove it */
         placeTile(sq, "", "", 0);
      col += vec.dx;
      row += vec.dy;
      nextBlank = false;
   }
   if (ev.data.show)
      /* Add a highlight to the score */
      $(this).find("span.score").addClass("highlight");
   else {
      /* Remove highlight from score */
      $(this).find("span.score").removeClass("highlight");
      tempTiles = null;
      /* Show and highlight the most recent move again */
      for (nsq in newestMove)
         if (newestMove.hasOwnProperty(nsq))
            placeTile(nsq, newestMove[nsq].tile, newestMove[nsq].letter, newestMove[nsq].score);
      highlightNewestMove(playerColor);
      /* Hide the score difference */
      $("div.scorediff").css("visibility", "hidden");
   }
}

function highlightMove(ev) {
   /* Highlight a move's tiles when hovering over it in the move list */
   if (!uiFullscreen)
      // No need to do this if not on a fullscreen UI,
      // since the board is not visible while hovering on
      // the move list
      return;
   var co = ev.data.coord;
   var tiles = ev.data.tiles;
   var playerColor = ev.data.player;
   var vec = toVector(co);
   var col = vec.col;
   var row = vec.row;
   for (var i = 0; i < tiles.length; i++) {
      var tile = tiles.charAt(i);
      if (tile == '?')
         continue;
      var sq = coord(row, col);
      var tileDiv = $("#"+sq).children().eq(0);
      if (ev.data.show)
         tileDiv.addClass("highlight" + playerColor);
      else
         tileDiv.removeClass("highlight" + playerColor);
      col += vec.dx;
      row += vec.dy;
   }
   if (ev.data.show)
      /* Add a highlight to the score */
      $(this).find("span.score").addClass("highlight");
   else
      /* Remove highlight from score */
      $(this).find("span.score").removeClass("highlight");
}

function lookupWord(ev) {
   /* Look up the word on official word list website */
   if (uiFullscreen)
      // We only do this if displaying the full UI
      // (not the mobile one)
      window.open('http://malid.is/leit/' + ev.data.tiles, 'malid');
}

function appendMove(player, co, tiles, score) {
   /* Add a move to the move history list */
   var wrdclass = "wordmove";
   var rawCoord = co;
   var tileMoveIncrement = 0; // +1 for tile moves, -1 for successful challenges
   if (co === "") {
      /* Not a regular tile move */
      wrdclass = "othermove";
      if (tiles == "PASS") {
         /* Pass move */
         tiles = " Pass ";
         score = "";
      }
      else
      if (tiles.indexOf("EXCH") === 0) {
         /* Exchange move - we don't show the actual tiles exchanged, only their count */
         var numtiles = tiles.slice(5).length;
         tiles = "Skipti um " + numtiles.toString() + (numtiles == 1 ? " staf" : " stafi");
         score = "";
      }
      else
      if (tiles == "RSGN")
         /* Resigned from game */
         tiles = " Gaf viðureign "; // Extra space intentional
      else
      if (tiles == "CHALL") {
         /* Challenge issued */
         tiles = " Véfengdi lögn "; // Extra space intentional
         score = "";
      }
      else
      if (tiles == "RESP") {
         /* Challenge response */
         if (score < 0) {
            tiles = " Óleyfileg lögn "; // Extra space intentional
            tileMoveIncrement = -1; // Subtract one from the actual tile moves on the board
         }
         else
            tiles = " Röng véfenging "; // Extra space intentional
      }
      else
      if (tiles == "TIME") {
         /* Overtime adjustment */
         tiles = " Umframtími "; // Extra spaces intentional
      }
      else
      if (tiles == "OVER") {
         /* Game over */
         tiles = "Viðureign lokið";
         wrdclass = "gameover";
         gameOver = true;
      }
      else {
         /* The rack leave at the end of the game (which is always in lowercase
            and thus cannot be confused with the above abbreviations) */
         wrdclass = "wordmove";
      }
   }
   else {
      // Normal tile move
      co = "(" + co + ")";
      // Note: String.replace() will not work here since there may be two question marks in the string
      tiles = tiles.split("?").join(""); /* !!! TODO: Display wildcard characters differently? */
      tileMoveIncrement = 1;
   }
   /* Update the scores */
   if (player === 0)
      leftTotal = Math.max(leftTotal + score, 0);
   else
      rightTotal = Math.max(rightTotal + score, 0);
   var str;
   var title = (tileMoveIncrement > 0 && !gameIsManual()) ? 'title="Smelltu til að fletta upp" ' : "";
   if (wrdclass == "gameover") {
      str = '<div class="move gameover"><span class="gameovermsg">' + tiles + '</span>' +
         '<span class="statsbutton" onclick="navToReview()">Skoða yfirlit</span></div>';
      // Show a congratulatory message if the local player is the winner
      var winner = -2; // -1 is reserved
      if (leftTotal > rightTotal)
         winner = 0;
      else
      if (leftTotal < rightTotal)
         winner = 1;
      if (localPlayer() == winner) {
         $("#congrats").css("visibility", "visible");
         if (!initializing || gameIsZombie()) {
            // The local player is winning in real time or opening the
            // game for the first time after winning it in absentia:
            // Play fanfare sound if audio enabled
            var youWin = document.getElementById("you-win");
            if (youWin)
               youWin.play();
         }
      }
      // Show the Facebook share button if the game is over
      $("div.fb-share").css("visibility", "visible");
      // Clear local storage, if any
      clearTiles();
   }
   else
   if (player === 0) {
      /* Left side player */
      str = '<div ' + title + 'class="move leftmove">' +
         '<span class="total">' + leftTotal + '</span>' +
         '<span class="score">' + score + '</span>' + 
         '<span class="' + wrdclass + '"><i>' + tiles + '</i> ' +
         co + '</span>' +
         '</div>';
   }
   else {
      /* Right side player */
      str = '<div ' + title + 'class="move rightmove">' +
         '<span class="' + wrdclass + '">' + co +
         ' <i>' + tiles + '</i></span>' +
         '<span class="score">' + score + '</span>' + 
         '<span class="total">' + rightTotal + '</span>' +
         '</div>';
   }
   var movelist = $("div.movelist");
   movelist.append(str);
   if (wrdclass != "gameover") {
      var m = movelist.children().last();
      var playerColor = "0";
      var lcp = localPlayer();
      if (player === lcp || (lcp == -1 && player === 0))
         m.addClass("humangrad" + (player === 0 ? "_left" : "_right")); /* Local player */
      else {
         m.addClass("autoplayergrad" + (player === 0 ? "_left" : "_right")); /* Remote player */
         playerColor = "1";
      }
      if (tileMoveIncrement > 0) {
         /* Tile move: Register a hover event handler to highlight it on the board */
         m.on("mouseover",
            { coord: rawCoord, tiles: tiles, score: score, player: playerColor, show: true },
            highlightMove
         );
         m.on("mouseout",
            { coord: rawCoord, tiles: tiles, score: score, player: playerColor, show: false },
            highlightMove
         );
         if (!gameIsManual())
            // Clicking on a word in the word list looks up the word on the official word list website
            // (This is not available in a manual challenge game)
            m.on("click",
               { tiles: tiles },
               lookupWord
            );
      }
   }
   /* Manage the scrolling of the move list */
   var lastchild = $("div.movelist .move").last();
   var firstchild = $("div.movelist .move").first();
   var topoffset = lastchild.position().top -
      firstchild.position().top +
      lastchild.outerHeight();
   var height = movelist.height();
   if (topoffset >= height)
      movelist.scrollTop(topoffset - height);
   /* Count the moves */
   numMoves += 1;
   numTileMoves += tileMoveIncrement; // Can be -1 for successful challenges
}

function appendBestMove(player, co, tiles, score) {
   /* Add a move to the best move list */
   var rawCoord = co;
   var rawTiles = tiles;
   var str;
   co = "(" + co + ")";
   // Note: String.replace will not work here since string may contain multiple '?' instances
   tiles = tiles.split("?").join(""); /* !!! TODO: Display wildcard characters differently? */
   if (player === 0) {
      /* Left side player */
      str = '<div class="leftmove">' +
         '<span class="score">' + score + '</span>' +
         '<span class="wordmove"><i>' + tiles + '</i> ' +
         co + '</span>' +
         '</div>';
   }
   else {
      /* Right side player */
      str = '<div class="rightmove">' +
         '<span class="wordmove">' + co +
         ' <i>' + tiles + '</i></span>' +
         '<span class="score">' + score + '</span>' + 
         '</div>';
   }
   var movelist = $("div.movelist");
   movelist.append(str);
   var m = movelist.children().last();
   var playerColor = "0";
   if (player === localPlayer())
      m.addClass("humangrad" + (player === 0 ? "_left" : "_right")); /* Local player */
   else {
      m.addClass("autoplayergrad" + (player === 0 ? "_left" : "_right")); /* Remote player */
      playerColor = "1";
   }
   /* Register a hover event handler to highlight this move */
   m.on("mouseover",
      { coord: rawCoord, tiles: rawTiles, score: score, player: playerColor, show: true },
      showBestMove
   );
   m.on("mouseout",
      { coord: rawCoord, tiles: rawTiles, score: score, player: playerColor, show: false },
      showBestMove
   );
}

function appendBestHeader(moveNumber, co, tiles, score) {
   /* Add a header on the best move list */
   var wrdclass = "wordmove";
   var dispText;
   if (co.length > 0) {
      // Regular move
      co = " (" + co + ")";
      dispText = "<i>" + tiles.split("?").join("") + "</i>"; /* !!! TODO: Display wildcard characters differently? */
   }
   else {
      /* Not a regular tile move */
      wrdclass = "othermove";
      if (tiles == "PASS")
         /* Pass move */
         dispText = "Pass";
      else
      if (tiles.indexOf("EXCH") === 0) {
         /* Exchange move - we don't show the actual tiles exchanged, only their count */
         var numtiles = tiles.slice(5).length;
         dispText = "Skipti um " + numtiles.toString() + (numtiles == 1 ? " staf" : " stafi");
      }
      else
      if (tiles == "RSGN")
         /* Resigned from game */
         dispText = "Gaf viðureign";
      else
      if (tiles == "CHALL")
         /* Challenge issued */
         dispText = "Véfengdi lögn";
      else
      if (tiles == "RESP") {
         /* Challenge response */
         if (score < 0)
            dispText = "Lögn óleyfileg";
         else
            dispText = "Röng véfenging";
      }
      else
      if (tiles == "OVER") {
         /* Game over */
         dispText = "Leik lokið";
         wrdclass = "gameover";
      }
      else {
         /* The rack leave at the end of the game (which is always in lowercase
            and thus cannot be confused with the above abbreviations) */
         wrdclass = "wordmove";
         dispText = tiles;
      }
   }
   var str = '<div class="reviewhdr">' +
      '<span class="movenumber">#' + moveNumber.toString() + '</span>' +
      '<span class="' + wrdclass + '">' + dispText + co + '</span>' +
      // '<span class="score">' + score + '</span>' +
      '</div>';
   $("div.movelist").append(str);
}

function blankFlasher() {
   // Flash a frame around the target square for a blank tile
   var target = $("#blank-dialog").data("param").target;
   if (target !== undefined)
      $(target).toggleClass("over");
}

function keyBlankDialog(ev, combo) {
   /* Handle a key press from Mousetrap: close the blank dialog with the indicated letter chosen */
   var letter = combo;
   if (letter == "esc")
      letter = "";
   else
   if (letter.indexOf("shift+") === 0)
      letter = letter.charAt(6);
   closeBlankDialog({ data: letter });
}

function openBlankDialog(elDragged, target) {
   /* Show the modal dialog to prompt for the meaning of a blank tile */
   // Hide the blank in its original position
   $(elDragged).css("visibility", "hidden");
   // Flash a frame around the target square
   var iv = window.setInterval(blankFlasher, 500);
   // Show the dialog
   $("#blank-dialog")
      .data("param", { eld: elDragged, target: target, ival: iv })
      .css("visibility", "visible");
   // Reset the esc key to make it close the dialog
   Mousetrap.bind('esc', keyBlankDialog);
   // Bind all normal keys to make them select a letter and close the dialog
   for (var i = 0; i < LEGAL_LETTERS.length; i++) {
      Mousetrap.bind(LEGAL_LETTERS[i], keyBlankDialog);
      Mousetrap.bind("shift+" + LEGAL_LETTERS[i], keyBlankDialog);
   }
}

function closeBlankDialog(ev) {
   /* The blank tile dialog is being closed: place the tile as instructed */
   // ev.data contains the tile selected, or "" if none
   var letter = (!ev) ? "" : ev.data;
   var param = $("#blank-dialog").data("param");
   // The DIV for the blank tile being dragged
   var eld = param.eld;
   // The target TD for the tile
   var target = param.target;
   // Stop flashing
   window.clearInterval(param.ival);
   // Remove the highlight of the target square, if any
   $(target).removeClass("over");
   $(eld).css("visibility", "visible");
   if (letter !== "") {
      // Place the blank tile with the indicated meaning on the board
      $(eld).data("letter", letter);
      $(eld).addClass("blanktile");
      eld.childNodes[0].nodeValue = letter;
      eld.parentNode.removeChild(eld);
      target.appendChild(eld);
   }
   // Hide the dialog
   $("#blank-dialog")
      .data("param", null)
      .css("visibility", "hidden");
   // Make sure that all yellow frames are removed
   $("#blank-meaning").find("td").removeClass("over");
   // Rebind the Esc key to the resetRack() function
   Mousetrap.bind('esc', resetRack);
   // Unbind the alphabetic letters
   for (var i = 0; i < LEGAL_LETTERS.length; i++) {
      Mousetrap.unbind(LEGAL_LETTERS[i]);
      Mousetrap.unbind("shift+" + LEGAL_LETTERS[i]);
   }
   saveTiles();
   updateButtonState();
}

function prepareBlankDialog() {
   /* Construct the blank tile dialog DOM to make it ready for display */
   var bt = $("#blank-meaning");
   bt.html("");
   // Create tile TDs and DIVs for all legal letters
   var len = LEGAL_LETTERS.length;
   var ix = 0;
   while (len > 0) {
      /* Rows */
      var str = "<tr>";
      /* Columns: max BLANK_TILES_PER_LINE tiles per row */
      for (var i = 0; i < BLANK_TILES_PER_LINE && len > 0; i++) {
         var tile = LEGAL_LETTERS[ix++];
         str += "<td><div class='blank-choice'>" + tile + "</div></td>";
         len--;
      }
      str += "</tr>";
      bt.append(str);
   }
   /* Add a click handler to each tile, calling closeBlankDialog with the
      associated letter as an event parameter */
   $("div.blank-choice").addClass("tile").addClass("racktile").each(function() {
      $(this).click($(this).text(), closeBlankDialog);
   });
   // Show a yellow frame around the letter under the mouse pointer
   bt.find("td").hover(
      function() { $(this).addClass("over"); },
      function() { $(this).removeClass("over"); }
   );
   // Make the close button close the dialog
   $("#blank-close").click("", closeBlankDialog);
}

var elementDragged = null; /* The element being dragged with the mouse */
var tileSelected = null; /* The selected (single-clicked) tile */
var showingDialog = false; /* Is a modal dialog banner being shown? */
var exchangeAllowed = true; /* Is an exchange move allowed? */
var challengeAllowed = false; /* Is a challenge allowed? */
var lastChallenge = false; /* Last tile move on the board, pending challenge or pass? */

function moveSelectedTile(sq) {
   // Move the tileSelected to the target square
   if (sq.firstChild === null) {
      moveTile(tileSelected, sq);
      selectTile(null);
   }
}

function selOver(sq) {
   if (sq.firstChild === null)
      // Legitimate drop target
      $(sq).addClass("sel");
}

function selOut(sq) {
   $(sq).removeClass("sel");
}

function selectTile(elem) {
   if (elem === tileSelected) {
      if (elem === null)
         // Nothing was selected - nothing to do
         return;
      // Re-clicking on an already selected tile:
      // remove the selection
      $(elem).removeClass("sel");
      tileSelected = null;
   }
   else {
      // Changing the selection
      if (tileSelected !== null)
         $(tileSelected).removeClass("sel");
      tileSelected = elem;
      if (tileSelected !== null)
         $(tileSelected).addClass("sel");
   }
   if (tileSelected !== null) {
      // We have a selected tile: show a red square around
      // drop targets for it
      $("table.board td.ui-droppable").hover(
         function() { selOver(this); },
         function() { selOut(this); }
      ).click(
         function() { moveSelectedTile(this); }
      );
   }
   else {
      // No selected tile: no hover
      $("table.board td.ui-droppable").off("mouseenter mouseleave click").removeClass("sel");
   }
}

function handleDragstart(e, ui) {
   // Remove selection, if any
   selectTile(null);
   // Remove the blinking sel class from the drag clone, if there
   $("div.ui-draggable-dragging").removeClass("sel");
   // The dragstart target is the DIV inside a TD
   elementDragged = e.target;
   // The original tile, still shown while dragging
   elementDragged.style.opacity = "0.5";
}

function handleDragend(e, ui) {
   if (elementDragged !== null)
      elementDragged.style.opacity = null; // "1.0";
   elementDragged = null;
}

function handleDropover(e, ui) {
   if (e.target.id.charAt(0) == 'R' || e.target.firstChild === null)
     /* Rack square or empty square: can drop. Add yellow outline highlight to square */
     this.classList.add("over");
}

function handleDropleave(e, ui) {
   /* Can drop here: remove outline highlight from square */
   this.classList.remove("over");
}

function initDraggable(elem) {
   /* The DIVs inside the board TDs are draggable */
   $(elem).draggable(
      {
         opacity : 0.9,
         helper : "clone",
         cursor : "pointer",
         zIndex : 100,
         start : handleDragstart,
         stop : handleDragend
      }
   );
   $(elem).click(function(ev) { selectTile(this); ev.stopPropagation(); });
}

function removeDraggable(elem) {
   /* The DIVs inside the board TDs are draggable */
   $(elem).draggable("destroy");
   if (elem === tileSelected)
      selectTile(null);
   $(elem).off("click");
}

function initRackDraggable(state) {
   /* Make the seven tiles in the rack draggable or not, depending on
      the state parameter */
   $("div.racktile").each(function() {
      if (!$(this).hasClass("ui-draggable-dragging")) {
         var sq = $(this).parent().attr("id");
         var rackTile = document.getElementById(sq);
         if (rackTile && rackTile.firstChild)
            /* There is a tile in this rack slot */
            if (state)
               initDraggable(rackTile.firstChild);
            else
               removeDraggable(rackTile.firstChild);
      }
   });
}

function firstEmptyRackSlot() {
   /* Returns the identifier of the first available rack slot or null if none */
   for (var i = 1; i <= RACK_SIZE; i++) {
      var rackTileId = "R" + i.toString();
      var rackTile = document.getElementById(rackTileId);
      if (rackTile && !rackTile.firstChild)
         return rackTileId;
   }
   return null; // No empty slot in rack
}

function initDropTarget(elem) {
   /* Prepare a board square or a rack slot to accept drops */
   if (elem !== null)
      elem.droppable(
         {
            drop : handleDrop,
            over : handleDropover,
            out : handleDropleave
         }
      );
}

function initDropTargets() {
   /* All board squares are drop targets */
   var x, y, sq;
   for (x = 0; x < BOARD_SIZE; x++)
      for (y = 0; y < BOARD_SIZE; y++) {
         sq = $("#" + coord(y, x));
         initDropTarget(sq);
      }
   /* Make the rack a drop target as well */
   for (x = 1; x <= RACK_SIZE; x++) {
      sq = $("#R" + x.toString());
      initDropTarget(sq);
   }
   /* Make the background a drop target */
   initDropTarget($("#container"));
}

function moveTile(src, target) {
   // src is a DIV; target is a TD
   var ok = true;
   var parentid = src.parentNode.id;
   if (parentid.charAt(0) == 'R') {
      /* Dropping from the rack */
      var t = $(src).data("tile");
      var dropToRack = (target.id.charAt(0) == 'R');
      if (!dropToRack && t == '?') {
         /* Dropping a blank tile on to the board: we need to ask for its meaning */
         openBlankDialog(src, target);
         ok = false; // The drop will be completed later, when the blank dialog is closed
      }
   }
   if (ok) {
      /* Complete the drop */
      src.parentNode.removeChild(src);
      target.appendChild(src);
      if (target.id.charAt(0) == 'R') {
         /* Dropping into the rack */
         if ($(src).data("tile") == '?') {
            /* Dropping a blank tile: erase its letter value, if any */
            $(src).data("letter", ' ');
            src.childNodes[0].nodeValue = "\xa0"; // Non-breaking space, i.e. &nbsp;
         }
      }
      // Save this state in local storage,
      // to be restored when coming back to this game
      saveTiles();
   }
   updateButtonState();
}

function handleDrop(e, ui) {
   /* A tile is being dropped on a square on the board or into the rack */
   e.target.classList.remove("over");
   /* Save the elementDragged value as it will be set to null in handleDragend() */
   var eld = elementDragged;
   if (eld === null)
      return;
   var i, rslot;
   eld.style.opacity = null; // "1.0";
   if (e.target.id == "container") {
      // Dropping to the background container:
      // shuffle things around so it looks like we are dropping to the first empty rack slot
      rslot = null;
      for (i = 1; i <= RACK_SIZE; i++) {
         rslot = document.getElementById("R" + i.toString());
         if (!rslot.firstChild)
            /* Empty slot in the rack */
            break;
         rslot = null;
      }
      if (!rslot)
         return; // Shouldn't really happen
      e.target = rslot;
   }
   var dropToRack = (e.target.id.charAt(0) == 'R');
   if (dropToRack && e.target.firstChild !== null) {
      /* Dropping into an already occupied rack slot: shuffle the rack tiles to make room */
      var ix = parseInt(e.target.id.slice(1));
      rslot = null;
      i = 0;
      /* Try to find an empty slot to the right */
      for (i = ix + 1; i <= RACK_SIZE; i++) {
         rslot = document.getElementById("R" + i.toString());
         if (!rslot.firstChild)
            /* Empty slot in the rack */
            break;
         rslot = null;
      }
      if (rslot === null) {
         /* Not found: Try an empty slot to the left */
         for (i = ix - 1; i >= 1; i--) {
            rslot = document.getElementById("R" + i.toString());
            if (!rslot.firstChild)
               /* Empty slot in the rack */
               break;
            rslot = null;
         }
      }
      if (rslot === null) {
         /* No empty slot: must be internal shuffle in the rack */
         rslot = eld.parentNode;
         i = parseInt(rslot.id.slice(1));
      }
      if (rslot !== null) {
         var j, src, tile;
         if (i > ix)
            /* Found empty slot: shift rack tiles to the right to make room */
            for (j = i; j > ix; j--) {
               src = document.getElementById("R" + (j - 1).toString());
               tile = src.firstChild;
               src.removeChild(tile);
               rslot.appendChild(tile);
               rslot = src;
            }
         else
         if (i < ix)
            /* Found empty slot: shift rack tiles to the left to make room */
            for (j = i; j < ix; j++) {
               src = document.getElementById("R" + (j + 1).toString());
               tile = src.firstChild;
               src.removeChild(tile);
               rslot.appendChild(tile);
               rslot = src;
            }
      }
   }
   if (e.target.firstChild === null) {
      /* Looks like a legitimate drop */
      moveTile(eld, e.target);
   }
   elementDragged = null;
}

/* The word that is being checked for validity with a server query */
var wordToCheck = "";

function wordGoodOrBad(flagGood, flagBad) {
   /* Flag whether the word being laid down is good or bad (or neither when we don't know) */
   $("div.word-check").toggleClass("word-good", flagGood);
   $("div.word-check").toggleClass("word-bad", flagBad);
   if (gameIsManual())
      // For a manual wordcheck game, always use a neutral blue color for the score
      $("div.score").toggleClass("manual", true);
   else
      // Otherwise, show a green score if the word is good
      $("div.score").toggleClass("word-good", flagGood);
   if (flagGood) {
      // Show a 50+ point word with a special color
      if (parseInt($("div.score").text()) >= 50)
         $("div.score").addClass("word-great");
   }
}

function showWordCheck(json) {
   /* The server has returned our word check result: show it */
   if (json && json.word == wordToCheck)
      /* Nothing significant has changed since we sent the request */
      wordGoodOrBad(json.ok, !json.ok);
}

function updateButtonState() {
   /* Refresh state of action buttons depending on availability */
   var tilesPlaced = gameOver ? 0 : findCovers().length;
   var showResign = false;
   var showExchange = false;
   var showPass = false;
   var showRecall = false;
   var showScramble = false;
   var showMove = false;
   var showChallenge = false;
   var showChallengeInfo = false;
   if ((!gameOver) && localTurn()) {
      /* The local player's turn */
      if (lastChallenge) {
         // The last tile move is on the board. It can only be passed or challenged.
         showChallenge = true;
         showPass = true;
         showChallengeInfo = true;
      }
      else {
         showMove = (tilesPlaced !== 0);
         showExchange = (tilesPlaced === 0);
         showPass = (tilesPlaced === 0);
         showResign = (tilesPlaced === 0);
         showChallenge = (tilesPlaced === 0) && gameIsManual() && challengeAllowed;
      }
      /* Disable or enable buttons according to current state */
      $("div.submitmove").toggleClass("disabled",
         tilesPlaced === 0 || showingDialog);
      $("div.submitexchange").toggleClass("disabled",
         tilesPlaced !== 0 || showingDialog || !exchangeAllowed);
      $("div.submitpass").toggleClass("disabled",
         (tilesPlaced !== 0 && !lastChallenge) || showingDialog);
      $("div.challenge").toggleClass("disabled",
         (tilesPlaced !== 0 && !lastChallenge) || showingDialog);
      $("div.submitresign").toggleClass("disabled", showingDialog);
      $("div.recallbtn").toggleClass("disabled", showingDialog);
      $("div.scramblebtn").toggleClass("disabled", showingDialog);
      $("#left-to-move").css("display", localPlayer() === 0 ? "inline" : "none");
      $("#right-to-move").css("display", localPlayer() === 1 ? "inline" : "none");
      $("div.opp-turn").css("visibility", "hidden");
      // Indicate that it's this player's turn in the window/tab title
      document.title = "\u25B6 Netskrafl";
   }
   else {
      /* The other player's turn */
      $("#left-to-move").css("display", localPlayer() === 1 ? "inline" : "none");
      $("#right-to-move").css("display", localPlayer() === 0 ? "inline" : "none");
      if (gameOver)
         $("div.opp-turn").css("visibility", "hidden");
      else
         $("div.opp-turn").css("visibility", "visible");
      // Reset to normal window/tab title
      document.title = "Netskrafl";
   }
   /* Show the last challenge reminder as appropriate */
   $("div.chall-info").css("visibility", showChallengeInfo ? "visible" : "hidden");
   /* Erase previous error message, if any */
   clearError();
   /* Calculate tentative score */
   $("div.score").removeClass("word-good").removeClass("word-great");
   if (tilesPlaced === 0 || lastChallenge) {
      $("div.score").text("").css("visibility", "hidden");
      wordToCheck = "";
      wordGoodOrBad(false, false);
      if (!gameOver)
         showScramble = true;
   }
   else {
      var scoreResult = calcScore();
      if (scoreResult === undefined) {
         $("div.score").text("?").css("visibility", "visible");
         wordToCheck = "";
         wordGoodOrBad(false, false);
      }
      else {
         $("div.score").text(scoreResult.score.toString()).css("visibility", "visible");
         /* Start a word check request to the server, checking the
            word laid down and all cross words */
         wordToCheck = scoreResult.word;
         wordGoodOrBad(false, false);
         if (!gameIsManual())
            serverQuery("/wordcheck",
               { word: wordToCheck, words: scoreResult.words },
               showWordCheck
            );
      }
      showRecall = true;
   }
   if (showChallengeInfo)
      showScramble = false;
   $("div.submitmove").toggleClass("hidden", !showMove);
   $("div.submitexchange").css("display", showExchange ? "block" : "none");
   $("div.submitpass").css("display", showPass ? "block" : "none");
   $("div.submitresign").css("display", showResign ? "block" : "none");
   $("div.challenge").css("display", showChallenge ? "block" : "none");
   $("div.recallbtn").css("display", showRecall ? "block" : "none");
   $("div.scramblebtn").css("display", showScramble ? "block" : "none");
}

function findCovers() {
   /* Return a list of the newly laid tiles on the board */
   var moves = [];
   $("div.tile").each(function() {
      var sq = $(this).parent().attr("id");
      var t = $(this).data("tile");
      if (t !== null && t !== undefined && sq.charAt(0) != "R") {
         if (t == '?')
            /* Blank tile: add its meaning */
            t += $(this).data("letter");
         moves.push(sq + "=" + t);
      }
   });
   return moves;      
}

function wordScore(row, col) {
   return parseInt(WORDSCORE[row].charAt(col));
}

function letterScore(row, col) {
   return parseInt(LETTERSCORE[row].charAt(col));
}

function calcScore() {
   /* Calculate the score for the tiles that have been laid on the board in the current move */
   var score = 0, crossScore = 0;
   var wsc = 1;
   var minrow = BOARD_SIZE, mincol = BOARD_SIZE;
   var maxrow = 0, maxcol = 0;
   var numtiles = 0, numcrosses = 0;
   var word = "";
   var words = [];
   $("div.tile").each(function() {
      var sq = $(this).parent().attr("id");
      var t = $(this).data("tile");
      if (t !== null && t !== undefined && sq.charAt(0) != "R") {
         /* Tile on the board */
         var row = ROWIDS.indexOf(sq.charAt(0));
         var col = parseInt(sq.slice(1)) - 1;
         var sc = $(this).data("score") * letterScore(row, col);
         numtiles++;
         wsc *= wordScore(row, col);
         if (row < minrow)
            minrow = row;
         if (col < mincol)
            mincol = col;
         if (row > maxrow)
            maxrow = row;
         if (col > maxcol)
            maxcol = col;
         score += sc;
      }
   });
   if (minrow != maxrow && mincol != maxcol)
      /* Not a pure horizontal or vertical move */
      return undefined;
   var x = mincol, y = minrow;
   var dx = 0, dy = 0;
   if (minrow != maxrow)
      dy = 1; /* Vertical */
   else
   if (mincol == maxcol && (tileAt(minrow - 1, mincol) !== null || tileAt(minrow + 1, mincol) !== null))
      /* Single tile: if it has tiles above or below, consider this a vertical move */
      dy = 1;
   else
      dx = 1; /* Horizontal */
   /* Find the beginning of the word */
   while (tileAt(y - dy, x - dx) !== null) {
      x -= dx;
      y -= dy;
   }
   var t = null;
   /* Find the end of the word */
   while ((t = tileAt(y, x)) !== null) {
      if ($(t).hasClass("racktile")) {
         // Add score for cross words
         var csc = calcCrossScore(y, x, 1 - dy, 1 - dx);
         if (csc.score >= 0) {
            /* There was a cross word there (it can score 0 if blank) */
            crossScore += csc.score;
            numcrosses++;
            words.push(csc.word);
         }
      }
      else {
         /* This is a tile that was previously on the board */
         score += $(t).data("score");
         numcrosses++;
      }
      /* Accumulate the word being formed */
      word += t.childNodes[0].nodeValue;
      x += dx;
      y += dy;
   }
   if (numTileMoves === 0) {
      // First move that actually lays down tiles must go through center square
      if (null === tileAt(7, 7))
         return undefined;
   }
   else
   if (!numcrosses)
      // Not first move, and not linked with any word on the board
      return undefined;
   /* Check whether word is consecutive
      (which it is not if there is an empty square before the last tile) */
   if (dx && (x <= maxcol))
      return undefined;
   if (dy && (y <= maxrow))
      return undefined;
   words.push(word);
   return { word: word, words: words,
      score: score * wsc + crossScore + (numtiles == RACK_SIZE ? 50 : 0) };
}

function calcCrossScore(oy, ox, dy, dx) {
   /* Calculate the score contribution of a cross word */
   var score = 0;
   var hascross = false;
   var x = ox, y = oy;
   var word = "";
   /* Find the beginning of the word */
   while (tileAt(y - dy, x - dx) !== null) {
      x -= dx;
      y -= dy;
   }
   var t = null;
   /* Find the end of the word */
   while ((t = tileAt(y, x)) !== null) {
      var sc = $(t).data("score");
      if (x == ox && y == oy)
         sc *= letterScore(y, x);
      else
         hascross = true;
      word += t.childNodes[0].nodeValue;
      score += sc;
      x += dx;
      y += dy;
   }
   if (!hascross)
      return { score: -1, word: "" };
   return { score: score * wordScore(oy, ox), word: word };
}

function resetRack(ev) {
   /* Reset the rack, i.e. recall all tiles. Bound to the Esc key. */
   if (showingDialog)
      return false;
   var rslot = 1;
   $("div.tile").each(function() {
      var sq = $(this).parent().attr("id");
      var t = $(this).data("tile");
      var score = $(this).data("score");
      if (t !== null && t !== undefined && sq.charAt(0) != "R") {
         placeTile(sq, "", "", 0);
         /* Find an empty slot in the rack for the tile */
         for (; rslot <= RACK_SIZE; rslot++) {
            var rackTileId = "R" + rslot.toString();
            var rackTile = document.getElementById(rackTileId);
            if (rackTile && rackTile.firstChild === null) {
               /* Found empty rack slot: put this there */
               placeTile(rackTileId, t, t, score);
               initDraggable(rackTile.firstChild);
               rslot++;
               break;
            }
         }
      }
   });
   saveTiles();
   updateButtonState();
   return true;
}

function rescrambleRack(ev) {
   /* Reorder the rack randomly. Bound to the Backspace key. */
   if (showingDialog)
      return false;
   resetRack(ev);
   var array = [];
   var i, rackTileId;
   for (i = 1; i <= RACK_SIZE; i++) {
      rackTileId = "R" + i.toString();
      array.push(document.getElementById(rackTileId).firstChild);
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
      var elem = document.getElementById(rackTileId);
      if (elem.firstChild !== null)
         elem.removeChild(elem.firstChild);
      if (array[i-1] !== null)
         elem.appendChild(array[i-1]);
   }
   saveTiles();
   return false; // Stop default behavior
}

function updateBag(bag) {
   /* Update the bag display in the lower right corner */
   var bagC = $(".bag-content");
   bagC.html("");
   var lenbag = bag.length;
   var ix = 0;
   // If 7 or fewer unseen tiles, the bag is empty and they're all in the opponent's
   // rack; display the tiles in the opponent's color
   if (lenbag <= RACK_SIZE)
      bagC
         .toggleClass("new", false)
         .toggleClass("empty", true);
   else
   if (gameUsesNewBag())
      // Indicate visually that we're using the new bag
      bagC.toggleClass("new", true);
   while (lenbag > 0) {
      /* Rows */
      var str = "<tr>";
      /* Columns: max BAG_TILES_PER_LINE tiles per row */
      for (var i = 0; i < BAG_TILES_PER_LINE && lenbag > 0; i++) {
         var tile = bag[ix++];
         if (tile == "?")
            /* Show wildcard tiles '?' as blanks */
            tile = "&nbsp;";
         str += "<td>" + tile + "</td>";
         lenbag--;
      }
      str += "</tr>";
      bagC.append(str);
   }
}

function showError(msgId, msg) {
   /* Display error in error bar */
   $("div.error").css("visibility", "visible").find("p").css("display", "none");
   var errorP = $("div.error").find("#err_" + msgId);
   errorP.css("display", "inline");
   if (msg !== undefined)
      // Fill in word if provided in error message
      errorP.find("span.errword").text(msg);
   $("div.submitmove").toggleClass("error-shown", true);
}

function clearError() {
   /* Clear error from error bar */
   $("div.error").css("visibility", "hidden");
   $("div.submitmove").toggleClass("error-shown", false);
}

function _updateState(json, preserveTiles) {
   /* Work through the returned JSON object to update the
      board, the rack, the scores and the move history */
   if (json.result === 0 || json.result == GAME_OVER) {
      /* Successful move */
      /* Reinitialize the rack - we show it even if the game is over */
      var i = 0;
      var score;
      var placed;
      var anyPlaced;
      if (preserveTiles && json.result == GAME_OVER) {
         // The user may have placed tiles on the board: force them back
         // into the rack and make the rack non-draggable
         resetRack();
         initRackDraggable(false);
      }
      if (!preserveTiles || json.succ_chall) {
         // Destructive fetch or successful challenge: reset the rack
         for (; i < json.rack.length; i++)
            placeTile("R" + (i + 1).toString(), /* Coordinate */
               json.rack[i][0], /* Tile */
               json.rack[i][0], /* Letter */
               json.rack[i][1]); /* Score */
         /* Clear the rest of the rack */
         for (; i < RACK_SIZE; i++)
            placeTile("R" + (i + 1).toString(), "", "", 0);
         if (json.result === 0)
            /* The rack is only draggable if the game is still ongoing */
            initRackDraggable(true);
      }
      if (!preserveTiles) {
         /* Glue the laid-down tiles to the board */
         placed = { };
         anyPlaced = false;
         $("div.tile").each(function() {
            var sq = $(this).parent().attr("id");
            var t = $(this).data("tile");
            score = $(this).data("score");
            if (t !== null && t !== undefined && sq.charAt(0) != "R") {
               var letter = t;
               if (letter == '?') {
                  /* Blank tile: get its meaning */
                  letter = $(this).data("letter");
                  if (letter === null || letter === undefined)
                     letter = t;
               }
               placeTile(sq, t, letter, score);
               placed[sq] = { tile: t, letter: letter, score: score };
               anyPlaced = true;
            }
         });
         if (anyPlaced)
            newestTileMove = placed;
      }
      /* Remove highlight from previous move, if any */
      $("div.highlight1").removeClass("highlight1");
      $("div.highlight0").removeClass("highlight0");
      /* Add the new tiles laid down in response */
      if (json.lastmove !== undefined) {
         var delay = 0;
         placed = { };
         anyPlaced = false;
         for (i = 0; i < json.lastmove.length; i++) {
            var sq = json.lastmove[i][0];
            if (preserveTiles && document.getElementById(sq).firstChild) {
               // The incoming move is overwriting a tile from the local user:
               // send it to the rack
               var m = $("#"+sq).children().eq(0);
               var t = m.data("tile");
               score = m.data("score");
               // Find an empty slot in the rack
               var rsq = firstEmptyRackSlot();
               if (rsq) { // Should always be non-null
                  placeTile(rsq, t, t, score);
                  // Make the rack tile draggable
                  initDraggable(document.getElementById(rsq).firstChild);
               }
            }
            var tile = json.lastmove[i][1];
            var letter = json.lastmove[i][2];
            score = json.lastmove[i][3];
            placeTile(sq, tile, letter, score);
            placed[sq] = { tile: tile, letter: letter, score: score };
            anyPlaced = true;
            // Show the new tiles with a progressive fade-in effect
            $("#"+sq).children().eq(0).addClass("freshtile")
               .hide().delay(delay).fadeIn();
            delay += 200; // 200 ms between tiles
         }
         if (anyPlaced)
            newestTileMove = placed;
      }
      /* Update the scores */
      scoreLeft = json.scores[0];
      scoreRight = json.scores[1];
      /* Update the move list */
      if (json.newmoves !== undefined) {
         for (i = 0; i < json.newmoves.length; i++) {
            var player = json.newmoves[i][0];
            var co = json.newmoves[i][1][0];
            var tiles = json.newmoves[i][1][1];
            score = json.newmoves[i][1][2];
            appendMove(player, co, tiles, score);
            if (co === "" && tiles == "RESP" && score < 0)
               // Successful challenge: remove the tiles originally placed
               removeNewestTileMove();
         }
      }
      /* Update the bag */
      if (json.bag !== undefined)
         updateBag(json.bag);
      /* See if an exchange move is still allowed */
      if (json.xchg !== undefined)
         exchangeAllowed = json.xchg;
      /* See if a challenge is allowed */
      if (json.chall !== undefined)
         challengeAllowed = json.chall;
      /* Are we in a last challenge state? */
      if (json.last_chall !== undefined)
         lastChallenge = json.last_chall;
      /* Save the new tile state */
      saveTiles();
      /* Enable and disable buttons as required */
      updateButtonState();
      if (json.result == GAME_OVER) {
         /* Game over: disable Pass, Exchange and Resign buttons */
         $("div.submitpass").toggleClass("disabled", true);
         $("div.submitresign").toggleClass("disabled", true);
         $("div.submitexchange").toggleClass("disabled", true);
         /* Hide Move button and display New Game button */
         $("div.submitmove").toggleClass("hidden", true);
         $("div.submitnewgame").css("display", "inline");
         gameOver = true;
      }
   }
   else
      showError(json.result.toString(), json.msg);
   if (json.time_info !== undefined)
      // New timing information from the server: reset and update the clock
      resetClock(json.time_info);
   // Update the scores display after we have timing info
   updateScores();
}

function updateState(json) {
   /* Normal move submit: update the state without preserving
      tiles that may have been placed experimentally on the board */
   _updateState(json, false);
}

function updateStateGently(json) {
   /* Handle an incoming move: update the state while trying to
      preserve tiles that the user may have been placing experimentally on the board */
   _updateState(json, true);
}

function submitMove(btn) {
   /* The Move button has been clicked: send a regular move to the backend */
   if (!$(btn).hasClass("disabled"))
      sendMove('move');
}

function confirmExchange(yes) {
   /* The user has either confirmed or cancelled the exchange */
   $("div.exchange").css("visibility", "hidden");
   showingDialog = false;
   updateButtonState();
   /* Take the rack out of exchange mode */
   var exch = "";
   for (var i = 1; i <= RACK_SIZE; i++) {
      var rackTileId = "#R" + i.toString();
      var rackTile = $(rackTileId).children().eq(0);
      if (rackTile) {
         /* There is a tile in this rack slot */
         if (rackTile.hasClass("xchgsel")) {
            exch += rackTile.data("tile");
            rackTile.removeClass("xchgsel");
         }
         /* Stop listening to clicks */
         rackTile.removeClass("xchg").off("click.xchg");
      }
   }
   initRackDraggable(true);
   if (yes && exch.length > 0) {
      // The user wants to exchange tiles: submit an exchange move
      sendMove('exch=' + exch);
   }
}

function toggleExchange(e) {
   /* Toggles the exchange state of a tile */
   $(this).toggleClass("xchgsel");
}

function submitExchange(btn) {
   /* The user has clicked the exchange button: show exchange banner */
   if (!$(btn).hasClass("disabled")) {
      $("div.exchange").css("visibility", "visible");
      showingDialog = true;
      updateButtonState();
      initRackDraggable(false);
      /* Disable all other actions while panel is shown */
      /* Put the rack in exchange mode */
      for (var i = 1; i <= RACK_SIZE; i++) {
         var rackTileId = "#R" + i.toString();
         var rackTile = $(rackTileId).children().eq(0);
         if (rackTile)
            /* There is a tile in this rack slot: mark it as
               exchangeable and attack a click handler to it */
            rackTile.addClass("xchg").on("click.xchg", toggleExchange);
      }
   }
}

function clearDialog() {
   /* Erase any dialogs that may be showing */
   $("div.resign").css("visibility", "hidden");
   $("div.exchange").css("visibility", "hidden");
   $("div.chall").css("visibility", "hidden");
   $("div.pass").css("visibility", "hidden");
   $("div.pass-last").css("visibility", "hidden");
   showingDialog = false;
   initRackDraggable(true);
   updateButtonState();
}

function confirmResign(yes) {
   /* The user has either confirmed or cancelled the resignation */
   $("div.resign").css("visibility", "hidden");
   showingDialog = false;
   initRackDraggable(true);
   updateButtonState();
   if (yes)
      sendMove('rsgn');
}

function submitResign(btn) {
   /* The user has clicked the resign button: show resignation banner */
   if (!$(btn).hasClass("disabled")) {
      $("div.resign").css("visibility", "visible");
      showingDialog = true;
      initRackDraggable(false);
      /* Disable all other actions while panel is shown */
      updateButtonState();
   }
}

function confirmChallenge(yes) {
   /* The user has either confirmed or cancelled a challenge */
   $("div.chall").css("visibility", "hidden");
   showingDialog = false;
   initRackDraggable(true);
   updateButtonState();
   if (yes)
      sendMove('chall');
}

function submitChallenge(btn) {
   /* The user has clicked the challenge button */
   if (!$(btn).hasClass("disabled")) {
      $("div.chall").css("visibility", "visible");
      showingDialog = true;
      initRackDraggable(false);
      /* Disable all other actions while panel is shown */
      updateButtonState();
   }
}

function confirmPass(yes) {
   /* The user has either confirmed or cancelled the pass move */
   $("div.pass").css("visibility", "hidden");
   $("div.pass-last").css("visibility", "hidden");
   showingDialog = false;
   initRackDraggable(true);
   updateButtonState();
   if (yes)
      sendMove('pass');
}

function submitPass(btn) {
   /* The user has clicked the pass button: show confirmation banner */
   if (!$(btn).hasClass("disabled")) {
      $(lastChallenge ? "div.pass-last" : "div.pass").css("visibility", "visible");
      showingDialog = true;
      initRackDraggable(false);
      /* Disable all other actions while panel is shown */
      updateButtonState();
   }
}

function setStat(name, json, digits, value) {
   var txt = value;
   if (txt === undefined)
      txt = json[name];
   if (txt === undefined)
      return;
   if (digits !== undefined && digits > 0)
      txt = txt.toFixed(digits).replace(".", ","); // Convert decimal point to comma
   $("#" + name).text(txt);
}

function updateStats(json) {
   /* Display statistics from a server query result encoded in JSON */
   if (!json || json.result === undefined)
      return;
   if (json.result !== 0 && json.result != GAME_OVER)
      /* Probably out of sync or login required */
      /* !!! TBD: Add error reporting here */
      return;
   setStat("gamestart", json);
   setStat("gameend", json);
   /* Statistics for player 0 (left player) */
   setStat("moves0", json);
   setStat("bingoes0", json);
   setStat("tiles0", json);
   setStat("blanks0", json);
   setStat("letterscore0", json);
   setStat("average0", json, 2);
   setStat("multiple0", json, 2);
   setStat("cleantotal0", json);
   setStat("remaining0", json);
   setStat("overtime0", json);
   setStat("wrongchall0", json);
   setStat("bingopoints0", json, 0, json.bingoes0 * 50);
   setStat("avgmove0", json, 2);
   setStat("total0", json, 0, json.scores[0]);
   setStat("ratio0", json, 1);
   /* Statistics for player 1 (right player) */
   setStat("moves1", json);
   setStat("bingoes1", json);
   setStat("tiles1", json);
   setStat("blanks1", json);
   setStat("letterscore1", json);
   setStat("average1", json, 2);
   setStat("multiple1", json, 2);
   setStat("cleantotal1", json);
   setStat("remaining1", json);
   setStat("overtime1", json);
   setStat("wrongchall1", json);
   setStat("bingopoints1", json, 0, json.bingoes1 * 50);
   setStat("avgmove1", json, 2);
   setStat("total1", json, 0, json.scores[1]);
   setStat("ratio1", json, 1);
}

function showStats(gameId) {
   $("div.gamestats").css("visibility", "visible");
   /* Get the statistics from the server */
   serverQuery("/gamestats", { game: gameId }, updateStats);
}

function hideStats() {
   $("div.gamestats").css("visibility", "hidden");
}

var submitInProgress = false;

function moveComplete(xhr, status) {
   /* Called when a move has been submitted, regardless of success or failure */
   $("div.waitmove").css("display", "none");
   submitInProgress = false;
}

function serverError(xhr, status, errorThrown) {
   /* The server threw an error back at us (probably 5XX): inform the user */
   showError("server");
}

function sendMove(movetype) {
   /* Send a move to the back-end server using Ajax */
   if (submitInProgress)
      /* Avoid re-entrancy */
      return;
   var moves = [];
   if (movetype === null || movetype == 'move') {
      moves = findCovers();
   }
   else
   if (movetype == 'pass') {
      /* Remove any tiles that have already been placed on the board */
      $("div.tile").each(function() {
         var sq = $(this).parent().attr("id");
         var t = $(this).data("tile");
         if (t !== null && t !== undefined && sq.charAt(0) != "R") {
            placeTile(sq, "", "", 0);
         }
      });
      moves.push("pass");
   }
   else
   if (movetype.indexOf('exch=') === 0) {
      /* Exchange move */
      moves.push(movetype);
   }
   else
   if (movetype == 'rsgn') {
      /* Resigning from game */
      moves.push("rsgn");
   }
   else
   if (movetype == 'chall') {
      /* Challenging last move */
      moves.push("chall");
   }

   /* Be sure to remove the halo from the submit button */
   $("div.submitmove").removeClass("over");
   $("div.challenge").removeClass("over");
   /* Erase previous error message, if any */
   clearError();
   /* Freshly laid tiles are no longer fresh */
   $("div.freshtile").removeClass("freshtile");
   if (moves.length === 0)
      /* Nothing to submit */
      return;
   /* Show a temporary animated GIF while the Ajax call is being processed */
   submitInProgress = true;
   /* Show an animated GIF while waiting for the server to respond */
   $("div.waitmove").css("display", "block");
   /* Talk to the game server using jQuery/Ajax */
   serverQuery("/submitmove",
      {
         moves: moves,
         // Send a move count to ensure that the client and the server are in sync
         mcount: numMoves,
         // Send the game's UUID
         uuid: gameId()
      },
      updateState, moveComplete, serverError
   );
}

function closeHelpPanel() {
   /* Close the board color help panel and set a user preference to not display it again */
   $("div.board-help").css("display", "none");
   serverQuery("/setuserpref",
      {
         beginner: false
      }
   );
}

function forceResign() {
   /* The game is overdue and the waiting user wants to force the opponent to resign */
   $("#force-resign").css("display", "none");
   serverQuery("/forceresign",
      {
         game: gameId(),
         // Send a move count to ensure that the client and the server are in sync
         mcount: numMoves
      }
   );
   // We trust that the Channel API will return a new client state to us
}

// Have we loaded this game's chat channel from the server?
var chatLoaded = false;
var numChatMessages = 0;
// Timestamp of the last message added to the chat window
var dtLastMsg = null;

function populateChat(json) {
   // Populate the chat window with the existing conversation for this game
   $("#chat-area").html("");
   numChatMessages = 0;
   dtLastMsg = null;
   if (json.messages === undefined)
      // Something went wrong
      return;
   var player_index = localPlayer();
   var i = 0;
   for (; i < json.messages.length; i++) {
      var m = json.messages[i];
      var p = player_index;
      if (m.from_userid != userId())
         // The message is from the remote user
         p = 1 - p;
      showChatMsg(p, m.msg, m.ts);
   }
}

function loadChat() {
   // Load this game's chat channel from the server
   chatLoaded = true; // Prevent race condition
   serverQuery("/chatload",
      {
         channel: "game:" + gameId()
      },
      populateChat
   );
}

var gamesLoading = false;

function populateGames(json) {
   // Populate the list of pending games
   gamesLoading = false;
   $("div.games").html("");
   if (!json || json.result === undefined)
      return;
   if (json.result !== 0)
      /* Probably out of sync or login required */
      /* !!! TBD: Add error reporting here */
      return;
   var numGames = json.gamelist.length;
   var numMyTurns = 0;
   for (var i = 0; i < numGames; i++) {
      var item = json.gamelist[i];
      if (item.uuid == gameId())
         continue; // Don't show this game
      if (!item.my_turn && !item.zombie)
         continue; // Only show pending games
      var fullname = escapeHtml(item.fullname);
      var opp = escapeHtml(item.opp);
      if (item.oppid === null)
         // Mark robots with a cog icon
         opp = "<span class='glyphicon glyphicon-cog'></span>&nbsp;" + opp;
      var winLose = item.sc0 < item.sc1 ? " losing" : "";
      var title = "Staðan er " + item.sc0 + ":" + item.sc1;
      var tileCount = "<div class='tilecount trans'><div class='tc" +
         winLose + "' style='width:" +
         item.tile_count.toString() + "%'>" + opp + "</div></div>";
      // Add the game-timed class if the game is a timed game.
      // These will not be displayed in the mobile UI.
      var cls = "games-item" + (item.timed ? " game-timed" : "");
      var str = "<div class='" + cls + "' title='" + title + "'>" +
         "<a href='" + item.url + "'>" +
         "<div class='at-top-left'>" +
         "<div class='tilecount'><div class='oc'>" + opp + "</div></div>" +
         "</div>" +
         "<div class='at-top-left'>" + tileCount + "</div>" +
         "</a></div>";
      $("div.games").append(str);
      numMyTurns++;
   }
   // Show a red flag if there are pending games
   // !!! TODO: implement this properly with a listening channel
   // $("#tab-games").toggleClass("alert", numMyTurns !== 0);
}

function loadGames() {
   // Load list of pending games from the server
   if (gamesLoading)
      return; // Avoid race conditions
   gamesLoading = true;
   serverQuery("/gamelist",
      { zombie : false }, // We don't need zombie games, so omit them
      populateGames
   );
}

function _selectTab(tabSel) {
   // The tab-board button is only visible and clickable when on a
   // small-format (mobile) screen
   $("div.board-area").css("z-index", tabSel == "tab-board" ? "4" : "1");
   $("#tab-board").toggleClass("selected", tabSel == "tab-board");
   $("div.movelist").css("z-index", tabSel == "tab-movelist" ? "4" : "1");
   $("#tab-movelist").toggleClass("selected", tabSel == "tab-movelist");
   $("div.twoletter").css("z-index", tabSel == "tab-twoletter" ? "4" : "1");
   $("#tab-twoletter").toggleClass("selected", tabSel == "tab-twoletter");
   $("div.games").css("z-index", tabSel == "tab-games" ? "4" : "1");
   $("#tab-games").toggleClass("selected", tabSel == "tab-games");
   $("div.chat").css("z-index", tabSel == "tab-chat" ? "4" : "1");
   $("#tab-chat").toggleClass("selected", tabSel == "tab-chat");
   if (tabSel == "tab-chat") {
      // Selecting the chat tab
      // Remove the alert, if any
      var hadUnseen = $("#tab-chat").hasClass("alert");
      if (hadUnseen)
         $("#tab-chat").removeClass("alert");
      // Check whether the chat conversation needs loading
      if (!chatLoaded)
         loadChat();
      if (hadUnseen)
         // Indicate that we've now seen previously unseen messages
         sendChatSeenMarker();
      // Focus on the text input field
      $("#msg").focus();
   }
   else
   if (tabSel == "tab-games") {
      // Selecting the games tab: load the pending games
      loadGames();
   }
}

function selectTab(ev) {
   /* A right-side tab has been selected: bring it to the foreground */
   var tabSel = $(this).attr("id");
   _selectTab(tabSel);
}

function selectBoardTab() {
   /* Select the board tab, bringing it to the foreground */
   _selectTab("tab-board");
}

function selectMovelistTab() {
   /* Select the move list tab, bringing it to the foreground */
   _selectTab("tab-movelist");
}

function sendChatSeenMarker() {
   /* Send a marker to the server indicating that we've seen chat messages to this point */
   serverQuery("/chatmsg",
      {
         channel: "game:" + gameId(),
         msg: "" // Special indicator
      }
   );
}

function sendChatMsg() {
   /* Send a chat message that has been entered in the chat text input box */
   var chatMsg = $("#msg").val().trim();
   if (chatMsg.length)
      // Send chat message to server
      serverQuery("/chatmsg",
         {
            channel: "game:" + gameId(),
            msg: chatMsg
         }
      );
   $("#msg").val("").focus();
}

function handleChatEnter(ev) {
   /* Handle the Enter key when pressed in the chat message text field */
   if (ev.keyCode == 13) {
      ev.preventDefault();
      sendChatMsg();
   }
}

function decodeTimestamp(ts) {
   // Parse and split an ISO timestamp string, formatted as YYYY-MM-DD HH:MM:SS
   return {
      year: parseInt(ts.substr(0, 4)),
      month: parseInt(ts.substr(5, 2)),
      day: parseInt(ts.substr(8, 2)),
      hour: parseInt(ts.substr(11, 2)),
      minute: parseInt(ts.substr(14, 2)),
      second: parseInt(ts.substr(17, 2))
   };
}

function dateFromTimestamp(ts) {
   // Create a JavaScript millisecond-based representation of an ISO timestamp
   var dcTs = decodeTimestamp(ts);
   return Date.UTC(dcTs.year, dcTs.month - 1, dcTs.day,
      dcTs.hour, dcTs.minute, dcTs.second);
}

function timeDiff(dtFrom, dtTo) {
   // Return the difference between two JavaScript time points, in seconds
   return Math.round((dtTo - dtFrom) / 1000.0);
}

function showChatMsg(player_index, msg, ts) {
   /* Show a newly arrived chat message. It may be coming from the
      current player herself or from the opponent */
   var chatArea = $("#chat-area");
   var escMsg = escapeHtml(msg);
   escMsg = replaceEmoticons(escMsg);
   var str = "<div class='chat-msg " +
      (player_index === 0 ? "left " : "right ") +
      (player_index == localPlayer() ? "local" : "remote") +
      "'>" + escMsg + "</div>";
   // Decode the ISO format timestamp we got from the server
   var dtTs = dateFromTimestamp(ts);
   if (dtLastMsg === null || timeDiff(dtLastMsg, dtTs) >= 5 * 60) {
      // If 5 minutes or longer interval between messages,
      // insert a time
      var ONE_DAY = 24 * 60 * 60 * 1000; // 24 hours expressed in milliseconds
      var dtNow = new Date().getTime();
      var dtToday = dtNow - dtNow % ONE_DAY; // Start of today (00:00 UTC)
      var dtYesterday = dtToday - ONE_DAY; // Start of yesterday
      var strTs;
      if (dtTs < dtYesterday)
         // Older than today or yesterday: Show full timestamp YYYY-MM-DD HH:MM
         strTs = ts.slice(0, -3);
      else
      if (dtTs < dtToday)
         // Yesterday
         strTs = "Í gær " + ts.substr(11, 5);
      else
         // Today
         strTs = ts.substr(11, 5);
      chatArea.append("<div class='chat-ts'>" + strTs + "</div>");
   }
   chatArea.append(str);
   numChatMessages++;
   dtLastMsg = dtTs;
   if (numChatMessages >= MAX_CHAT_MESSAGES)
      // Disable tne entry field once we've hit the maximum number of chat messages
      $("#msg").prop("disabled", true);
   /* Manage the scrolling of the chat message list */
   var lastchild = $("#chat-area .chat-msg").last(); // Last always a chat-msg
   var firstchild = $("#chat-area .chat-ts").first(); // First always a chat-ts
   var topoffset = lastchild.position().top -
      firstchild.position().top +
      lastchild.outerHeight();
   var height = chatArea.height();
   if (topoffset >= height)
      chatArea.scrollTop(topoffset - height);
}

function markChatMsg() {
   // If the chat tab is not visible (selected), put an alert on it
   // to indicate that a new chat message has arrived
   if (!$("#tab-chat").hasClass("selected")) {
      $("#tab-chat").toggleClass("alert", true);
      // Play audio, if present
      var newMsg = document.getElementById("new-msg");
      if (newMsg)
         // Note that playing media outside user-invoked event handlers does not work on iOS.
         // That is a 'feature' introduced and documented by Apple.
         newMsg.play();
      // Return false to indicate that the message has not been seen yet
      return false;
   }
   // Return true to indicate that the message has been seen
   return true;
}

function switchTwoLetter() {
   // Switch the two-letter help panel from sorting by 1st to the 2nd letter or vice versa
   var switchFrom = $(this).attr("id");
   $("#two-1").css("visibility", switchFrom == "two-1" ? "hidden" : "visible");
   $("#two-2").css("visibility", switchFrom == "two-2" ? "hidden" : "visible");
}

function handleChatMessage(json) {
   // Handle an incoming chat message
   var player_index = localPlayer();
   if (json.from_userid != userId()) {
      // The message is from the remote user
      player_index = 1 - player_index;
      // Put an alert on the chat tab if it is not selected
      if (markChatMsg()) {
         // The message was seen: inform the server
         sendChatSeenMarker();
      }
   }
   if (chatLoaded)
      showChatMsg(player_index, json.msg, json.ts);
}

function handleMoveMessage(json) {
   // Handle an incoming opponent move
   // json contains an entire client state update, as a after submitMove()
   updateStateGently(json); // Try to preserve tiles that the user may have placed on the board
   // Play audio, if present
   var yourTurn = document.getElementById("your-turn");
   if (yourTurn)
      // Note that playing media outside user-invoked event handlers does not work on iOS.
      // That is a 'feature' introduced and documented by Apple.
      yourTurn.play();
   if (gameOver) {
      // The game is now over and the player has seen it happen:
      // let the server know so it can remove the game from the zombie list
      serverQuery("gameover", { game: gameId(), player: userId() });
   }
}

function handleUserMessage(json) {
   // Handle an incoming user update
   // Presently not used
}

function _showUserInfo(oppInfo) {
    showUserInfo(oppInfo.nick, oppInfo.fullname, oppInfo.userid);
}

function lookAtPlayer() {
   // Click on a player identifier: open user preferences or track record dialog
   var playerId = $(this).attr("id");
   var playerIndex = (playerId == "player-0" ? 0 : 1);
   if (playerIndex == localPlayer())
      // Clicking on the player's own identifier opens the user preferences
      navToUserprefs();
   else {
      // Show information about the opponent
      _showUserInfo(opponentInfo());
   }
}

function mediaMinWidth667(mql) {
   if (mql.matches) {
      // Take action when min-width exceeds 667
      // (usually because of rotation from portrait to landscape)
      // The board tab is not visible, so the movelist is default
      selectMovelistTab();
      // Cancel any pending dialog
      if (showingDialog)
         clearDialog();
      else
         // Recall any tiles from the board into the rack
         // Note: if a dialog is showing, we know that no tiles are on the board
         resetRack();
   }
   else {
      // min-width is below 667
      // (usually because of rotation from landscape to portrait)
      // Make sure the board tab is selected
      selectBoardTab();
   }
}

function mediaMinWidth768(mql) {
   if (mql.matches) {
      // Take action when min-width exceeds 768
      uiFullscreen = true;
      $("div.heading").off("click");
      // Enable clicking on player identifier buttons
      $("div.player-btn").click(lookAtPlayer);
      // Remove pull-to-refresh disabling hack, if present
      preventPullToRefresh(false);
   }
   else {
      uiFullscreen = false;
      // Make header a click target
      $("div.heading").click(function(e) { window.location.href = "/"; });
      // Disable clicking on player identifier buttons
      $("div.player-btn").off("click");
      // Disable pull-to-refresh on mobile
      preventPullToRefresh(true);
   }
}

function initMediaListener() {
   // Install listener functions for media changes
   var mql;
   mql = window.matchMedia("(min-width: 667px)");
   if (mql) {
      mediaMinWidth667(mql);
      mql.addListener(mediaMinWidth667);
   }
   mql = window.matchMedia("(min-width: 768px)");
   if (mql) {
      mediaMinWidth768(mql);
      mql.addListener(mediaMinWidth768);
   }
}

function initFirebaseListener(token) {
   // Sign into Firebase with the token passed from the server
   loginFirebase(token);
   // Listen to Firebase events on the /game/[gameId]/[userId] path
   var basepath = 'game/' + gameId() + "/" + userId() + "/";
   // New moves
   attachFirebaseListener(basepath + "move", handleMoveMessage);
   // New chat messages
   attachFirebaseListener(basepath + "chat", handleChatMessage);
   // Listen to Firebase events on the /user/[userId] path
   // attachFirebaseListener('user/' + userId(), handleUserMessage);
}

function initSkrafl(jQuery) {
   /* Called when the page is displayed or refreshed */

   // Initialize the game timing information (duration, elapsed time)
   var igt = initialGameTime();

   if (igt.duration > 0)
      // This is a timed game: move things around and show the clock
      showClock();

   if (gameUsesNewBag())
      // Switch tile scores to the new bag
      TILESCORE = NEW_TILESCORE;

   placeTiles();
   initMoveList(); // Sets gameOver to true if the game is over
   if (!gameOver) {
      // Restore previous tile positions, if saved
      restoreTiles();
      // Prepare drag-and-drop
      initRackDraggable(true);
      initDropTargets();
   }
   initBag();
   if (localPlayer() === 1) {
      $("h3.playerright").addClass("humancolor");
      $("h3.playerleft").addClass("autoplayercolor");
   }
   else {
      // This is the default color scheme if looking at games by third parties
      $("h3.playerleft").addClass("humancolor");
      $("h3.playerright").addClass("autoplayercolor");
   }
   if (gameIsFairplay())
      // Display fair play indicator
      $("div.fairplay").css("display", "block");
   updateButtonState();

   // Prepare the dialog box that asks for the meaning of a blank tile
   prepareBlankDialog();

   /* Bind Esc key to a function to reset the rack */
   Mousetrap.bind('esc', resetRack);
   /* Bind Backspace key to a function to rescramble the rack */
   Mousetrap.bind('backspace', rescrambleRack);
   /* Bind pinch gesture to a function to reset the rack */
   /* $('body').bind('pinchclose', resetRack); */

   // Bind a handler to the close icon on the board color help panel
   $("div.board-help-close span").click(closeHelpPanel);

   /* Enable the close button in the user info dialog */
   $("#usr-info-close").click(hideUserInfo);

   /* Enable clicking on the favorite star icon in the user info dialog */
   $("div.usr-info-fav").click(favUserInfo);

   /* Initialize versus toggle in user info dialog */
   $("span.versus-cat > span").each(function() {
      var data = $(this).attr('id');
      $(this).click(data, toggleVersus);
   });

   // Initialize the stats toggler
   initToggle("#stats-toggler", false);
   $("#stats-toggler").click(toggleStats);

   // Prepare the right-side tabs
   $("div.right-tab").click(selectTab);

   // Two letter help area switch
   $("div.twoletter-area").click(switchTwoLetter);

   // Chat message send button
   $("#chat-send").click(sendChatMsg);
   $("#msg").keypress(13, handleChatEnter);

   // Facebook share button
   $("div.fb-share").click(fbShare);

   initMediaListener(); // Initiate listening to media change events

   lateInit();

   if (igt.duration > 0)
      startClock(igt);

   // Done with the initialization phase
   initializing = false;
}

