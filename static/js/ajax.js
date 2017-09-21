/*

   Ajax.js

   Utility functions for client-server communications via Ajax

   Copyright (C) 2015-2017 Miðeind ehf.
   Author: Vilhjalmur Thorsteinsson

   The GNU General Public License, version 3, applies to this software.
   For further information, see https://github.com/vthorsteinsson/Netskrafl

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

function nullCompleteFunc(xhr, status) {
   /* Null placeholder function for Ajax completion */
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

function serverQueryHtml(requestUrl, jsonData, selector, completeFunc, errorFunc) {
   /* Wraps a simple, standard Ajax request to the server */
   $.ajax({
      // The URL for the request
      url: requestUrl,

      // The data to send
      data: jsonData,

      // Whether this is a POST or GET request
      type: "POST",

      cache: false,

      // Code to run if the request succeeds;
      // the response is passed to the function
      success: function(result) { $(selector).html(result); if (!!completeFunc) completeFunc(); },

      // Code to run if the request fails; the raw request and
      // status codes are passed to the function
      // Code to run if the request fails; the raw request and
      // status codes are passed to the function
      error: (!errorFunc) ? errFunc : errorFunc

   });
}

