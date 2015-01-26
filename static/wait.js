/*

   Wait.js
   Client-side script for wait.html,
   a page displated while waiting for a time-limited game to start

   Author: Vilhjalmur Thorsteinsson, 2015

*/

function nullFunc(json) {
   /* Null placeholder function to use for Ajax queries that don't need a success func */
}

function errFunc(xhr, status, errorThrown) {
   /* Error handling function for Ajax communications */
   // alert("Villa í netsamskiptum");
   console.log("Error: " + errorThrown);
   console.log("Status: " + status);
   console.dir(xhr);
}

function serverQuery(requestUrl, jsonData, successFunc) {
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
      error: errFunc,

      // code to run regardless of success or failure
      complete: function(xhr, status) {
      }
   });
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

/* Google Channel API stuff */

var channel = null;
var socket = null;
var channelToken = null;
var finalClose = false;

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
   // alert("channelOnMessage: Json.kind is " + json.kind);
   if (json.kind == "ready")
      // The opponent is ready and a new game has been created:
      // navigate to it
      goToGame(json.game);
}

function channelOnError(err) {
   /* Act on err.code and err.description here */
   // alert("Channel error: " + err.code + "," + err.description);
}

function newChannel(json) {
   /* Ajax callback, called when the server has issued a new channel token */
   if (json && json.result === 0) {
      // No error: get the new token and reopen the channel
      openChannel(json.token);
   }
}

function channelOnClose() {
   /* Channel expired: Ask for a new channel from the server */
   // alert("Channel closed: calling newchannel()");
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
   /* Called when the page is displayed or refreshed */

   /* Enable the close button in the user info dialog */
   $("#wait-cancel").click(closeAndCleanUp);

   /* Call initialization that requires variables coming from the server */
   lateInit();

}

