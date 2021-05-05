/*

   Wait.js

   Client-side script for wait.html,
   a page displated while waiting for a time-limited game to start

   Copyright (C) 2021 Miðeind ehf.
   Original author: Vilhjálmur Þorsteinsson

   The GNU Affero General Public License, version 3, applies to this software.
   For further information, see https://github.com/mideind/Netskrafl

*/

/*
   global $:false, serverQuery, goToGame, cancelWait, loginFirebase,
   attachFirebaseListener, opponentId, userId, lateInit
*/

/* eslint-disable no-unused-vars */

function handleWaitMessage(json) {
   // The server has sent a notification on the /user/[user_id]/wait/[opponent_id] path
   if (json !== true && json.game)
      goToGame(json.game);
}

function markOnline(json) {
   /* If the challenged user is online, show a bright icon */
   if (json && json.online !== undefined && json.online) {
      $("#chall-online").addClass("online");
      $("#chall-online").attr("title", "Er álínis");
      $("#chall-is-online").text("");
   }
}

function initForm(userid, nick, fullname, duration) {
   /* Show the challenge dialog */
   $("#chall-nick").text(nick);
   $("#chall-nick-2").text(nick);
   $("#chall-fullname").text(fullname);
   $("#chall-duration").text(duration.toString());
   $("#chall-online").removeClass("online");
   $("#chall-online").attr("title", "Er ekki álínis");
   /* Launch a query to check whether the challenged user is online */
   serverQuery("/onlinecheck",
      {
         user: userid
      },
      markOnline);
}

function closeAndCleanUp(ev)
{
   // Cancel the wait status and navigate back to the main page
   serverQuery("/cancelwait",
      {
         user: userId(),
         opp : opponentId()
      }
   );
   cancelWait();
}

function initFirebaseListener(token) {
   // Sign into Firebase with the token passed from the server
   loginFirebase(token);
   // Listen to Firebase events on the /user/[userId]/wait/[oppId]/game path
   var path = 'user/' + userId() + "/wait/" + opponentId();
   attachFirebaseListener(path, handleWaitMessage);
}

function initWait() {
   /* Called when the wait.html page is displayed or refreshed */

   /* Enable the close button in the user info dialog */
   $("#wait-cancel").click(closeAndCleanUp);
   /* Call initialization that requires variables coming from the server */
   lateInit();
}

