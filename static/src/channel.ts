/*

   Channel.ts

   Utility functions for working with Firebase

   Copyright (C) 2021 Miðeind ehf.
   Original author: Vilhjálmur Þorsteinsson

   The GNU Affero General Public License, version 3, applies to this software.
   For further information, see https://github.com/mideind/Netskrafl

*/

export { loginFirebase, attachFirebaseListener, detachFirebaseListener };

declare namespace firebase {
  export { auth, database };
};

var auth: any;
var database: any;

function loginFirebase(token: string, userId: string, onLoginFunc?: () => void) {
   // Log in to Firebase using the provided custom token
   if (onLoginFunc !== undefined) {
      // Register our login function to execute once the user login is done
      firebase.auth().onAuthStateChanged(
         (user: boolean) => {
            if (user) {
               // User is signed in
               onLoginFunc();
            } else {
               // No user is signed in
            }
         }
      );
   }
   firebase.auth()
      .signInWithCustomToken(token)
      .then(() => initPresence(userId))
      .catch((error: { code: string; message: string; }) => {
         console.log('Firebase login failed, error code: ', error.code);
         console.log('Error message: ', error.message);
      });
}

function initPresence(userId: string) {
   // Ensure that this user connection is recorded in Firebase
   const db = firebase.database();
   const connectedRef = db.ref('.info/connected');
   // Create a unique connection entry for this user
   const connectionPath = 'connection/' + userId;
   const userRef = db.ref(connectionPath).push();
   connectedRef.on('value', (snapshot: any) => {
      if (snapshot.val()) {
         // We're connected (or reconnected)
         // When I disconnect, remove this entry
         userRef.onDisconnect().remove();
         // Set presence
         userRef.set(true);
      }
      else
         // Unset presence
         userRef.set(false);
   });
}

function attachFirebaseListener(
   path: string, func: (json: any, firstAttach: boolean) => void
) {
   // Attach a message listener to a Firebase path
   let cnt = 0;
   firebase.database()
      .ref(path)
      .on('value', function(snapshot: any) {
         // Note: we need function() here for proper closure
         // The cnt variable is used to tell the listener whether it's being
         // called upon the first attach or upon a later data change
         cnt++;
         const json = snapshot.val();
         if (json) {
            func(json, cnt == 1);
         }
      });
}

function detachFirebaseListener(path: string) {
   // Detach a message listener from a Firebase path
   firebase.database().ref(path).off();
}

