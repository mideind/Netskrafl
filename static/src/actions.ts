/*

  Actions.ts

  Single page UI for Explo using the Mithril library

  Copyright (C) 2021 Miðeind ehf.
  Author: Vilhjálmur Þorsteinsson

  The Creative Commons Attribution-NonCommercial 4.0
  International Public License (CC-BY-NC 4.0) applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

  This file implements the Actions class.

*/

export { Actions, createRouteResolver };

import { Model, Params } from "model";

import { View } from "page";

import { m } from "mithril";

import {
  attachFirebaseListener, detachFirebaseListener, logEvent, loginFirebase
} from "channel";

import { ServerGame } from "game";

class Actions {

  model: Model;
  view: View;

  constructor(model: Model, view: View) {
    this.model = model;
    this.view = view;
    this.initMediaListener();
    this.initFirebaseListener();
    this.attachListenerToUser();
  }

  onNavigateTo(routeName: string, params: Params) {
    // We have navigated to a new route
    // If navigating to something other than help,
    // we need to have a logged-in user
    let model = this.model;
    this.view.boardScale = 1.0;
    model.routeName = routeName;
    model.params = params;
    if (routeName == "game") {
      // New game route: initiate loading of the game into the model
      if (model.game !== null) {
        this.detachListenerFromGame(model.game.uuid);
      }
      // If opening this game as a zombie, remove zombie status
      const deleteZombie = params.zombie === "1";
      // Load the game, and attach it to the Firebase listener once it's loaded
      model.loadGame(
        params.uuid,
        () => {
          this.attachListenerToGame(params.uuid);
          setTimeout(this.view.scrollMovelistToBottom);
        },
        deleteZombie
      );
      if (model.game !== null && model.game !== undefined)
        logEvent("game_open", { locale: model.game.locale, uuid: params.uuid });
    }
    else
    if (routeName == "review") {
      // A game review: detach listener, if any, and load
      // new game if necessary
      if (model.game !== null) {
        // !!! This may cause an extra detach - we assume that's OK
        this.detachListenerFromGame(model.game.uuid);
      }
      // Find out which move we should show in the review
      let moveParam: string = params.move || "0";
      // Start with move number 0 by default
      let move = parseInt(moveParam);
      if (isNaN(move) || !move || move < 0)
        move = 0;
      if (model.game === null || model.game.uuid != params.uuid)
        // Different game than we had before: load it, and then
        // fetch the best moves
        model.loadGame(params.uuid, () => {
          model.loadBestMoves(move);
          setTimeout(this.view.scrollMovelistToBottom);
        });
      else {
        if (model.game !== null) {
          // Already have the right game loaded:
          // Fetch the best moves and show them once they're available
          model.loadBestMoves(move);
        }
      }
      if (model.game !== null && model.game !== undefined)
        logEvent("game_review", { locale: model.game.locale, uuid: params.uuid });
    }
    else {
      // Not a game route: delete the previously loaded game, if any
      if (model.game !== null) {
        this.detachListenerFromGame(model.game.uuid);
        model.game.cleanup();
        model.game = null;
      }
      if (routeName == "help") {
        // Make sure that the help HTML is loaded upon first use
        model.loadHelp();
        logEvent("help", { locale: model.state.locale });
      }
      else
      if (routeName == "main") {
        // Force reload of lists
        // !!! TBD: This may not be necessary,
        // !!! if all Firebase notifications are acted upon
        model.gameList = null;
        model.userListCriteria = null;
        model.userList = null;
        model.challengeList = null;
        model.recentList = null;
      }
    }
  }

  onMoveMessage(json: ServerGame, firstAttach: boolean) {
    // Handle a move message from Firebase
    console.log("Move message received: " + JSON.stringify(json));
    this.model.handleMoveMessage(json, firstAttach);
  }

  onUserMessage(json: any, firstAttach: boolean) {
    // Handle a user message from Firebase
    console.log("User message received: " + JSON.stringify(json));
    this.model.handleUserMessage(json, firstAttach);
  }

  onChatMessage(
    json: { from_userid: string; game: string; msg: string; ts: string; },
    firstAttach: boolean
  ) {
    // Handle an incoming chat message
    if (firstAttach)
      console.log("First attach of chat: " + JSON.stringify(json));
    else {
      console.log("Chat message received: " + JSON.stringify(json));
      if (this.model.addChatMessage(json.game, json.from_userid, json.msg, json.ts)) {
        // A chat message was successfully added
        this.view.notifyChatMessage();
      }
    }
  }

  onFullScreen() {
    // Take action when min-width exceeds 768
    let state = this.model.state;
    if (!state.uiFullscreen) {
      state.uiFullscreen = true;
      this.view.notifyMediaChange();
      m.redraw();
    }
  }

  onMobileScreen() {
    let state = this.model.state;
    if (state.uiFullscreen !== false) {
      state.uiFullscreen = false;
      this.view.notifyMediaChange();
      m.redraw();
    }
  }

  onLandscapeScreen() {
    let state = this.model.state;
    if (!state.uiLandscape) {
      state.uiLandscape = true;
      this.view.notifyMediaChange();
      m.redraw();
    }
  }

  onPortraitScreen() {
    let state = this.model.state;
    if (state.uiLandscape !== false) {
      state.uiLandscape = false;
      this.view.notifyMediaChange();
      m.redraw();
    }
  }

  mediaMinWidth667(mql: MediaQueryList) {
    if (mql.matches) {
      // Take action when min-width exceeds 667
      // (usually because of rotation from portrait to landscape)
      // The board tab is not visible, so the movelist is default
      this.onLandscapeScreen();
    }
    else {
      // min-width is below 667
      // (usually because of rotation from landscape to portrait)
      // Make sure the board tab is selected
      this.onPortraitScreen();
    }
  }

  mediaMinWidth768(mql: MediaQueryList) {
    if (mql.matches) {
      this.onFullScreen();
    }
    else {
      this.onMobileScreen();
    }
  }

  initMediaListener() {
    // Install listener functions for media changes

    function addEventListener(mql: MediaQueryList, func: (ev: MediaQueryListEvent) => void) {
      // Hack to make addEventListener work on older Safari platforms
      try {
        // Chrome & Firefox
        mql.addEventListener('change', func, { passive: true });
      } catch (e1) {
        try {
          // Safari
          mql.addListener(func);
        } catch (e2) {
          console.error(e2);
        }
      }
    }

    let mql: MediaQueryList = window.matchMedia("(min-width: 667px)");
    let view = this;
    if (mql) {
      this.mediaMinWidth667(mql);
      addEventListener(mql, function (ev: MediaQueryListEvent) {
          view.mediaMinWidth667(this);
        }
      );
    }
    mql = window.matchMedia("(min-width: 768px)");
    if (mql) {
      this.mediaMinWidth768(mql);
      addEventListener(mql, function (ev: MediaQueryListEvent) {
          view.mediaMinWidth768(this);
        }
      );
    }
  }

  initFirebaseListener() {
    // Sign into Firebase with the token passed from the server
    loginFirebase(this.model.state);
  }

  attachListenerToUser() {
    let state = this.model.state;
    if (state.userId)
      attachFirebaseListener('user/' + state.userId,
        (json, firstAttach) => this.onUserMessage(json, firstAttach)
      );
  }

  detachListenerFromUser() {
    // Stop listening to Firebase notifications for the current user
    let state = this.model.state;
    if (state.userId)
      detachFirebaseListener('user/' + state.userId);
  }

  attachListenerToGame(uuid: string) {
    // Listen to Firebase events on the /game/[gameId]/[userId] path
    let state = this.model.state;
    const basepath = 'game/' + uuid + "/" + state.userId + "/";
    // New moves
    attachFirebaseListener(basepath + "move",
      (json, firstAttach) => this.onMoveMessage(json, firstAttach)
    );
    // New chat messages
    attachFirebaseListener(basepath + "chat",
      (json, firstAttach) => this.onChatMessage(json, firstAttach)
    );
  }

  detachListenerFromGame(uuid: string) {
    // Stop listening to Firebase events on the /game/[gameId]/[userId] path
    let state = this.model.state;
    const basepath = 'game/' + uuid + "/" + state.userId + "/";
    detachFirebaseListener(basepath + "move");
    detachFirebaseListener(basepath + "chat");
  }

} // class Actions

function createRouteResolver(actions: Actions) {

  // Return a map of routes to onmatch and render functions

  let model = actions.model;
  let view = actions.view;
  // let state = model.state;

  return model.paths.reduce((acc, item) => {
    acc[item.route] = {

      // Navigating to a new route (passed in the second parameter)
      onmatch: (params: Params, _: string) => {
        // Automatically close all dialogs
        view.popAllDialogs();
        actions.onNavigateTo(item.name, params);
      },

      // Render a view on a model
      render: () => { return view.appView(); }

    };
    return acc;
  }, {});
}

