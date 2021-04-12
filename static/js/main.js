/*

   Main.js
   Client-side script functions for main.html, the main page of Netskrafl

   Copyright (C) 2021 Miðeind ehf.
   Original author: Vilhjálmur Þorsteinsson

   The GNU General Public License, version 3, applies to this software.
   For further information, see https://github.com/mideind/Netskrafl

*/

/* global $:false,
   showUserInfo, openPromoDialog, registerSalesCloud, newgameUrl, serverQuery,
   _populateStats, _populateRecentList, toggle, escapeHtml, userId, userHasPaid,
   waitUrl, fairPlay, newBag, loginFirebase, attachFirebaseListener, initFirebaseListener,
   initPresence, preventPullToRefresh, hideUserInfo, favUserInfo, toggleVersus, lateInit
*/

/* eslint-disable no-unused-vars */

var uiFullscreen = false;

function _showUserInfo(ev) {
   showUserInfo(ev.data.nick, ev.data.fullname, ev.data.userid);
}

function updateChallenges(json) {
   /* Coming back from an update of challeges:
      refresh the challenge list */
   refreshChallengeList();
}

function markChallenge(ev) {
   /* Change the state of a challenge upon a click on a challenge icon */
   var action;
   var elem = ev.delegateTarget;
   if ($(elem).hasClass("glyphicon-thumbs-down")) {
      /* A challenge from another user is being declined */
      action = "decline";
   }
   else
   if ($(elem).hasClass("grayed")) {
      /* A challenge is being issued to another user */
      action = "issue";
   }
   else {
      /* A challenge to another user is being retracted */
      $(elem).addClass("grayed");
      action = "retract";
   }
   if (action == "issue") {
      if (!moreGamesAllowed()) {
         // User is now past his concurrent game limit:
         // promote becoming a friend
         openPromoDialog('friend', registerSalesCloud);
         return;
      }
      if (ev.data.userid.indexOf("robot-") === 0) {
         /* Challenging a robot: Create a new game and display it right away */
         window.location.href = newgameUrl(ev.data.userid, false);
         return;
      }
      /* New challenge: show dialog */
      showChallenge(elem.id, ev.data.userid, ev.data.nick,
         ev.data.fullname, ev.data.fairplay, ev.data.newbag);
   }
   else
      serverQuery("/challenge",
         {
            // Identify the relation in question
            destuser: ev.data.userid,
            action: action
         }, updateChallenges
      );
}

function populateOwnStats(json) {
   // Populate the user's own statistics
   _populateStats("own", json);
}

function toggleOwnStats(ev) {
   // Toggle between displaying the user's own stats for human games only or for all
   var state = toggle(ev);
   $("#own-stats-human").css("display", state ? "none" : "inline-block");
   $("#own-stats-all").css("display", state ? "inline-block" : "none");
}

// Is a user list request already in progress?
var ulRq = false;

function populateUserList(json) {
   /* Display a user list that has been returned from the server */
   ulRq = false; // Allow another user list request to proceed
   if (!json || json.result === undefined)
      return;
   if (json.result !== 0)
      /* Probably out of sync or login required */
      return;
   for (var i = 0; i < json.userlist.length; i++) {
      var item = json.userlist[i];
      // Robot userids start with 'robot-'
      var isRobot = item.userid.indexOf("robot-") === 0;
      var fav;
      if (isRobot)
         // Can't favorite a robot
         fav = "<span class='glyphicon glyphicon-star-empty'></span>";
      else
         fav = "<span title='Uppáhald' class='glyphicon glyphicon-star" +
         ((!item.fav) ? "-empty" : "") +
         "' onclick='markFavorite(this, \"" + item.userid + "\")'></span>";
      var chId = "chall" + i;
      var ch = "<span title='Skora á' class='glyphicon glyphicon-hand-right" +
         (item.chall ? "'" : " grayed'") +
         " id='" + chId + "'></span>";
      var nick = escapeHtml(item.nick);
      var alink = "", aclose = "", info = "", ready = "", elo = "";
      var clsFullname = "list-fullname";
      if (isRobot) {
         // Mark robots with a cog icon
         nick = "<span class='glyphicon glyphicon-cog'></span>&nbsp;" + nick;
         // Put a hyperlink on the robot name and description
         alink = "<a href='" + newgameUrl(item.userid, false) + "'>";
         aclose = "</a>";
         // Wider name column for robots
         clsFullname = "list-fullname-robot";
      }
      else {
         // Create a link to access user info
         info = "<span id='usr" + i + "' class='usr-info'></span>";
         // Show Elo points
         elo = "<span class='list-human-elo'>" + item.human_elo + "</span>";
      }
      if (info.length)
         info = "<span class='list-info' title='Skoða feril'>" + info + "</span>";
      // Readiness buttons
      if (item.ready && !isRobot)
         ready = "<span class='ready-btn' title='Álínis og tekur við áskorunum'></span> ";
      if (item.ready_timed)
         ready += "<span class='timed-btn' title='Til í viðureign með klukku'></span> ";
      // Fair play commitment
      if (item.fairplay)
         ready += "<span class='fairplay-btn' title='Skraflar án hjálpartækja'></span> ";
      // New bag preference
      var newbag = "<span class='glyphicon glyphicon-shopping-bag" +
         (item.newbag ? " grayed" : "") + "' title='Gamli pokinn'></span>";
      newbag = "<span class='list-newbag'>" + newbag + "</span>";
      // Assemble the entire line
      var str = "<div class='listitem " + ((i % 2 === 0) ? "oddlist" : "evenlist") + "'>" +
         "<span class='list-ch'>" + ch + "</span>" +
         "<span class='list-fav'>" + fav + "</span>" +
         alink +
         "<span class='list-nick'>" + nick + "</span>" +
         "<span class='" + clsFullname + "'>" + ready + escapeHtml(item.fullname) + "</span>" +
         elo +
         aclose +
         info +
         newbag +
         "</div>";
      $("#userlist").append(str);
      // Associate a click handler with the info button, if present
      if (info.length)
         $("#usr" + i).click(
            { userid: item.userid, nick: item.nick, fullname: item.fullname },
            _showUserInfo
         );
      // Associate a click handler with the challenge icon
      $("#" + chId).click(
         { userid: item.userid, nick: item.nick, fullname: item.fullname,
            fairplay: item.fairplay, newbag: item.newbag },
         markChallenge
      );
   }
   // If unsuccessful search, say so
   var noMatch = (json.spec !== null && json.spec !== "" && json.userlist.length === 0);
   $("#user-no-match").css("display", noMatch ? "block" : "none");
   if (noMatch)
      $("#search-prefix").text(json.spec);
}

function rankStr(rank, ref) {
   // Return a rank string or dash if no rank or not meaningful
   // (i.e. if the reference, such as the number of games, is zero)
   if (rank === 0 || (ref !== undefined && ref === 0))
      return "--";
   return rank.toString();
}

function populateEloList(json) {
   /* Display a user list that has been returned from the server */
   // Hide the user load spinner
   $("#user-load").css("display", "none");
   ulRq = false; // Allow another user list request to proceed
   if (!json || json.result === undefined)
      return;
   if (json.result !== 0)
      /* Probably out of sync or login required */
      return;
   for (var i = 0; i < json.rating.length; i++) {
      var item = json.rating[i];
      // Robot userids start with 'robot-'
      var isRobot = item.userid.indexOf("robot-") === 0;
      var chId = "chall" + i;
      var ch = "";
      var nick = escapeHtml(item.nick);
      var fullname = escapeHtml(item.fullname);
      var info = "&nbsp;"; // Necessary for correct rendering on iPad
      if (item.userid != userId() && !item.inactive)
         // Not the logged-in user himself and not inactive: allow a challenge
         ch = "<span title='Skora á' class='glyphicon glyphicon-hand-right" +
            (item.chall ? "'" : " grayed'") +
            " id='" + chId + "'></span>";
      if (isRobot) {
         // Mark robots with a cog icon
         nick = "<span class='glyphicon glyphicon-cog'></span>&nbsp;" + nick;
      }
      else
      if (item.userid != userId()) {
         // Create a link to access user info
         info = "<span id='usr" + i + "' class='usr-info'></span>";
      }
      info = "<span class='list-info' title='Skoða feril'>" + info + "</span>";
      // Fair play commitment
      if (item.fairplay)
         nick = "<span class='fairplay-btn' title='Skraflar án hjálpartækja'></span> " + nick;
      // New bag preference
      var newbag = "<span class='glyphicon glyphicon-shopping-bag" +
         (item.newbag ? " grayed" : "") + "' title='Gamli pokinn'></span>";
      newbag = "<span class='list-newbag'>" + newbag + "</span>";
      // Assemble the entire line
      var str = "<div class='listitem " + ((i % 2 === 0) ? "oddlist" : "evenlist") + "'>" +
         "<span class='list-ch'>" + ch + "</span>" +
         "<span class='list-rank bold'>" + rankStr(item.rank) + "</span>" +
         "<span class='list-rank-no-mobile'>" + rankStr(item.rank_yesterday) + "</span>" +
         "<span class='list-rank-no-mobile'>" + rankStr(item.rank_week_ago) + "</span>" +
         "<span class='list-nick-elo' title='" + fullname + "'>" + nick + "</span>" +
         "<span class='list-elo bold'>" + item.elo + "</span>" +
         "<span class='list-elo-no-mobile'>" + rankStr(item.elo_yesterday, item.games_yesterday) + "</span>" +
         "<span class='list-elo-no-mobile'>" + rankStr(item.elo_week_ago, item.games_week_ago) + "</span>" +
         "<span class='list-elo-no-mobile'>" + rankStr(item.elo_month_ago, item.games_month_ago) + "</span>" +
         "<span class='list-games bold'>" + item.games + "</span>" +
         "<span class='list-ratio'>" + item.ratio + "%</span>" +
         "<span class='list-avgpts'>" + item.avgpts + "</span>" +
         info +
         newbag +
         "</div>";
      $("#userlist").append(str);
      // Associate a click handler with the info button, if present
      if (info.length)
         $("#usr" + i).click(
            { userid: item.userid, nick: item.nick, fullname: item.fullname },
            _showUserInfo
         );
      if (ch.length)
         // Associate a click handler with the challenge icon,
         // if this is not the logged-in user himself
         $("#" + chId).click(
            { userid: item.userid, nick: item.nick, fullname: item.fullname,
               fairplay: item.fairplay, newbag: item.newbag },
            markChallenge
         );
   }
}

function toggleElo(ev) {
   // The Elo rating list toggle has been clicked:
   // display a list of all users including robots, or a list of humans only
   if (ulRq)
      return;
   var eloState = toggle(ev);
   $("#userlist").html("");
   /* Show the user load spinner */
   $("#user-load").css("display", "block");
   ulRq = true; // Set to false again in populateEloList()
   serverQuery("/rating",
      {
         kind: eloState ? "all" : "human"
      },
      populateEloList
   );
}

// What range of users was last displayed, in case we need to refresh?
var displayedUserRange = null;

function redisplayUserList() {
   /* Redisplay the user list that is being shown */
   if (displayedUserRange !== null)
      refreshUserList({ data: displayedUserRange });
}

function periodicUserList() {
   /* This function gets called at regular intervals to
      refresh the list of live (connected) users, if
      that list is selected */
   if (displayedUserRange && (displayedUserRange == "live")) {
      refreshUserList({ data: "live" });
   }
}

function refreshUserList(ev) {
   /* Erase existing user list and issue a request to the server for a new one */
   if (ulRq)
      // A user list request is already in progress: avoid race condition
      return;
   ulRq = true; // Set to false again in populateUserList()
   /* Erase existing user list, if any */
   $("#userlist").html("");
   /* Indicate which subtab is being shown */
   if (ev.delegateTarget) {
      $("div.user-cat span").removeClass("shown");
      $(ev.delegateTarget).addClass("shown");
   }
   /* Show the user load spinner */
   $("#user-load").css("display", "block");
   /* Establish the alphabet range that we want to display */
   var rangeType = ev.data + "";
   var rangeSpec = "";
   /* Note the last displayed range in case we need to redisplay */
   displayedUserRange = rangeType + "";
   if (rangeType == "elo") {
      // Show the Elo list header
      $("#usr-hdr").css("display", "none");
      $("#elo-hdr").css("display", "block");
   }
   else {
      $("#elo-hdr").css("display", "none");
      $("#usr-hdr").css("display", "block");
   }
   if (rangeType == "search") {
      // Asking for a search
      var idbox = $("#search-id");
      idbox.focus();
      rangeSpec = idbox.val().trim();
   }
   // Hide the Elo and user info button headers if listing the robots
   $("#usr-list-info").css("visibility", (rangeType == "robots") ? "hidden" : "visible");
   $("#usr-list-elo").css("visibility", (rangeType == "robots") ? "hidden" : "visible");
   if (rangeType == "elo")
      serverQuery("/rating",
         {
            kind: "human"
         },
         populateEloList);
   else
   if (rangeType != "search" || rangeSpec !== "")
      serverQuery("/userlist",
         {
            query: rangeType,
            spec: rangeSpec
         },
         populateUserList,
         function() {
            // Hide the user load spinner
            $("#user-load").css("display", "none");
         }
      );
   else {
      // Actually no processing going on
      $("#user-load").css("display", "none");
      ulRq = false;
   }
}

// Number of games by this user
var numGames;
// Maximum number of concurrent games unless user is a paying friend
var MAX_GAME_LIMIT = 8;

function populateGameList(json) {
   numGames = undefined;
   if (!json || json.result === undefined)
      return;
   if (json.result !== 0)
      /* Probably out of sync or login required */
      return;
   numGames = json.gamelist.length;
   var numMyTurns = 0;
   for (var i = 0; i < numGames; i++) {
      var item = json.gamelist[i];
      var fullname = escapeHtml(item.fullname);
      var opp = escapeHtml(item.opp);
      if (item.oppid === null)
         // Mark robots with a cog icon
         opp = "<span class='glyphicon glyphicon-cog'></span>&nbsp;" + opp;
      var turnText;
      if (item.my_turn)
         turnText = "Þú átt leik";
      else
      if (item.zombie)
         turnText = "Viðureign lokið";
      else
         turnText = opp + " á leik";
      var flagClass = " grayed";
      if (item.my_turn)
         flagClass = "";
      else
      if (item.zombie)
         flagClass = " zombie";
      // Fair play commitment
      if (item.fairplay)
         opp = "<span class='fairplay-btn' title='Skraflar án hjálpartækja'></span> " + opp;
      var myTurn = "<span title='" + turnText + "' class='glyphicon glyphicon-flag" +
         flagClass + "'></span>";
      var overdueText = item.overdue ?
         (item.my_turn ? "Er að renna út á tíma" : "Getur þvingað fram uppgjöf") : "";
      var overdue = "<span title='" + overdueText + "' class='glyphicon glyphicon-hourglass" +
         (item.overdue ? "" : " grayed") + "'></span>";
      var winLose = item.sc0 < item.sc1 ? " losing" : "";
      var tileCount = "<div class='tilecount'><div class='tc" + winLose + "' style='width:" +
         item.tile_count.toString() + "%'></div></div>";
      // Opponent track record button
      var info = "&nbsp;"; // Necessary for correct rendering on iPad
      if (item.oppid !== null) {
         info = "<span id='gmusr" + i + "' class='usr-info' title='Skoða feril'></span>";
      }
      // Is this a manual game?
      var manual = "<span class='glyphicon glyphicon-lightbulb" +
         (item.manual ? "' title='Keppnishamur'" : " grayed'") + "></span>";

      var str = "<div class='listitem " + ((i % 2 === 0) ? "oddlist" : "evenlist") + "'>" +
         "<a href='" + item.url + "'>" +
         "<span class='list-myturn'>" + myTurn + "</span>" +
         "<span class='list-overdue'>" + overdue + "</span>" +
         "<span class='list-ts-short'>" + item.ts + "</span>" +
         "<span class='list-opp' title='" + fullname + "'>" + opp + "</span>" +
         "</a>" +
         "<span class='list-info' title='Skoða feril'>" + info + "</span>" +
         "<span class='list-s0'>" + item.sc0 + "</span>" +
         "<span class='list-colon'>:</span>" +
         "<span class='list-s1'>" + item.sc1 + "</span>" +
         "<span class='list-tc'>" + tileCount + "</span>" +
         "<span class='list-manual'>" + manual + "</span>" +
         "</div>";
      $("#gamelist").append(str);
      // Enable user track record button
      $("#gmusr" + i).click(
         { userid: item.oppid, nick: item.opp, fullname: item.fullname },
         _showUserInfo
      );
      // Count games where it's this user's turn
      if (item.my_turn || item.zombie)
         numMyTurns++;
   }
   // Update the count of games where it's this user's turn
   if (numMyTurns === 0) {
      $("#numgames").css("display", "none");
      document.title = "Netskrafl";
   }
   else {
      $("#numgames").css("display", "inline-block").text(numMyTurns.toString());
      document.title = "(" + numMyTurns.toString() + ") Netskrafl";
   }
   if (numGames === 0) {
      // No games in the list: Display a hint to select an opponent
      $("div.hint").css("display", "block");
   }
   else {
      // Hide the hint
      $("div.hint").css("display", "none");
   }
}

function moreGamesAllowed() {
   // Is the user allowed to issue or accept more challenges?
   return userHasPaid() || (numGames !== undefined && numGames < MAX_GAME_LIMIT);
}

function refreshGameList() {
   /* Update list of active games for the current user */
   $("#gamelist").html("");
   serverQuery("/gamelist",
      {
         // No data to send with query - current user is implicit
      },
      populateGameList);
}

function populateRecentList(json) {
   /* Populate a list of recent games for the current user */
   _populateRecentList(json, "#recentlist");
}

function refreshRecentList() {
   /* Update list of recent games for the current user */
   $("#recentlist").html("");
   serverQuery("/recentlist",
      {
         // Current user is implicit
         versus: null,
         count: 40
      },
      populateRecentList);
   // Update the user's own statistics
   serverQuery("/userstats",
      {
         // Current user is implicit
      },
      populateOwnStats);
}

function acceptChallenge(ev) {
   /* Accept a previously issued challenge from the user in question */
   ev.preventDefault();
   if (!moreGamesAllowed()) {
      openPromoDialog('friend', registerSalesCloud);
      return;
   }
   var param = ev.data;
   var prefs = param.prefs;
   if (prefs !== undefined && prefs.duration !== undefined && prefs.duration > 0)
      /* Accepting a timed challenge: go to a wait page */
      window.location.href = waitUrl(param.userid);
   else
      /* Accepting a normal challenge: start a new game immediately */
      window.location.href = newgameUrl(param.userid, false);
}

function waitAccept(json) {
   /* Coming back from an opponent waiting query that was sent to the server */
   if (json && json.waiting)
      /* Create a new timed game. The true parameter indicates
         that the normal roles are reversed, i.e. here it is the
         original issuer of the challenge that is causing the new
         game to be created, not the challenged opponent */
      window.location.href = newgameUrl(json.userid, true);
   else {
      // The opponent is not ready
      $("#accept-status").html("Andstæðingurinn <strong><span id='accept-opp'></span></strong> er ekki reiðubúinn");
      $("#accept-opp").text($("#accept-nick").text());
      // We seem to have a reason to update the challenge list
      refreshChallengeList();
   }
}

function cancelAccept(ev) {
   /* Dismiss the acceptance dialog without creating a new game */
   $("#accept-dialog")
      .css("visibility", "hidden");
}

function showAccept(userid, nick, prefs) {
   /* Show the acceptance dialog */
   $("#accept-status").text("Athuga hvort andstæðingur er reiðubúinn...");
   $("#accept-nick").text(nick);
   $("#accept-dialog")
      .css("visibility", "visible");
   /* Launch a query to check whether the challenged user is online */
   serverQuery("/waitcheck",
      {
         user: userid
      },
      waitAccept);
}

function readyAccept(ev) {
   /* Trigger a timed game, if the opponent is waiting and ready to accept */
   ev.preventDefault();
   var param = ev.data;
   var prefs = param.prefs;
   if (prefs !== undefined && prefs.duration !== undefined && prefs.duration > 0) {
      showAccept(param.userid, param.nick, prefs);
   }
}

function markChallAndRefresh(ev) {
   /* Mark a challenge and refresh the user list */
   markChallenge(ev);
   redisplayUserList();
}

function challengeDescription(json) {
   /* Return a human-readable string describing a challenge
      according to the enclosed preferences */
   if (!json || json.duration === undefined || json.duration === 0)
      /* Normal unbounded (untimed) game */
      return "Venjuleg ótímabundin viðureign";
   return "Með klukku, 2 x " + json.duration.toString() + " mínútur";
}

var ival = null; // Flashing interval timer

function readyFlasher() {
   $(".opp-ready").toggleClass("blink");
}

function populateChallengeList(json) {
   /* Populate the lists of received and issued challenges */
   if (ival) {
      window.clearInterval(ival);
      ival = null;
   }
   if (!json || json.result === undefined)
      return;
   if (json.result !== 0)
      /* Probably out of sync or login required */
      return;
   /* Clear list of challenges received by this user */
   $("#chall-received").html("");
   /* Clear list of challenges sent by this user */
   $("#chall-sent").html("");
   var countReceived = 0, countSent = 0, countReady = 0;
   for (var i = 0; i < json.challengelist.length; i++) {
      var item = json.challengelist[i];
      var opp = escapeHtml(item.opp);
      var fullname = escapeHtml(item.fullname);
      var prefs = escapeHtml(challengeDescription(item.prefs));
      var odd = ((item.received ? countReceived : countSent) % 2 === 0);
      /* Show Decline icon (thumb down) if received challenge;
         show Delete icon (cross) if issued challenge */
      var icon;
      var opp_ready = false;
      if (item.received)
         icon = "<span title='Hafna' " +
            "class='glyphicon glyphicon-thumbs-down'";
      else {
         icon = "<span title='Afturkalla' " +
            "class='glyphicon glyphicon-hand-right'";
         if (item.opp_ready)
            opp_ready = true; // Opponent ready and waiting for timed game
      }
      var accId = "accept" + i;
      var readyId = "ready" + i;
      var chId = "chl" + i;
      icon += " id='" + chId + "'></span>";

      // Opponent track record button
      var info = "<span id='chusr" + i + "' class='usr-info'></span>";
      info = "<span class='list-info' title='Skoða feril'>" + info + "</span>";

      // Fair play indicator
      var fairplay = "";
      if (item.prefs.fairplay)
         fairplay = "<span class='fairplay-btn' title='Án hjálpartækja'></span> ";

      // Manual challenge indicator
      var manual = "";
      if (item.prefs.manual)
         manual = "<span class='manual-btn' title='Keppnishamur'></span> ";

      // New bag preference
      var newbag = "<span class='glyphicon glyphicon-shopping-bag" +
         (item.prefs.newbag ? " grayed" : "") + "' title='Gamli pokinn'></span>";
      newbag = "<span class='list-newbag'>" + newbag + "</span>";

      var str = "<div class='listitem " + (odd ? "oddlist" : "evenlist") + "'>" +
         "<span class='list-icon'>" + icon + "</span>" +
         (item.received ? ("<a href='#' id='" + accId + "'>") : "") +
         (opp_ready ? ("<a href='#' id='" + readyId + "' class='opp-ready'>") : "") +
         "<span class='list-ts'>" + item.ts + "</span>" +
         "<span class='list-nick' title='" + fullname + "'>" + opp + "</span>" +
         "<span class='list-chall'>" + fairplay + manual + prefs + "</span>" +
         (item.received ? "</a>" : "") +
         (opp_ready ? "</a>" : "") +
         info +
         newbag +
         "</div>";

      if (item.received) {
         $("#chall-received").append(str);
         // Route a click on the acceptance link
         $("#" + accId).click(
            { userid: item.userid, prefs: item.prefs },
            acceptChallenge
         );
         countReceived++;
      }
      else {
         $("#chall-sent").append(str);
         // Route a click on the opponent ready link
         if (opp_ready) {
            $("#" + readyId).click(
               { userid: item.userid, nick: item.opp, prefs: item.prefs },
               readyAccept
            );
            countReady++;
         }
         countSent++;
      }

      // Enable mark challenge button (to decline or retract challenges)
      $("#" + chId).click(
         { userid: item.userid, nick: item.opp, fullname: item.fullname,
            fairplay: false, newbag: false },
         markChallAndRefresh
      );
      // Enable user track record button
      $("#chusr" + i.toString()).click(
         { userid: item.userid, nick: item.opp, fullname: item.fullname },
         _showUserInfo
      );
   }
   // Update the count of received challenges and ready opponents
   if (countReceived + countReady === 0) {
      $("#numchallenges").css("display", "none");
   }
   else {
      $("#numchallenges").css("display", "inline-block")
         .text((countReceived + countReady).toString());
   }
   // If there is an opponent ready and waiting for a timed game,
   // do some serious flashing
   if (countReady)
      ival = window.setInterval(readyFlasher, 500);
}

/* Interval timer for the initial fetch of the challenge list,
   which occurs 2 seconds after the page is first loaded */
var ivalChallengeList = null;

function refreshChallengeList() {
   /* If we're being called as a result of an interval timer, clear it */
   if (ivalChallengeList !== null) {
      window.clearInterval(ivalChallengeList);
      ivalChallengeList = null;
   }
   // populateChallengeList clears out the existing content, if any
   serverQuery("/challengelist",
      {
         // No data to send with query - current user is implicit
      },
      populateChallengeList);
}

function prepareChallenge() {
   /* Enable buttons in the challenge dialog */
   $("#chall-cancel").click(cancelChallenge);
   $("#chall-ok").click(okChallenge);
   $("div.chall-time").click(function() {
      $("div.chall-time").removeClass("selected");
      $(this).addClass("selected");
   });

   // Enable the manual challenge toggle button

   function doManualToggle() {
      // Toggle from one state to the other
      $("#manual-toggler #opt1").toggleClass("selected");
      $("#manual-toggler #opt2").toggleClass("selected");
   }

   $("#manual-toggler").click(doManualToggle);
   $("#manual-toggler").keypress(function(ev) {
      if (ev.keyCode === 0 || ev.keyCode == 32)
         doManualToggle();
   });
}

function markOnline(json) {
   /* If the challenged user is online, show a bright icon */
   if (json && json.online !== undefined && json.online) {
      $("#chall-online").addClass("online");
      $("#chall-online").attr("title", "Er álínis");
   }
}

function showChallenge(elemid, userid, nick, fullname, fairplayOpp, newbagOpp) {
   /* Show the challenge dialog */
   $("#chall-nick").text(nick);
   $("#chall-fullname").text(fullname);
   $("#chall-online").removeClass("online");
   $("#chall-online").attr("title", "Er ekki álínis");
   $("#manual-toggler #opt1").toggleClass("selected", true);
   $("#manual-toggler #opt2").toggleClass("selected", false);
   // This is a fair play challenge if the issuing user and the
   // opponent are both marked as consenting to fair play
   var fairplayChallenge = fairplayOpp && fairPlay();
   // This is a new bag challenge unless the issuing user and
   // the challenged user both prefer the old bag
   var newbagChallenge = newbagOpp || newBag();
   // This may be a manual challenge if the issuing user is
   // a paying friend of Netskrafl
   var manualChallenge = userHasPaid();
   $("#chall-fairplay").toggleClass("hidden", !fairplayChallenge);
   $("#chall-oldbag").toggleClass("hidden", newbagChallenge);
   $("#chall-manual").toggleClass("hidden", !manualChallenge);
   $("#chall-dialog")
      .data("param", { elemid: elemid, userid: userid,
         fairplay: fairplayChallenge, newbag: newbagChallenge })
      .css("visibility", "visible");
   /* Launch a query to check whether the challenged user is online */
   serverQuery("/onlinecheck",
      {
         user: userid
      },
      markOnline);
}

function cancelChallenge(ev) {
   /* Hide the challenge dialog without issuing a challenge */
   $("#chall-dialog")
      .data("param", null)
      .css("visibility", "hidden");
}

function okChallenge(ev) {
   /* Issue a challenge from the challenge dialog */
   var param = $("#chall-dialog").data("param");
   /* Find out which duration is selected */
   var duration = $("div.chall-time.selected").attr("id").slice(6);
   if (duration == "none")
      duration = 0;
   else
      duration = parseInt(duration);
   /* Get the status of the manual challenge toggle */
   var manualChallenge = $("#manual-toggler #opt2").hasClass("selected");
   /* Inform the server */
   serverQuery("/challenge",
      {
         // Identify the relation in question
         destuser: param.userid,
         action: "issue",
         duration: duration,
         fairplay: param.fairplay,
         newbag: param.newbag,
         manual: manualChallenge
      },
      updateChallenges
   );
   /* Mark the challenge element */
   $("#" + param.elemid).removeClass("grayed");
   /* Tear down the dialog as we're done */
   cancelChallenge(ev);
}

function toggleReady(ev) {
   // The ready toggle has been clicked
   var readyState = toggle(ev);
   serverQuery("/setuserpref",
      {
         ready: readyState
      }
   );
}

function toggleTimed(ev) {
   // The timed toggle has been clicked
   var timedState = toggle(ev);
   serverQuery("/setuserpref",
      {
         ready_timed: timedState
      }
   );
}

function updateUserSearch()
{
   /* Make sure that the user search list is updated when the search criteria are modified */
   refreshUserList({ data: "search", delegateTarget: document.getElementById("search") });
}

var ivalUserSearch = null;

function periodicUserSearch() {
   // The waiting period has expired after a change of the search box
   // Clear the interval timer, if still running
   if (ivalUserSearch !== null) {
      window.clearInterval(ivalUserSearch);
      ivalUserSearch = null;
   }
   if (displayedUserRange == "search")
      // Still showing search results: send a request to update'em
      updateUserSearch();
}

function triggerUserSearch() {
   // The user search box has changed: trigger a new waiting period
   // before issuing a refresh of the user list
   if (ivalUserSearch !== null)
      window.clearInterval(ivalUserSearch);
   ivalUserSearch = window.setInterval(periodicUserSearch, 800); // 0.8 seconds
}

function handleChallengeMessage(json) {
   // A challenge to this user has been issued or retracted
   refreshChallengeList();
   redisplayUserList();
}

function handleMoveMessage(json) {
   // A move has been made in a game for this user
   refreshGameList();
   // Play audio, if present
   var yourTurn = document.getElementById("your-turn");
   if (yourTurn)
      // Note that playing media outside user-invoked event handlers does not work on iOS.
      // That is a 'feature' introduced and documented by Apple.
      yourTurn.play();
}

function initFirebaseListener(token) {
   // Sign into Firebase with the token passed from the server
   var uid = userId();
   var basepath = "user/" + uid + "/";
   // Log in and attach listeners once the login succeeds
   loginFirebase(token,
      function() {
         // Listen to Firebase events on the /user/[userId]/[messageType] path
         attachFirebaseListener(basepath + "challenge", handleChallengeMessage);
         attachFirebaseListener(basepath + "move", handleMoveMessage);
         initPresence(uid);
      }
   );
}

function mediaMinWidth667(mql) {
   if (mql.matches) {
      // Take action when min-width exceeds 667
   }
   else {
      // min-width is below 667
   }
}

function mediaMinWidth768(mql) {
   if (mql.matches) {
      // Take action when min-width exceeds 768
      uiFullscreen = true;
      preventPullToRefresh(false);
   }
   else {
      uiFullscreen = false;
      /* Prevent mobile behavior where pull down (scroll) causes a page refresh */
      preventPullToRefresh(true);
   }
}

function initMediaListener() {
   // Install listener functions for media changes
   var mql;
   mql = window.matchMedia("(min-width: 667px)");
   if (mql) {
      mediaMinWidth667(mql);
      mql.addEventListener("change", mediaMinWidth667);
   }
   mql = window.matchMedia("(min-width: 768px)");
   if (mql) {
      mediaMinWidth768(mql);
      mql.addEventListener("change", mediaMinWidth768);
   }
}

function initMain() {
   /* Called when the page is displayed or refreshed */

   // Put lazy loading logic in place for tabs that are not displayed initially
   $("#tabs").tabs({
      heightStyle: "auto",
      activate: function(event, ui) {
         var panelId = ui.newPanel.attr('id');
         /* The challenge list is loaded automatically after a short delay,
            so the following is not necessary */
         /*
         if (panelId == "tabs-2") {
            if (!$("#chall-received").html() && !$("#chall-sent").html())
               // Delay load challenge list
               refreshChallengeList();
         }
         else
         */
         if (panelId == "tabs-4") {
            if (!$("#recentlist").html())
               // Delay load recent game list
               refreshRecentList();
         }
         else
         if (panelId == "tabs-3") {
            if (!$("#userlist").html())
               // Delay load user list
               if (displayedUserRange !== null)
                  refreshUserList({ data: displayedUserRange });
               else
                  /* Initialize user list to show robots by default */
                  refreshUserList({ data: "robots" });
         }
      }
   });

   $("#opponents").click(function() {
      // Select and show the user list (opponents) tab
      $("#tabs").tabs("option", "active", 2);
   });

   /* Initialize game list */
   refreshGameList();

   /* Initialize the challenge list after two seconds */
   ivalChallengeList = window.setInterval(refreshChallengeList, 2 * 1000);

   /* Initialize categories (robots, favorites, similar...) in user list header */
   $("div.user-cat > span").each(function() {
      var data = $(this).attr('id');
      $(this).click(data, refreshUserList);
   });

   /* When starting to type in the user search box, focus on it */
   $("#search-id").focus(updateUserSearch).on("input", triggerUserSearch);

   /* Refresh the live user list periodically while it is being displayed */
   window.setInterval(periodicUserList, 5 * 60 * 1000); // Every five minutes

   /* Enable the close button in the user info dialog */
   $("#usr-info-close").click(hideUserInfo);

   /* Enable clicking on the favorite star icon in the user info dialog */
   $("div.usr-info-fav").click(favUserInfo);

   /* Initialize versus toggle in user info dialog */
   $("span.versus-cat > span").each(function() {
      var data = $(this).attr('id');
      $(this).click(data, toggleVersus);
   });

   /* Prepare the challenge dialog */
   prepareChallenge();

   /* Enable the cancel button in the acceptance dialog */
   $("#accept-cancel").click(cancelAccept);

   /* Listen to media events, such as orientation changes */
   initMediaListener();

   /* Call initialization that requires variables coming from the server */
   lateInit();

}

