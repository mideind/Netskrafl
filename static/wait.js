/*

   Wait.js
   Client-side script for wait.html,
   a page displated while waiting for a time-limited game to start

   Author: Vilhjalmur Thorsteinsson, 2015

*/

/* Google Channel API stuff */

var channel = null;
var socket = null;
var channelToken = null;

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
   if (json.kind == "ready") {
      // The opponent is ready: start a game
      // !!! TBD
   }
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
   serverQuery("newchannel", { user: userId(), oldch: channelToken }, newChannel);
   channelToken = null;
   channel = null;
   socket = null;
}

function initWait() {
   /* Called when the page is displayed or refreshed */

   /* Enable the close button in the user info dialog */
   $("#wait-cancel").click(cancelWait);

   /* Call initialization that requires variables coming from the server */
   lateInit();

}

