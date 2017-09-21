/*

   Channel.js

   Utility functions for working with Firebase

   Copyright (C) 2015-2017 Miðeind ehf.
   Author: Vilhjalmur Thorsteinsson

   The GNU General Public License, version 3, applies to this software.
   For further information, see https://github.com/vthorsteinsson/Netskrafl

*/

function loginFirebase(token) {
   // Log in to Firebase using the provided custom token
   firebase.auth()
      .signInWithCustomToken(token)
      .catch(function(error) {
         console.log('Login failed!', error.code);
         console.log('Error message: ', error.message);
      });
}

function initPresence(userId) {
   // Ensure that this user connection is recorded in Firebase
   var connectedRef = firebase.database().ref('.info/connected');
   var connectionPath = 'connection/' + userId;
   connectedRef.on('value', function(snap) {
      if (snap.val() === true) {
         // We're connected (or reconnected)
         // Create a global connection entry
         var ref = firebase.database().ref(connectionPath);
         // Create a fresh entry under the user id
         var con = ref.push();
         // When I disconnect, remove this entry
         con.onDisconnect().remove();
         // Set presence
         con.set(true);
      }
   });
}

function attachFirebaseListener(path, func) {
   // Attach a message listener to a Firebase path
   firebase.database()
      .ref(path)
      .on('value', function(data) {
         if (!data)
            return;
         var json = data.val();
         if (json)
            func(json);
      });
}

