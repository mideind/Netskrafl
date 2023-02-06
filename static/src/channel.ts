/*

  Channel.ts

  Utility functions for working with Firebase

  Copyright (C) 2023 Miðeind ehf.
  Original author: Vilhjálmur Þorsteinsson

  The Creative Commons Attribution-NonCommercial 4.0
  International Public License (CC-BY-NC 4.0) applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

*/

export {
  loginFirebase, attachFirebaseListener, detachFirebaseListener, logEvent
};

import { GlobalState } from "model";

declare namespace firebase {
  export { auth, database, analytics };
};

var auth: any;
var database: any;
var analytics: any;

function loginFirebase(state: GlobalState, onLoginFunc?: () => void) {
  const token = state.firebaseToken;
  const userId = state.userId;
  const locale = state.locale;
  // Log in to Firebase using the provided custom token
  // Register our login function to execute once the user login is done
  firebase.auth().onAuthStateChanged(
    (signedIn: boolean) => {
      if (signedIn) {
        // User is signed in
        if (onLoginFunc !== undefined) {
          onLoginFunc();
        }
        // For new users, log an additional signup event
        if (state.newUser)
          logEvent("sign_up",
            {
              locale: state.locale,
              method: state.loginMethod,
              userid: state.userId
            }
          );
        // And always log a login event
        logEvent("login",
          {
            locale: state.locale,
            method: state.loginMethod,
            userid: state.userId
          }
        );
      } else {
        // No user is signed in
      }
    }
  );
  firebase.auth()
    .signInWithCustomToken(token)
    .then(() => initPresence(userId, locale))
    .catch((error: { code: string; message: string; }) => {
      console.log('Firebase login failed, error code: ', error.code);
      console.log('Error message: ', error.message);
    });
}

function initPresence(userId: string, locale: string) {
  // Ensure that this user connection is recorded in Firebase
  const db = firebase.database();
  const connectedRef = db.ref('.info/connected');
  // Create a unique connection entry for this user
  const connectionPath = `connection/${locale}/${userId}`;
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
      userRef.remove();
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

function logEvent(ev: string, params: any) {
  // Log a Firebase analytics event
  firebase.analytics().logEvent(ev, params);
}
