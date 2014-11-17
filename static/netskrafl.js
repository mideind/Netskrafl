/*

   Netskrafl.js
   Client-side script for the Netskrafl server in netskrafl.py

   Author: Vilhjalmur Thorsteinsson, 2014
   
*/

/* Constants */

var ROWIDS = "ABCDEFGHIJKLMNO";
var BOARD_SIZE = 15;
var RACK_SIZE = 7;
var BAG_TILES_PER_LINE = 19;
var LEGAL_LETTERS = "aábdðeéfghiíjklmnoóprstuúvxyýþæö";

var WORDSCORE = Array(
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
var LETTERSCORE = Array(
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

var GAME_OVER = 15; /* Error code corresponding to the Error class in skraflmechanics.py */

/* Global variables */

var numMoves = 0;

function placeTile(sq, tile, letter, score) {
   /* Place a given tile in a particular square, either on the board or in the rack */
   if (tile.length == 0) {
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

function highlightMove(ev) {
   /* Highlight a move's tiles when hovering over it in the move list */
   var coord = ev.data.coord;
   var tiles = ev.data.tiles;
   var score = ev.data.score;
   var player = ev.data.player;
   var dx = 0, dy = 0;
   var col = 0;
   var row = ROWIDS.indexOf(coord.charAt(0));
   if (row >= 0) {
      /* Horizontal move */
      col = parseInt(coord.slice(1)) - 1;
      dx = 1;
   }
   else {
      /* Vertical move */
      row = ROWIDS.indexOf(coord.charAt(coord.length - 1));
      col = parseInt(coord) - 1;
      dy = 1;
   }
   for (var i = 0; i < tiles.length; i++) {
      var sq = ROWIDS.charAt(row) + (col + 1).toString();
      var tileDiv = $("#"+sq).children().eq(0);
      if (!(tileDiv == null))
         if (ev.data.show) {
            tileDiv.addClass("highlight" + player);
            $(this).find("span.score").addClass("highlight");
         }
         else {
            tileDiv.removeClass("highlight" + player);
            $(this).find("span.score").removeClass("highlight");
         }
      col += dx;
      row += dy;
   }
}

function appendMove(player, coord, tiles, score) {
   /* Add a move to the move history list */
   var wrdclass = "wordmove";
   var rawCoord = coord;
   if (coord == "") {
      /* Not a regular tile move */
      wrdclass = "othermove";
      if (tiles == "PASS")
         /* Pass move */
         tiles = "Pass";
      else
      if (tiles.indexOf("EXCH") == 0) {
         /* Exchange move - we don't show the actual tiles exchanged, only their count */
         numtiles = tiles.slice(5).length;
         tiles = "Skipti um " + numtiles.toString() + (numtiles == 1 ? " staf" : " stafi");
      }
      else
      if (tiles == "RSGN")
         /* Resigned from game */
         tiles = "Gaf leikinn";
      else
      if (tiles == "OVER") {
         /* Game over */
         tiles = "Leik lokið";
         wrdclass = "gameover";
      }
      else
         /* The rack leave at the end of the game (which is always in lowercase
            and thus cannot be confused with the above abbreviations) */
         wrdclass = "wordmove";
   }
   else {
      coord = "(" + coord + ")";
      tiles = tiles.replace("?", ""); /* !!! TODO: Display wildcard characters differently? */
   }
   var str;
   if (wrdclass == "gameover") {
      str = '<div class="gameover">' + tiles + '</div>';
   }
   else
   if (player == 0) {
      /* Left side player */
      str = '<div class="leftmove"><span class="score">' + score + '</span>' +
         '<span class="' + wrdclass + '"><i>' + tiles + '</i> ' + coord + '</span></div>';
   }
   else {
      /* Right side player */
      str = '<div class="rightmove"><span class="' + wrdclass + '">' + coord + ' <i>' + tiles + '</i></span>' +
         '<span class="score">' + score + '</span></div>';
   }
   var movelist = $("div.movelist");
   movelist.append(str);
   if (wrdclass != "gameover") {
      var m = $("div.movelist").children().last();
      var playerid = "0";
      if (player == humanPlayer())
         m.addClass("humangrad"); /* Local player */
      else {
         m.addClass("autoplayergrad"); /* Remote player */
         playerid = "1";
      }
      if (wrdclass == "wordmove") {
         /* Register a hover event handler to highlight this move */
         m.on("mouseover",
            { coord: rawCoord, tiles: tiles, score: score, player: playerid, show: true },
            highlightMove
         );
         m.on("mouseout",
            { coord: rawCoord, tiles: tiles, score: score, player: playerid, show: false },
            highlightMove
         );
      }
   }
   /* Manage the scrolling of the move list */
   var lastchild = $("div.movelist:last-child"); /* .children().last() causes problems */
   var firstchild = $("div.movelist").children().eq(0);
   var topoffset = lastchild.position().top -
      firstchild.position().top +
      lastchild.height();
   var height = movelist.height();
   if (topoffset >= height)
      movelist.scrollTop(topoffset - height)
   /* Count the moves */
   numMoves += 1;
}

function promptForBlank() {
   /* When dropping a blank tile, ask for its meaning */
   var defq = "Hvaða staf táknar auða flísin?";
   var err = "\nSláðu inn einn staf í íslenska stafrófinu."
   var q = defq;
   while(true) {
      letter = prompt(q);
      if (letter == null)
         /* Pressed Esc or terminated */
         return null;
      if (letter.length != 1) {
         q = defq + err;
         continue;
      }
      letter = letter.toLowerCase();
      if (LEGAL_LETTERS.indexOf(letter) == -1) {
         /* Not an allowed letter: add an error message and prompt again */
         q = defq + err;
         continue;
      }
      return letter;
   }
}

var elementDragged = null; /* The element being dragged with the mouse */
var showingDialog = false; /* Is a modal dialog banner being shown? */
var exchangeAllowed = true; /* Is an exchange move allowed? */

function handleDragstart(e, ui) {
   /* The dragstart target is the DIV inside a TD */
   elementDragged = e.target;
   elementDragged.style.opacity = "0.5"
}

function handleDragend(e, ui) {
   if (elementDragged != null)
      elementDragged.style.opacity = "1.0";
   elementDragged = null;
}

function handleDropover(e, ui) {
   if (e.target.id.charAt(0) == 'R' || e.target.firstChild == null)
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
   for (var i = 1; i <= RACK_SIZE; i++) {
      var rackTileId = "R" + i.toString();
      var rackTile = document.getElementById(rackTileId);
      if (rackTile && rackTile.firstChild)
         /* There is a tile in this rack slot */
         if (state)
            initDraggable(rackTile.firstChild);
         else
            removeDraggable(rackTile.firstChild);
   }
}

function initDropTarget(elem) {
   /* Prepare a board square or a rack slot to accept drops */
   if (elem != null)
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
   var x, y, coord, sq;
   for (x = 1; x <= BOARD_SIZE; x++)
      for (y = 1; y <= BOARD_SIZE; y++) {
         coord = ROWIDS.charAt(y - 1) + x.toString();
         sq = $("#"+coord);
         initDropTarget(sq);
      }
   /* Make the rack a drop target as well */
   for (x = 1; x <= RACK_SIZE; x++) {
      coord = "R" + x.toString();
      sq = $("#"+coord);
      initDropTarget(sq);
   }
}

function handleDrop(e, ui) {
   /* A tile is being dropped on a square on the board or into the rack */
   e.target.classList.remove("over");
   /* Save the elementDragged value as it will be set to null in handleDragend() */
   var eld = elementDragged;
   if (eld == null)
      return;
   eld.style.opacity = "1.0";
   var dropToRack = false;
   if (e.target.id.charAt(0) == 'R' && e.target.firstChild != null) {
      /* Dropping into an already occupied rack slot: shuffle the rack tiles to make room */
      var ix = parseInt(e.target.id.slice(1));
      var rslot = null;
      var i = 0;
      /* Try to find an empty slot to the right */
      for (i = ix + 1; i <= RACK_SIZE; i++) {
         rslot = document.getElementById("R" + i.toString());
         if (!rslot.firstChild)
            /* Empty slot in the rack */
            break;
         rslot = null;
      }
      if (rslot == null) {
         /* Not found: Try an empty slot to the left */
         for (i = ix - 1; i >= 1; i--) {
            rslot = document.getElementById("R" + i.toString());
            if (!rslot.firstChild)
               /* Empty slot in the rack */
               break;
            rslot = null;
         }
      }
      if (rslot == null) {
         /* No empty slot: must be internal shuffle in the rack */
         rslot = eld.parentNode;
         i = parseInt(rslot.id.slice(1));
      }
      if (rslot != null) {
         if (i > ix)
            /* Found empty slot: shift rack tiles to the right to make room */
            for (var j = i; j > ix; j--) {
               src = document.getElementById("R" + (j - 1).toString());
               tile = src.firstChild;
               src.removeChild(tile);
               rslot.appendChild(tile);
               rslot = src;
            }
         else
         if (i < ix)
            /* Found empty slot: shift rack tiles to the left to make room */
            for (var j = i; j < ix; j++) {
               src = document.getElementById("R" + (j + 1).toString());
               tile = src.firstChild;
               src.removeChild(tile);
               rslot.appendChild(tile);
               rslot = src;
            }
         dropToRack = true;
      }
   }
   if (e.target.firstChild == null) {
      /* Looks like a legitimate drop */
      var ok = true;
      parentid = eld.parentNode.id;
      if (parentid.charAt(0) == 'R') {
         /* Dropping from the rack */
         var t = $(eld).data("tile");
         if (!dropToRack && t == '?') {
            /* Dropping a blank tile: we need to ask for its meaning */
            e.target.classList.add("over");
            eld.style.opacity = "0.8";
            letter = promptForBlank();
            eld.style.opacity = "1.0";
            e.target.classList.remove("over");
            if (letter == null)
               ok = false;
            else {
               $(eld).data("letter", letter);
               $(eld).addClass("blanktile");
               eld.childNodes[0].nodeValue = letter;
            }
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
      }
      updateButtonState();
   }
   elementDragged = null;
}

function updateButtonState() {
   /* Refresh state of action buttons depending on availability */
   var tilesPlaced = findCovers().length;
   $("div.submitmove").toggleClass("disabled",
      (tilesPlaced == 0 || showingDialog));
   $("div.submitexchange").toggleClass("disabled",
      (tilesPlaced != 0 || showingDialog || !exchangeAllowed));
   $("div.submitpass").toggleClass("disabled",
      (tilesPlaced != 0 || showingDialog));
   $("div.submitresign").toggleClass("disabled",
      showingDialog);
   /* Erase previous error message, if any */
   $("div.error").css("visibility", "hidden");
   /* Calculate tentative score */
   var score = calcScore();
   $("div.score").text(score.toString())
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
   /* Return a list of the newly laid tiles on the board */
   var score = 0;
   var wsc = 1;
   var minrow = BOARD_SIZE, mincol = BOARD_SIZE;
   var maxrow = 0, maxcol = 0;
   var numtiles = 0;
   $("div.tile").each(function() {
      var sq = $(this).parent().attr("id");
      var t = $(this).data("tile");
      if (t !== null && t !== undefined && sq.charAt(0) != "R") {
         /* Tile on the board */
         var row = ROWIDS.indexOf(sq.charAt(0));
         var col = parseInt(sq.slice(1)) - 1;
         var sc = parseInt($(this).data("score")) * letterScore(row, col);
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
   return score * wsc + (numtiles == RACK_SIZE ? 50 : 0);
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
            rackTileId = "R" + rslot.toString();
            rackTile = document.getElementById(rackTileId);
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
   updateButtonState();
}

function rescrambleRack(ev) {
   /* Reorder the rack randomly. Bound to the Backspace key. */
   if (showingDialog)
      return false;

   resetRack(ev);
   var array = [];
   var i;
   for (i = 1; i <= RACK_SIZE; i++) {
      var rackTileId = "R" + i.toString();
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
      var rackTileId = "R" + i.toString();
      var elem = document.getElementById(rackTileId);
      if (elem.firstChild !== null)
         elem.removeChild(elem.firstChild);
      if (array[i-1] !== null)
         elem.appendChild(array[i-1]);
   }
   return false; // Stop default behavior
}

function updateBag(bag) {
   /* Update the bag display in the lower right corner */
   $("#bag").html("");
   var lenbag = bag.length;
   var ix = 0;
   while (lenbag > 0) {
      /* Rows */
      var str = "<tr>";
      /* Columns: max BAG_TILES_PER_LINE tiles per row */
      for (var i = 0; i < BAG_TILES_PER_LINE && lenbag > 0; i++) {
         var tile = bag[ix++]
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

function updateState(json) {
   /* Work through the returned JSON object to update the
      board, the rack, the scores and the move history */
   if (json.result == 0 || json.result == GAME_OVER) {
      /* Successful move */
      /* Reinitialize the rack */
      var i = 0;
      if (json.result == 0)
         for (i = 0; i < json.rack.length; i++)
            placeTile("R" + (i + 1).toString(), /* Coordinate */
               json.rack[i][0], /* Tile */
               json.rack[i][0], /* Letter */
               json.rack[i][1]); /* Score */
      /* Clear the rest of the rack */
      for (; i < RACK_SIZE; i++)
         placeTile("R" + (i + 1).toString(), "", "", 0);
      if (json.result == 0)
         initRackDraggable(true);
      /* Glue the laid-down tiles to the board */
      $("div.tile").each(function() {
         var sq = $(this).parent().attr("id");
         var t = $(this).data("tile");
         var score = $(this).data("score");
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
      /* Add the new tiles laid down in response */
      if (json.lastmove !== undefined)
         for (i = 0; i < json.lastmove.length; i++) {
            sq = json.lastmove[i][0];
            placeTile(sq, /* Coordinate */
               json.lastmove[i][1], /* Tile */
               json.lastmove[i][2], /* Letter */
               json.lastmove[i][3]); /* Score */
            $("#"+sq).children().eq(0).addClass("freshtile");
         }
      /* Update the scores */
      $(".scoreleft").text(json.scores[0]);
      $(".scoreright").text(json.scores[1]);
      /* Update the move list */
      if (json.newmoves !== undefined) {
         for (i = 0; i < json.newmoves.length; i++) {
            player = json.newmoves[i][0];
            coord = json.newmoves[i][1][0];
            tiles = json.newmoves[i][1][1];
            score = json.newmoves[i][1][2];
            appendMove(player, coord, tiles, score);
         }
      }
      /* Update the bag */
      if (json.bag !== undefined)
         updateBag(json.bag);
      /* See if an exchange move is still allowed */
      if (json.xchg !== undefined)
         exchangeAllowed = json.xchg;
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
      }
   }
   else {
      /* Genuine error: display in error bar */
      $("div.error").css("visibility", "visible").find("p").css("display", "none");
      var error_p = $("div.error").find("#err_" + json.result.toString());
      error_p.css("display", "inline");
      if (json.msg !== undefined)
         // Fill in word if provided in error message
         error_p.find("span.errword").text(json.msg);
   }
}

function submitPass() {
   /* The Pass button has been pressed: submit a Pass move */
   if (!$("div.submitpass").hasClass("disabled"))
      submitMove('pass');
}

function confirmExchange(yes) {
   /* The user has either confirmed or cancelled the exchange */
   $("div.exchange").css("visibility", "hidden");
   showingDialog = false;
   updateButtonState();
   /* Take the rack out of exchange mode */
   var exch = "";
   for (var i = 1; i <= RACK_SIZE; i++) {
      rackTileId = "#R" + i.toString();
      rackTile = $(rackTileId).children().eq(0)
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
   if (yes) {
      submitMove('exch=' + exch);
   }
}

function submitExchange() {
   /* The user has clicked the exchange button: show exchange banner */
   if (!$("div.submitexchange").hasClass("disabled")) {
      $("div.exchange").css("visibility", "visible");
      showingDialog = true;
      updateButtonState();
      initRackDraggable(false);
      /* Disable all other actions while panel is shown */
      /* Put the rack in exchange mode */
      for (var i = 1; i <= RACK_SIZE; i++) {
         rackTileId = "#R" + i.toString();
         rackTile = $(rackTileId).children().eq(0)
         if (rackTile)
            /* There is a tile in this rack slot: mark it as
               exchangeable and attack a click handler to it */
            rackTile.addClass("xchg").on("click.xchg", function (e) {
               $(this).toggleClass("xchgsel");
            });
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
      submitMove('rsgn');
}

function submitResign() {
   /* The user has clicked the resign button: show resignation banner */
   if (!$("div.submitresign").hasClass("disabled")) {
      $("div.resign").css("visibility", "visible");
      showingDialog = true;
      initRackDraggable(false);
      /* Disable all other actions while panel is shown */
      updateButtonState();
   }
}

var submitTemp = "";

function submitMove(movetype) {
   /* Send a move to the back-end server using Ajax */
   if (submitTemp.length > 0)
      /* Avoid re-entrancy: if submitTemp contains text, we are already
         processing a previous Ajax call */
      return;
   var moves = [];
   if (movetype === null || movetype == 'move') {
      if ($("div.submitmove").hasClass("disabled"))
         return;
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
   if (movetype.indexOf('exch=') == 0) {
      /* Exchange move */
      moves.push(movetype);
   }
   else
   if (movetype == 'rsgn') {
      /* Resigning from game */
      moves.push("rsgn");
   }
   if (moves.length == 0)
      return;
   /* Erase previous error message, if any */
   $("div.error").css("visibility", "hidden");
   /* Freshly laid tiles are no longer fresh */
   $("div.freshtile").removeClass("freshtile");
   /* Show a temporary animated GIF while the Ajax call is being processed */
   submitTemp = $("div.submitmove").html();
   $("div.submitmove").removeClass("disabled").removeClass("over");
   $("div.submitmove").html("<img src='/static/ajax-loader.gif' border=0/>");
   /* Talk to the game server using jQuery/Ajax */
   $.ajax({
      // the URL for the request
      url: "/submitmove",

      // the data to send
      data: {
         moves: moves,
         // Send a move count to ensure that the client and the server are in sync
         mcount: numMoves
      },

      // whether this is a POST or GET request
      type: "POST",

      // the type of data we expect back
      dataType : "json",

      cache: false,

      // code to run if the request succeeds;
      // the response is passed to the function
      success: updateState,

      // code to run if the request fails; the raw request and
      // status codes are passed to the function
      error: function(xhr, status, errorThrown) {
         alert("Villa í netsamskiptum");
         console.log("Error: " + errorThrown);
         console.log("Status: " + status);
         console.dir(xhr);
      },

      // code to run regardless of success or failure
      complete: function(xhr, status) {
         $("div.submitmove").html(submitTemp);
         submitTemp = "";
      }
   });
}

function initSkrafl(jQuery) {
   /* Called when the page is displayed or refreshed */
   placeTiles();
   initRackDraggable(true);
   initDropTargets();
   initMoveList();
   initBag();
   if (humanPlayer() == 0) {
      $("h3.playerleft").addClass("humancolor");
      $("h3.playerright").addClass("autoplayercolor");
   }
   else {
      $("h3.playerright").addClass("humancolor");
      $("h3.playerleft").addClass("autoplayercolor");
   }
   updateButtonState();
   /* Bind Esc key to a function to reset the rack */
   Mousetrap.bind('esc', resetRack);
   /* Bind Backspace key to a function to rescramble the rack */
   Mousetrap.bind('backspace', rescrambleRack);
}


