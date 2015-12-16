/*

   Channel.js

   Client-side script for wait.html,
   a page displated while waiting for a time-limited game to start

   Author: Vilhjalmur Thorsteinsson, 2015

*/

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

