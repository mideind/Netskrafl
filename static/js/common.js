/*

   Common.js

   Common utility functions used by the Netskrafl HTML pages

   Copyright (C) 2024 Miðeind ehf.
   Author: Vilhjalmur Thorsteinsson

   The GNU General Public License, version 3, applies to this software.
   For further information, see https://github.com/vthorsteinsson/Netskrafl

*/

/*
   global $:false, serverQuery, gameUrl, userId, serverQueryHtml
*/

/* eslint-disable no-unused-vars */

function hasOwnProp(obj, prop) {
   return Object.prototype.hasOwnProperty.call(obj, prop);
}

function toKilos(num) {
   // Return a number in kilos ('k' suffix) if it is above 10,000
   if (num >= 100000)
      return (num / 1000).toFixed(0) + "k";
   if (num >= 10000)
      return (num / 1000).toFixed(1).replace(".", ",") + "k";
   return num.toString();
}

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
   return String(string).replace(/[&<>"'/]/g, function (s) {
      return entityMap[s];
   });
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

function showUserInfo(nick, fullname, userid) {
   /* Show the user information dialog */
   $("#usr-info-nick").text(nick);
   $("#usr-info-fullname").text(fullname);
   initToggle("#stats-toggler", false); // Show human only stats by default
   $("#usr-stats-human").css("display", "inline-block");
   $("#usr-stats-all").css("display", "none");
   $("#versus-all").toggleClass("shown", true);
   $("#versus-you").toggleClass("shown", false);
   // By default, not a friend of Netskrafl (modified later if friend)
   $("#usr-info-icon-user").css("display", "inline-block");
   $("#usr-info-icon-friend").css("display", "none");
   $("#usr-info-dialog")
      .data("userid", userid)
      .css("visibility", "visible");
   // Populate the #usr-recent DIV
   serverQuery("/recentlist",
      {
         user: userid,
         versus: null,
         count: 40 // Limit recent game count to 40
      },
      populateUserInfo);
   // Populate the user statistics
   serverQuery("/userstats",
      {
         user: userid
      },
      populateUserStats);
}

function toggleVersus(ev) {
   /* Show recent games between this user and the given opponent,
      or all games for this user, depending on toggle state */
   var oppId = $("#usr-info-dialog").data("userid");
   $("#versus-all").toggleClass("shown", ev.data == "versus-all");
   $("#versus-you").toggleClass("shown", ev.data == "versus-you");
   serverQuery("/recentlist",
      {
         user: oppId,
         versus: (ev.data == "versus-all" ? null : userId()),
         count: 40 // Limit recent game count to 40
      },
      populateUserInfo);
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

function populateUserInfo(json) {
   /* Populate a game list for a user info dialog */
   _populateRecentList(json, "#usr-recent");
}

function _populateRecentList(json, listId) {
   /* Worker function to populate a list of recent games */
   $(listId).html("");
   if (!json || json.result === undefined)
      return;
   if (json.result !== 0)
      /* Probably out of sync or login required */
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
      if (!item.duration) {
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
      else {
         // This was a timed game
         duration = "<span class='timed-btn' title='Viðureign með klukku'></span> 2 x " +
            item.duration + " mínútur";
      }
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

      // Was this a manual game?
      var manual = "<span class='glyphicon glyphicon-lightbulb" +
         (item.manual ? "' title='Keppnishamur'" : " grayed'") + "></span>";

      // Assemble the table row
      var str = "<div class='listitem " + ((i % 2 === 0) ? "oddlist" : "evenlist") + "'>" +
         "<a href='" + item.url + "'>" +
         "<span class='list-win'>" + myWin + "</span>" +
         "<span class='list-ts-short'>" + item.ts_last_move + "</span>" +
         "<span class='list-nick'>" + opp + "</span>" +
         "<span class='list-s0'>" + item.sc0 + "</span>" +
         "<span class='list-colon'>:</span>" +
         "<span class='list-s1'>" + item.sc1 + "</span>" +
         "<span class='list-elo-adj'>" + eloAdjHuman + "</span>" +
         "<span class='list-elo-adj'>" + eloAdj + "</span>" +
         "<span class='list-duration'>" + duration + "</span>" +
         "<span class='list-manual'>" + manual + "</span>" +
         "</a></div>";
      $(listId).append(str);
   }
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
   showStat(prefix, "games", toKilos(json.games), "th");
   showStat(prefix, "human-games", toKilos(json.human_games), "th");
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
   // Populate the highest score/best word field
   var best = "";
   if (json.highest_score)
      best = "Hæsta skor <b><a href='" + gameUrl(json.highest_score_game) + "'>" +
         json.highest_score + "</a></b>";
   if (json.best_word) {
      if (best.length)
         if (prefix == "own")
            best += "<br>"; // Own stats: Line break between parts
         else
            best += " | "; // Opponent stats: Divider bar between parts
      var bw = json.best_word;
      var s = "";
      // Make sure blank tiles get a different color
      for (var i = 0; i < bw.length; i++)
         if (bw[i] == '?') {
            s += "<span class='blanktile'>" + bw[i+1] + "</span>";
            i += 1;
         }
         else
            s += bw[i];
      best += "Besta orð <span class='best-word'>" + s + "</span>, " +
         "<b><a href='" + gameUrl(json.best_word_game) + "'>" +
         json.best_word_score + "</a></b> stig";
   }
   $("#" + prefix + "-best").html(best);
}

function populateUserStats(json) {
   // Populate the statistics for a particular user
   $("#usr-info-icon-user").css("display", json.friend ? "none" : "inline-block");
   $("#usr-info-icon-friend").css("display", json.friend ? "inline-block" : "none");
   _populateStats("usr", json);
}

function initToggle(elemid, state) {
   // Initialize a toggle
   $(elemid + " #opt2").toggleClass("selected", state);
   $(elemid + " #opt1").toggleClass("selected", !state);
}

function toggle(ev) {
   // Toggle from one state to the other
   var elemid = "#" + ev.delegateTarget.id;
   var state = $(elemid + " #opt2").hasClass("selected");
   $(elemid + " #opt1").toggleClass("selected", state);
   $(elemid + " #opt2").toggleClass("selected", !state);
   // Return the new state of the toggle
   return !state;
}

function toggleStats(ev) {
   // Toggle between displaying user stats for human games only or for all
   var state = toggle(ev);
   $("#usr-stats-human").css("display", state ? "none" : "inline-block");
   $("#usr-stats-all").css("display", state ? "inline-block" : "none");
}

function doRegisterSalesCloud(i,s,o,g,r,a,m) {
   i.SalesCloudObject=r;
   i[r]=i[r]||function(){(i[r].q=i[r].q||[]).push(arguments);};
   i[r].l=1*new Date();
   a=s.createElement(o);
   m=s.getElementsByTagName(o)[0];
   a.src=g;
   m.parentNode.insertBefore(a,m);
}

function registerSalesCloud() {
   doRegisterSalesCloud(
      window,
      document,
      'script',
      'https://cdn.salescloud.is/js/salescloud.min.js',
      'salescloud'
   );
}

function openPromoDialog(key, completeFunc) {
   // Show a modal promotion dialog, either for
   // a friend promo or a general promo
   $("#promo-dialog")
      .data("param", { key: key })
      .css("visibility", "visible")
      .toggleClass("promo-friend", false)
      .toggleClass("promo-" + key, true);
   $("#promo-form")
      .toggleClass("promo-friend", false)
      .toggleClass("promo-" + key, true);
   $("#promo-content")
      .toggleClass("promo-friend", false)
      .toggleClass("promo-" + key, true);
   // Obtain the promo content from the server and put it into the #promo-content div
   serverQueryHtml("/promo", { key: key }, "#promo-content", completeFunc);
}

function closePromoDialog() {
   // Hide the dialog
   var promoDialog = $("#promo-dialog");
   var key = promoDialog.data("param").key;
   promoDialog
      .data("param", null)
      .css("visibility", "hidden");
   $("#promo-form")
      .toggleClass("promo-" + key, false);
   $("#promo-content").html("");
}

var maybePreventPullToRefresh = false;
var lastTouchY = 0;
var pullToRefreshDisabled = false;

function _touchstartHandler(e) {
   if (e.touches.length != 1)
      return;
   lastTouchY = e.touches[0].clientY;
   // Pull-to-refresh will only trigger if the scroll begins when the
   // document's Y offset is zero.
   maybePreventPullToRefresh = (window.pageYOffset === 0);
}

function _touchmoveHandler(e) {
   var touchY = e.touches[0].clientY;
   var touchYDelta = touchY - lastTouchY;
   /* lastTouchY = touchY; */
   if (maybePreventPullToRefresh) {
      // To suppress pull-to-refresh it is sufficient to preventDefault the
      // first overscrolling touchmove.
      maybePreventPullToRefresh = false;
      if (touchYDelta > 0)
         e.preventDefault();
   }
}

function preventPullToRefresh(enable)
{
   /* Prevent the mobile (touch) behavior where pulling/scrolling the
      page down, if already at the top, causes a refresh of the web page */
   if (enable) {
      if (!pullToRefreshDisabled) {
         document.addEventListener('touchstart', _touchstartHandler, false);
         document.addEventListener('touchmove', _touchmoveHandler, { passive: false });
         pullToRefreshDisabled = true;
      }
   }
   else {
      if (pullToRefreshDisabled) {
         document.removeEventListener('touchstart', _touchstartHandler, false);
         document.removeEventListener('touchmove', _touchmoveHandler, { passive: false });
         pullToRefreshDisabled = false;
      }
   }
}

