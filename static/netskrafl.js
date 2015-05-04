/*

   Netskrafl.js
   Client-side script for board.html, the game board page

   Author: Vilhjalmur Thorsteinsson, 2015

*/

/* Constants */

var ROWIDS = "ABCDEFGHIJKLMNO";
var BOARD_SIZE = 15;
var RACK_SIZE = 7;
var BAG_SIZE = 104; // Number of tiles in bag at start of game
var BAG_TILES_PER_LINE = 19;
var BLANK_TILES_PER_LINE = 6;
var MAX_CHAT_MESSAGES = 250; // Max number of chat messages per game
var LEGAL_LETTERS = "aábdðeéfghiíjklmnoóprstuúvxyýþæö";

var TILESCORE = {
   'a': 1, 'á': 4, 'b': 6, 'd': 4, 'ð': 2, 'e': 1, 'é': 6, 'f': 3, 'g': 2,
   'h': 3, 'i': 1, 'í': 4, 'j': 5, 'k': 2, 'l': 2, 'm': 2, 'n': 1, 'o': 3,
   'ó': 6, 'p': 8, 'r': 1, 's': 1, 't': 1, 'u': 1, 'ú': 8, 'v': 3, 'x': 10,
   'y': 7, 'ý': 9, 'þ': 4, 'æ': 5, 'ö': 7, '?': 0
};

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
var newestMove = null; // The tiles placed in the newest move (used in move review)
var gameTime = null, gameTimeBase = null; // Game timing info, i.e. duration and elapsed time
var clockIval = null; // Clock interval timer
var scoreLeft = 0, scoreRight = 0;
var penaltyLeft = 0, penaltyRight = 0; // Current overtime penalty score
var gameOver = false;
var initializing = true; // True while loading initial move list and setting up
var _hasLocal = null; // Is HTML5 local storage supported by the browser?
var _localPrefix = null; // Prefix of local storage for this game

var entityMap = {
   "&": "&amp;",
   "<": "&lt;",
   ">": "&gt;",
   '"': '&quot;',
   "'": '&#39;',
   "/": '&#x2F;'
};

function escapeHtml(string) {
   /* Utility function to properly encode a string into HTML */
   return String(string).replace(/[&<>"'\/]/g, function (s) {
      return entityMap[s];
   });
}

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

function nullFunc(json) {
   /* Null placeholder function to use for Ajax queries that don't need a success func */
}

function nullCompleteFunc(xhr, status) {
   /* Null placeholder function for Ajax completion */
}

function errFunc(xhr, status, errorThrown) {
   /* Default error handling function for Ajax communications */
   // alert("Villa í netsamskiptum");
   console.log("Error: " + errorThrown);
   console.log("Status: " + status);
   console.dir(xhr);
}

function serverQuery(requestUrl, jsonData, successFunc, completeFunc, errorFunc) {
   /* Wraps a simple, standard Ajax request to the server */
   $.ajax({
      // The URL for the request
      url: requestUrl,

      // The data to send
      data: jsonData,

      // Whether this is a POST or GET request
      type: "POST",

      // The type of data we expect back
      dataType : "json",

      cache: false,

      // Code to run if the request succeeds;
      // the response is passed to the function
      success: (!successFunc) ? nullFunc : successFunc,

      // Code to run if the request fails; the raw request and
      // status codes are passed to the function
      error: (!errorFunc) ? errFunc : errorFunc,

      // code to run regardless of success or failure
      complete: (!completeFunc) ? nullCompleteFunc : completeFunc
   });
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

function reloadPage() {
   /* Reload this page from the server */
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
         window.setInterval(reloadPage, 500); // Do this in half a sec
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

function placeMove(player, co, tiles) {
   /* Place an entire move on the board, returning a dictionary of the tiles actually added */
   var vec = toVector(co);
   var col = vec.col;
   var row = vec.row;
   var nextBlank = false;
   var placed = { };
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
         var score = TILESCORE[tile];
         placeTile(sq, tile, letter, score);
         placed[sq] = { tile: tile, letter: letter, score:score };
      }
      col += vec.dx;
      row += vec.dy;
      nextBlank = false;
   }
   return placed;
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
   /* Look up the word on the official word list website */
   window.open('http://bin.arnastofnun.is/leit/?q=' + ev.data.tiles +
      '&ordmyndir=on', 'bin');
}

function appendMove(player, co, tiles, score) {
   /* Add a move to the move history list */
   var wrdclass = "wordmove";
   var rawCoord = co;
   var tileMove = false;
   if (co === "") {
      /* Not a regular tile move */
      wrdclass = "othermove";
      if (tiles == "PASS")
         /* Pass move */
         tiles = "Pass";
      else
      if (tiles.indexOf("EXCH") === 0) {
         /* Exchange move - we don't show the actual tiles exchanged, only their count */
         var numtiles = tiles.slice(5).length;
         tiles = "Skipti um " + numtiles.toString() + (numtiles == 1 ? " staf" : " stafi");
      }
      else
      if (tiles == "RSGN")
         /* Resigned from game */
         tiles = " Gaf leikinn"; // Extra space intentional
      else
      if (tiles == "TIME") {
         /* Overtime adjustment */
         tiles = " Umframtími "; // Extra spaces intentional
      }
      else
      if (tiles == "OVER") {
         /* Game over */
         tiles = "Leik lokið";
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
      co = "(" + co + ")";
      // Note: String.replace() will not work here since there may be two question marks in the string
      tiles = tiles.split("?").join(""); /* !!! TODO: Display wildcard characters differently? */
      tileMove = true;
   }
   /* Update the scores */
   if (player === 0)
      leftTotal = Math.max(leftTotal + score, 0);
   else
      rightTotal = Math.max(rightTotal + score, 0);
   var str;
   var title = tileMove ? 'title="Smelltu til að fletta upp" ' : "";
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
      if (tileMove) {
         /* Register a hover event handler to highlight this move */
         m.on("mouseover",
            { coord: rawCoord, tiles: tiles, score: score, player: playerColor, show: true },
            highlightMove
         );
         m.on("mouseout",
            { coord: rawCoord, tiles: tiles, score: score, player: playerColor, show: false },
            highlightMove
         );
         // Clicking on a word in the word list looks up the word on the official word list website
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
   if (tileMove)
      numTileMoves += 1;
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
         dispText = "Gaf leikinn";
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
var showingDialog = false; /* Is a modal dialog banner being shown? */
var exchangeAllowed = true; /* Is an exchange move allowed? */

function handleDragstart(e, ui) {
   /* The dragstart target is the DIV inside a TD */
   elementDragged = e.target;
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
         opacity : 0.8,
         helper : "clone",
         cursor : "pointer",
         zIndex : 100,
         start : handleDragstart,
         stop : handleDragend
      }
   );
}

function removeDraggable(elem) {
   /* The DIVs inside the board TDs are draggable */
   $(elem).draggable("destroy");
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
      var ok = true;
      var parentid = eld.parentNode.id;
      if (parentid.charAt(0) == 'R') {
         /* Dropping from the rack */
         var t = $(eld).data("tile");
         if (!dropToRack && t == '?') {
            /* Dropping a blank tile on to the board: we need to ask for its meaning */
            openBlankDialog(eld, e.target);
            ok = false; // The drop will be completed later, when the blank dialog is closed
         }
      }
      if (ok) {
         /* Complete the drop */
         eld.parentNode.removeChild(eld);
         e.target.appendChild(eld);
         if (e.target.id.charAt(0) == 'R') {
            /* Dropping into the rack */
            if ($(eld).data("tile") == '?') {
               /* Dropping a blank tile: erase its letter value, if any */
               $(eld).data("letter", ' ');
               eld.childNodes[0].nodeValue = "\xa0"; // Non-breaking space, i.e. &nbsp;
            }
         }
         // Save this state in local storage,
         // to be restored when coming back to this game
         saveTiles();
      }
      updateButtonState();
   }
   elementDragged = null;
}

/* The word that is being checked for validity with a server query */
var wordToCheck = "";

function wordGoodOrBad(flagGood, flagBad) {
   /* Flag whether the word being laid down is good or bad (or neither when we don't know) */
   $("div.word-check").toggleClass("word-good", flagGood);
   $("div.word-check").toggleClass("word-bad", flagBad);
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
   if ((!gameOver) && localTurn()) {
      /* The local player's turn */
      showMove = (tilesPlaced !== 0);
      showExchange = true;
      showPass = (tilesPlaced === 0);
      showResign = true;
      /* Disable or enable buttons according to current state */
      $("div.submitmove").toggleClass("disabled",
         (tilesPlaced === 0 || showingDialog));
      $("div.submitexchange").toggleClass("disabled",
         (tilesPlaced !== 0 || showingDialog || !exchangeAllowed));
      $("div.submitpass").toggleClass("disabled",
         (tilesPlaced !== 0 || showingDialog));
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
   /* Erase previous error message, if any */
   $("div.error").css("visibility", "hidden");
   /* Calculate tentative score */
   $("div.score").removeClass("word-good").removeClass("word-great");
   if (tilesPlaced === 0) {
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
         serverQuery("/wordcheck", { word: wordToCheck, words: scoreResult.words }, showWordCheck);
      }
      showRecall = true;
   }
   $("div.submitmove").css("visibility", showMove ? "visible" : "hidden");
   $("div.submitexchange").css("visibility", showExchange ? "visible" : "hidden");
   $("div.submitpass").css("visibility", showPass ? "visible" : "hidden");
   $("div.submitresign").css("visibility", showResign ? "visible" : "hidden");
   $("div.recallbtn").css("visibility", showRecall ? "visible" : "hidden");
   $("div.scramblebtn").css("visibility", showScramble ? "visible" : "hidden");
}

function buttonOver(elem) {
   /* Show a hover effect on a button */
   if (!$(elem).hasClass("disabled"))
      $(elem).toggleClass("over", true);
}

function buttonOut(elem) {
   /* Hide a hover effect on a button */
   $(elem).toggleClass("over", false);
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
   $("#bag").html("");
   var lenbag = bag.length;
   var ix = 0;
   // If 7 or fewer unseen tiles, the bag is empty and they're all in the opponent's
   // rack; display the tiles in the opponent's color
   $("#bag").toggleClass("empty", lenbag <= RACK_SIZE);
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
      $("#bag").append(str);
   }
}

function _updateState(json, preserveTiles) {
   /* Work through the returned JSON object to update the
      board, the rack, the scores and the move history */
   if (json.result === 0 || json.result == GAME_OVER) {
      /* Successful move */
      /* Reinitialize the rack - we show it even if the game is over */
      var i = 0;
      var score;
      if (preserveTiles && json.result == GAME_OVER) {
         // The user may have placed tiles on the board: force them back
         // into the rack and make the rack non-draggable
         resetRack();
         initRackDraggable(false);
      }
      if (!preserveTiles) {
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
         /* Glue the laid-down tiles to the board */
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
            }
         });
      }
      /* Remove highlight from previous move, if any */
      $("div.highlight1").removeClass("highlight1");
      $("div.highlight0").removeClass("highlight0");
      /* Add the new tiles laid down in response */
      if (json.lastmove !== undefined) {
         var delay = 0;
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
            placeTile(sq, /* Coordinate */
               json.lastmove[i][1], /* Tile */
               json.lastmove[i][2], /* Letter */
               json.lastmove[i][3]); /* Score */
            // Show the new tiles with a progressive fade-in effect
            $("#"+sq).children().eq(0).addClass("freshtile")
               .hide().delay(delay).fadeIn();
            delay += 200; // 200 ms between tiles
         }
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
         }
      }
      /* Update the bag */
      if (json.bag !== undefined)
         updateBag(json.bag);
      /* See if an exchange move is still allowed */
      if (json.xchg !== undefined)
         exchangeAllowed = json.xchg;
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
         $("div.submitmove").css("display", "none");
         $("div.submitnewgame").css("display", "inline");
         gameOver = true;
      }
   }
   else {
      /* Genuine error: display in error bar */
      $("div.error").css("visibility", "visible").find("p").css("display", "none");
      var errorP = $("div.error").find("#err_" + json.result.toString());
      errorP.css("display", "inline");
      if (json.msg !== undefined)
         // Fill in word if provided in error message
         errorP.find("span.errword").text(json.msg);
   }
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

function confirmPass(yes) {
   /* The user has either confirmed or cancelled the pass move */
   $("div.pass").css("visibility", "hidden");
   showingDialog = false;
   initRackDraggable(true);
   updateButtonState();
   if (yes)
      sendMove('pass');
}

function submitPass(btn) {
   /* The user has clicked the pass button: show confirmation banner */
   if (!$(btn).hasClass("disabled")) {
      $("div.pass").css("visibility", "visible");
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
   $("div.error").css("visibility", "visible").find("p").css("display", "none");
   $("div.error").find("#err_server").css("display", "inline");
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
   /* Be sure to remove the halo from the submit button */
   $("div.submitmove").removeClass("over");
   /* Erase previous error message, if any */
   $("div.error").css("visibility", "hidden");
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
      updateState, moveComplete, serverError);
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
      var tileCount = "<div class='tilecount trans'><div class='tc" + winLose + "' style='width:" +
         Math.round(item.tile_count * 100 / BAG_SIZE).toString() + "%'>" + opp + "</div></div>";
      var str = "<div class='games-item' title='" + title + "'>" +
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
      { }, // No parameter data required
      populateGames
   );
}

function selectTab(ev) {
   /* A right-side tab has been selected: bring it to the foreground */
   var tabSel = $(this).attr("id");
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
      if (!chatLoaded) {
         loadChat();
         if (hadUnseen)
            // Indicate that we've now seen previously unseen messages
            sendChatSeenMarker();
      }
      // Focus on the text input field
      $("#msg").focus();
   }
   else
   if (tabSel == "tab-games") {
      // Selecting the games tab: load the pending games
      loadGames();
   }
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
   // Parse and split a timestamp string from the format YYYY-MM-DD HH:MM:SS
   return {
      year: parseInt(ts.substr(0, 4)),
      month: parseInt(ts.substr(5, 2)),
      day: parseInt(ts.substr(8, 2)),
      hour: parseInt(ts.substr(11, 2)),
      minute: parseInt(ts.substr(14, 2)),
      second: parseInt(ts.substr(17, 2))
   };
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
   var dcTs = decodeTimestamp(ts);
   // Create a JavaScript millisecond-based representation of the time stamp
   var dtTs = Date.UTC(dcTs.year, dcTs.month - 1, dcTs.day,
      dcTs.hour, dcTs.minute, dcTs.second);
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

// !!! The following code is mostly identical to code in main.js
// !!! It should be kept in sync as far as possible

function toggle(ev) {
   // Toggle from one state to the other
   var elemid = "#" + ev.delegateTarget.id;
   var state = $(elemid + " #opt2").hasClass("selected");
   $(elemid + " #opt1").toggleClass("selected", state);
   $(elemid + " #opt2").toggleClass("selected", !state);
   // Return the new state of the toggle
   return !state;
}

function initToggle(elemid, state) {
   // Initialize a toggle
   $(elemid + " #opt2").toggleClass("selected", state);
   $(elemid + " #opt1").toggleClass("selected", !state);
}

function populateUserInfo(json) {
   /* Populate a game list for a user info dialog */
   _populateRecentList(json, "#usr-recent");
}

function _populateRecentList(json, listId) {
   /* Worker function to populate a list of recent games */
   if (!json || json.result === undefined)
      return;
   if (json.result !== 0)
      /* Probably out of sync or login required */
      /* !!! TBD: Add error reporting here */
      return;
   for (var i = 0; i < json.recentlist.length; i++) {
      var item = json.recentlist[i];
      var opp = escapeHtml(item.opp);
      if (item.opp_is_robot)
         // Mark robots with a cog icon
         opp = "<span class='glyphicon glyphicon-cog'></span>&nbsp;" + opp;
      // Show won games with a ribbon
      var myWin = "<span class='glyphicon glyphicon-bookmark" +
         (item.sc0 >= item.sc1 ? "" : " grayed") + "'></span>";
      // Format the game duration
      var duration = "";
      if (item.duration === 0) {
         if (item.days || item.hours || item.minutes) {
            if (item.days > 1)
               duration = item.days.toString() + " dagar";
            else
            if (item.days == 1)
               duration = "1 dagur";
            if (item.hours > 0) {
               if (duration.length)
                  duration += " og ";
               duration += item.hours.toString() + " klst";
            }
            if (item.days === 0) {
               if (duration.length)
                  duration += " og ";
               if (item.minutes == 1)
                  duration += "1 mínúta";
               else
                  duration += item.minutes.toString() + " mínútur";
            }
         }
      }
      else
         // This was a timed game
         duration = "<span class='timed-btn' title='Viðureign með klukku'></span> 2 x " +
            item.duration + " mínútur";
      // Show the Elo point adjustments resulting from the game
      var eloAdj = item.elo_adj ? item.elo_adj.toString() : "";
      var eloAdjHuman = item.human_elo_adj ? item.human_elo_adj.toString() : "";
      var eloAdjClass, eloAdjHumanClass;
      // Find out the appropriate class to use depending on the adjustment sign
      if (item.elo_adj !== null)
         if (item.elo_adj > 0) {
            eloAdj = "+" + eloAdj;
            eloAdjClass = "elo-win";
         }
         else
         if (item.elo_adj < 0)
            eloAdjClass = "elo-loss";
         else {
            eloAdjClass = "elo-neutral";
            eloAdj = "<span class='glyphicon glyphicon-stroller' title='Byrjandi'></span>";
         }
      if (item.human_elo_adj !== null)
         if (item.human_elo_adj > 0) {
            eloAdjHuman = "+" + eloAdjHuman;
            eloAdjHumanClass = "elo-win";
         }
         else
         if (item.human_elo_adj < 0)
            eloAdjHumanClass = "elo-loss";
         else {
            eloAdjHumanClass = "elo-neutral";
            eloAdjHuman = "<span class='glyphicon glyphicon-stroller' title='Byrjandi'></span>";
         }
      eloAdj = "<span class='elo-btn right " + eloAdjClass +
         (eloAdj.length ? "" : " invisible") +
         "'>" + eloAdj + "</span>";
      eloAdjHuman = "<span class='elo-btn left " + eloAdjHumanClass +
         (eloAdjHuman.length ? "" : " invisible") +
         "'>" + eloAdjHuman + "</span>";
      // Assemble the table row
      var str = "<div class='listitem " + ((i % 2 === 0) ? "oddlist" : "evenlist") + "'>" +
         "<a href='" + item.url + "'>" +
         "<span class='list-win'>" + myWin + "</span>" +
         "<span class='list-ts'>" + item.ts_last_move + "</span>" +
         "<span class='list-nick'>" + opp + "</span>" +
         "<span class='list-s0'>" + item.sc0 + "</span>" +
         "<span class='list-colon'>:</span>" +
         "<span class='list-s1'>" + item.sc1 + "</span>" +
         "<span class='list-elo-adj'>" + eloAdjHuman + "</span>" +
         "<span class='list-elo-adj'>" + eloAdj + "</span>" +
         "<span class='list-duration'>" + duration + "</span>" +
         "</a></div>";
      $(listId).append(str);
   }
}

function showUserInfo(oppInfo) {
   /* Show the user information dialog */
   $("#usr-info-nick").text(oppInfo.nick);
   $("#usr-info-fullname").text(oppInfo.fullname);
   initToggle("#stats-toggler", false); // Show human only stats by default
   $("#usr-stats-human").css("display", "inline-block");
   $("#usr-stats-all").css("display", "none");
   $("#usr-info-dialog")
      .data("userid", oppInfo.userid)
      .css("visibility", "visible");
   // Populate the #usr-recent DIV
   serverQuery("/recentlist",
      {
         user: oppInfo.userid,
         count: 40 // Limit recent game count to 40
      },
      populateUserInfo);
   // Populate the user statistics
   serverQuery("/userstats",
      {
         user: oppInfo.userid
      },
      populateUserStats);
}

function markFavorite(elem, uid) {
   /* Toggle a favorite mark for the indicated user */
   var action;
   if ($(elem).hasClass("glyphicon-star-empty")) {
      $(elem).removeClass("glyphicon-star-empty");
      $(elem).addClass("glyphicon-star");
      action = "add";
   }
   else {
      $(elem).removeClass("glyphicon-star");
      $(elem).addClass("glyphicon-star-empty");
      action = "delete";
   }
   serverQuery("/favorite",
      {
         // Identify the relation in question
         destuser: uid,
         action: action
      }, null); // No success func needed - it's a one-way notification
}

function favUserInfo() {
   // The favorite star icon has been clicked: modify the favorite status
   var userId = $("#usr-info-dialog").data("userid");
   var elem = document.getElementById("usr-info-fav-star");
   markFavorite(elem, userId);
}

function hideUserInfo(ev) {
   /* Hide the user information dialog */
   $("#usr-info-dialog").css("visibility", "hidden");
   $("#usr-recent").html("");
}

function showStat(prefix, id, val, icon, suffix) {
   // Display a user statistics figure, eventually with an icon
   var txt = val.toString();
   if (suffix !== undefined)
      txt += suffix;
   if (icon !== undefined)
      txt = "<span class='glyphicon glyphicon-" + icon + "'></span>&nbsp;" + txt;
   $("#" + prefix + "-stats-" + id).html(txt);
}

function _populateStats(prefix, json) {
   // Display user statistics, either the client user's own,
   // or a third party in a user info dialog
   showStat(prefix, "elo", json.elo, "crown");
   showStat(prefix, "human-elo", json.human_elo, "crown");
   showStat(prefix, "games", json.games, "th");
   showStat(prefix, "human-games", json.human_games, "th");
   var winRatio = 0, winRatioHuman = 0;
   if (json.games > 0)
      winRatio = Math.round(100.0 * json.wins / json.games);
   if (json.human_games > 0)
      winRatioHuman = Math.round(100.0 * json.human_wins / json.human_games);
   var avgScore = 0, avgScoreHuman = 0;
   if (json.games > 0)
      avgScore = Math.round(json.score / json.games);
   if (json.human_games > 0)
      avgScoreHuman = Math.round(json.human_score / json.human_games);
   showStat(prefix, "win-ratio", winRatio, "bookmark", "%");
   showStat(prefix, "human-win-ratio", winRatioHuman, "bookmark", "%");
   showStat(prefix, "avg-score", avgScore, "dashboard");
   showStat(prefix, "human-avg-score", avgScoreHuman, "dashboard");
   if (prefix == "usr") {
      // Show a star shape depending on favorite status
      var favStar = $("#usr-info-fav-star");
      favStar.toggleClass("glyphicon-star-empty", !json.favorite);
      favStar.toggleClass("glyphicon-star", json.favorite);
   }
}

function populateUserStats(json) {
   // Populate the statistics for a particular user
   _populateStats("usr", json);
}

function toggleStats(ev) {
   // Toggle between displaying user stats for human games only or for all
   var state = toggle(ev);
   $("#usr-stats-human").css("display", state ? "none" : "inline-block");
   $("#usr-stats-all").css("display", state ? "inline-block" : "none");
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
      showUserInfo(opponentInfo());
   }
}

/* Channel API stuff */

var channelToken = null;
var channel = null;
var socket = null;

function openChannel(token) {
   /* Open a new channel using the token stored in channelToken */
   channelToken = token;
   channel = new goog.appengine.Channel(token);
   socket = channel.open({
      onopen : channelOnOpen,
      onmessage : channelOnMessage,
      onerror : channelOnError,
      onclose : channelOnClose
   });
}

function channelOnOpen() {
}

function channelOnMessage(msg) {
   /* The server has sent a notification message back on our channel */
   var json = jQuery.parseJSON(msg.data);
   if ((json.stale !== undefined) && json.stale)
      // We missed updates on our channel: reload the board
      window.location.reload(true);
   else
   if (json.msg !== undefined) {
      // This is a chat message
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
   else {
      // json now contains an entire client state update, as a after submitMove()
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
}

function channelOnError(err) {
   /* Act on err.code and err.description here */
}

function newChannel(json) {
   /* Ajax callback, called when the server has issued a new channel token */
   if (json && json.result === 0) {
      // No error: get the new token and reopen the channel
      openChannel(json.token);
   }
}

function channelOnClose() {
   /* The channel has expired or is being closed for other reasons: request a new one */
   serverQuery("newchannel",
      { game: gameId(), oldch: channelToken },
      newChannel);
   channelToken = null;
   channel = null;
   socket = null;
}

function initSkrafl(jQuery) {
   /* Called when the page is displayed or refreshed */

   // Initialize the game timing information (duration, elapsed time)
   var igt = initialGameTime();

   if (igt.duration > 0)
      // This is a timed game: move things around and show the clock
      showClock();

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

   // Clicking on player identifier buttons
   $("div.player-btn").click(lookAtPlayer);

   // Bind a handler to the close icon on the board color help panel
   $("div.board-help-close span").click(closeHelpPanel);

   /* Enable the close button in the user info dialog */
   $("#usr-info-close").click(hideUserInfo);

   /* Enable clicking on the favorite star icon in the user info dialog */
   $("div.usr-info-fav").click(favUserInfo);

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

   lateInit();

   if (igt.duration > 0)
      startClock(igt);

   // Done with the initialization phase
   initializing = false;
}

