/*

   Wait.js

   Client-side script for wait.html,
   a page displated while waiting for a time-limited game to start

   Author: Vilhjalmur Thorsteinsson, 2015

*/

var finalClose = false;

function channelOnMessage(msg) {
   /* The server has sent a notification message back on our channel */
   var json = jQuery.parseJSON(msg.data);
   if (json.kind == "ready")
      // The opponent is ready and a new game has been created:
      // navigate to it
      goToGame(json.game);
}

function channelOnClose() {
   /* Channel expired: Ask for a new channel from the server */
   var chTok = channelToken;
   channelToken = null;
   channel = null;
   socket = null;
   if (!finalClose)
      serverQuery("newchannel", { wait: opponentId(), oldch: chTok }, newChannel);
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
   /* Attempt to be tidy by explicitly closing the channel socket,
      thereby speeding up the channel disconnect */
   finalClose = true;
   if (socket)
      socket.close();
   /* Navigate back to the main page */
   cancelWait();
}

function initWait() {
   /* Called when the wait.html page is displayed or refreshed */

   /* Enable the close button in the user info dialog */
   $("#wait-cancel").click(closeAndCleanUp);

   /* Call initialization that requires variables coming from the server */
   lateInit();

}

