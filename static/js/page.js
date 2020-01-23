/*

	Page.js

	Single page UI for Netskrafl using the Mithril library

  Copyright (C) 2020 Miðeind ehf.
  Author: Vilhjálmur Þorsteinsson

  The GNU General Public License, version 3, applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

  This UI is built on top of Mithril (https://mithril.js.org), a lightweight,
  straightforward JavaScript single-page reactive UI library.

  The page is structured into models, actions and views,
  cf. https://github.com/pakx/the-mithril-diaries/wiki/Basic-App-Structure

*/

/*
  global m:false, Promise:false, $state:false, Game:false,
  loginFirebase, attachFirebaseListener, detachFirebaseListener,
  toVector, coord
*/

/* eslint-disable indent */
/* eslint-disable no-console */
/* eslint-disable no-unused-vars */

var main = (function() {

"use strict";

// Constants

var RACK_SIZE = 7;
var BAG_TILES_PER_LINE = 19;
var BLANK_TILES_PER_LINE = 6;
var LEGAL_LETTERS = "aábdðeéfghiíjklmnoóprstuúvxyýþæö";
var ROUTE_PREFIX = "/page#!";
var ROUTE_PREFIX_LEN = ROUTE_PREFIX.length;
var BOARD_PREFIX = "/board?game=";
var BOARD_PREFIX_LEN = BOARD_PREFIX.length;
var MAX_CHAT_MESSAGES = 250; // Max number of chat messages per game

function main() {
  // The main UI entry point, called from page.html

  var
    settings = getSettings(),
    model = createModel(settings),
    view = createView(),
    actions = createActions(model, view),
    routeResolver = createRouteResolver(model, actions, view),
    defaultRoute = settings.defaultRoute,
    root = document.getElementById("container");

  // Run the Mithril router
  m.route(root, defaultRoute, routeResolver);
}

function getSettings() {
  // Returns an app-wide settings object
  var
    paths = [
      { name: "main", route: "/main", mustLogin: true },
      { name: "login", route: "/login", mustLogin: false },
      { name: "help", route: "/help", mustLogin: false },
      { name: "game", route: "/game/:uuid", mustLogin: true },
      { name: "review", route: "/review/:uuid", mustLogin: true }
    ];
  return {
    paths: paths,
    defaultRoute: paths[0].route
  };
}

function createModel(settings) {

  return {
    paths: settings.paths.slice(),
    // The routeName will be "login", "main", "game"...
    routeName: undefined,
    // Eventual parameters within the route URL, such as the game uuid
    params: undefined,
    // The current game being displayed, if any
    game: null,
    // The current game list
    gameList: null,
    // The current challenge list
    challengeList: null,
    // Recent games
    recentList: null,
    // The currently displayed user list
    userListCriteria: null,
    userList: null,
    // The user's own statistics
    ownStats: null,
    // The current user information being edited, if any
    user: null,
    userErrors: null,
    // The help screen contents
    helpHTML: null,
    // Outstanding requests
    spinners: 0,
    // The index of the game move being reviewed, if any
    reviewMove: null,
    // The best moves available at this stage, if reviewing game
    bestMoves: null,
    // Model methods
    loadGame: loadGame,
    loadGameList: loadGameList,
    loadChallengeList: loadChallengeList,
    loadRecentList: loadRecentList,
    loadUserRecentList: loadUserRecentList,
    loadUserList: loadUserList,
    loadOwnStats: loadOwnStats,
    loadUserStats: loadUserStats,
    loadPromoContent: loadPromoContent,
    loadBestMoves: loadBestMoves,
    loadHelp: loadHelp,
    loadUser: loadUser,
    saveUser: saveUser,
    newGame: newGame,
    modifyChallenge: modifyChallenge,
    markFavorite: markFavorite,
    addChatMessage: addChatMessage,
    handleUserMessage: handleUserMessage,
    handleMoveMessage: handleMoveMessage
  };

  function loadGame(uuid, funcComplete) {
    // Fetch a game state from the server, given a uuid
    console.log("Initiating load of game " + uuid);
    m.request({
      method: "POST",
      url: "/gamestate",
      body: { game: uuid }
    })
    .then(function(result) {
      this.game = null;
      this.reviewMove = null;
      this.bestMoves = null;
      if (!result.ok) {
        console.log("Game " + uuid + " could not be loaded");
      }
      else {
        this.game = new Game(uuid, result.game);
        // Successfully loaded: call the completion function, if given
        // (this usually attaches the Firebase event listener)
        if (funcComplete !== undefined)
          funcComplete();
        if (!$state.uiFullscreen)
          // Mobile UI: show board tab
          this.game.setSelectedTab("board");
      }
    }.bind(this));
  }

  function loadGameList() {
    // Load the list of currently active games for this user
    this.gameList = undefined; // Loading in progress
    m.request({
      method: "POST",
      url: "/gamelist"
    })
    .then(function(json) {
      if (!json || json.result !== 0) {
        // An error occurred
        this.gameList = null;
        return;
      }
      this.gameList = json.gamelist || [];
    }.bind(this));
  }

  function loadChallengeList() {
    // Load the list of current challenges (received and issued)
    this.challengeList = []; // Prevent concurrent loading
    m.request({
      method: "POST",
      url: "/challengelist"
    })
    .then(function(json) {
      if (!json || json.result !== 0) {
        // An error occurred
        this.challengeList = null;
        return;
      }
      this.challengeList = json.challengelist;
    }.bind(this));
  }

  function loadRecentList() {
    // Load the list of recent games for this user
    this.recentList = []; // Prevent concurrent loading
    m.request({
      method: "POST",
      url: "/recentlist",
      body: { versus: null, count: 40 }
    })
    .then(function(json) {
      if (!json || json.result !== 0) {
        // An error occurred
        this.recentList = null;
        return;
      }
      this.recentList = json.recentlist;
    }.bind(this));
  }

  function loadUserRecentList(userid, versus, readyFunc) {
    // Load the list of recent games for the given user
    m.request({
      method: "POST",
      url: "/recentlist",
      body: { user: userid, versus: versus, count: 40 }
    })
    .then(readyFunc);
  }

  function loadUserList(criteria, activateSpinner) {
    // Load a list of users according to the given criteria
    if (criteria.query == "search" && criteria.spec == "") {
      // Optimize by not sending an empty search query to the server,
      // since it always returns an empty list
      this.userList = [];
      this.userListCriteria = criteria;
      m.redraw(); // Call this explicitly as we're not calling m.request()
      return;
    }
    this.userList = undefined;
    this.userListCriteria = undefined; // Marker to prevent concurrent loading
    if (activateSpinner)
      // This will show a spinner overlay, disabling clicks on
      // all underlying controls
      this.spinners++;
    var url = "/userlist";
    var data = criteria;
    if (criteria.query == "elo") {
      // Kludge to make the Elo rating list appear as
      // just another type of user list
      url = "/rating";
      data = { kind: criteria.spec };
    }
    m.request({
      method: "POST",
      url: url,
      body: data
    })
    .then(function(json) {
      if (activateSpinner)
        // Remove spinner overlay, if present
        this.spinners--;
      if (!json || json.result !== 0) {
        // An error occurred
        this.userList = null;
        this.userListCriteria = null;
        return;
      }
      this.userList = json.userlist || json.rating;
      this.userListCriteria = criteria;
    }.bind(this));
  }

  function loadOwnStats() {
    // Load statistics for the current user
    this.ownStats = { };
    m.request({
      method: "POST",
      url: "/userstats",
      body: { } // Current user is implicit
    })
    .then(function(json) {
      if (!json || json.result !== 0) {
        // An error occurred
        this.ownStats = null;
        return;
      }
      this.ownStats = json;
    }.bind(this));
  }

  function loadUserStats(userid, readyFunc) {
    // Load statistics for the given user
    m.request({
      method: "POST",
      url: "/userstats",
      body: { user: userid }
    })
    .then(readyFunc);
  }

  function loadPromoContent(key, readyFunc) {
    // Load HTML content for promo dialog
    m.request({
      method: "POST",
      url: "/promo",
      body: { key: key },
      responseType: "text",
      deserialize: function(str) { return str; }
    })
    .then(readyFunc);
  }

  function loadBestMoves(move) {
    // Load the best moves available at a given state in a game
    if (!this.game || !this.game.uuid)
      return;
    if (!move) {
      this.reviewMove = null;
      this.bestMoves = null;
      this.game.setRack([]);
      this.game.placeTiles(0);
      return;
    }
    // Don't display navigation buttons while fetching
    // best moves
    this.reviewMove = 0;
    m.request({
      method: "POST",
      url: "/bestmoves",
      body: { game: this.game.uuid, move: move }
    })
    .then(function(json) {
      if (!json || json.result !== 0) {
        this.reviewMove = null;
        this.bestMoves = null;
        return;
      }
      this.reviewMove = json.move_number;
      this.bestMoves = json.best_moves;
      this.game.setRack(json.player_rack);
      // Populate the board cells with only the tiles
      // laid down up and until the indicated move
      this.game.placeTiles(this.reviewMove);
    }.bind(this));
  }

  function loadHelp() {
    // Load the help screen HTML from the server
    // (this is done the first time the help is displayed)
    if (this.helpHTML !== null)
      return; // Already loaded
    m.request({
      method: "GET",
      url: "/rawhelp",
      responseType: "text",
      deserialize: function(str) { return str; }
    })
    .then(function(result) {
      this.helpHTML = result;
    }.bind(this));
  }

  function loadUser(activateSpinner) {
    // Fetch the preferences of the currently logged in user, if any
    this.user = undefined;
    if (activateSpinner)
      // This will show a spinner overlay, disabling clicks on
      // all underlying controls
      this.spinners++;
    m.request({
      method: "POST",
      url: "/loaduserprefs"
    })
    .then(function(result) {
      if (activateSpinner)
        this.spinners--;
      if (!result.ok) {
        console.log("Unable to load user preferences");
        this.user = null;
        this.userErrors = null;
      }
      else {
        console.log("User preferences loaded");
        this.user = result.userprefs;
        this.userErrors = null;
      }
    }.bind(this));
  }

  function saveUser(successFunc) {
    // Update the preferences of the currently logged in user, if any
    m.request({
      method: "POST",
      url: "/saveuserprefs",
      body: this.user
    })
    .then(function(result) {
      if (result.ok) {
        // User preferences modified successfully on the server:
        // update the state variables that we're caching
        $state.userNick = this.user.nickname;
        $state.beginner = this.user.beginner;
        $state.fairPlay = this.user.fairplay;
        $state.newBag = this.user.newbag;
        // Give the game instance a chance to update its state
        if (this.game !== null)
          this.game.notifyUserChange();
        // Complete: call success function
        if (successFunc !== undefined)
          successFunc();
        // Reset errors
        this.userErrors = null;
        // Ensure that a fresh instance is loaded next time
        this.user = null;
      }
      else {
        // Error saving user prefs: show details, if available
        this.userErrors = result.err || null;
      }
    }.bind(this));
  }

  function newGame(oppid, reverse) {
    // Ask the server to initiate a new game against the given opponent
    m.request({
      method: "POST",
      url: "/initgame",
      body: { opp: oppid, rev: reverse }
    })
    .then(function(json) {
      if (json.ok) {
        // Go to the newly created game
        m.route.set("/game/" + json.uuid);
      }
    }.bind(this));
  }

  function modifyChallenge(parameters) {
    // Reject or retract a challenge
    m.request({
      method: "POST",
      url: "/challenge",
      body: parameters
    })
    .then(function(json) {
      if (json.result === 0)
        this.loadChallengeList();
    }.bind(this));
  }

  function markFavorite(userId, status) {
    // Mark or de-mark a user as a favorite
    m.request({
      method: "POST",
      url: "/favorite",
      body: { destuser: userId, action: status ? "add" : "delete" }
    })
    .then(function() {});
  }

  function addChatMessage(game, from_userid, msg, ts) {
    // Add a chat message to the game's chat message list
    if (this.game && this.game.uuid == game) {
      this.game.addChatMessage(from_userid, msg, ts);
      return true;
    }
    return false;
  }

  function handleUserMessage(json) {
    // Handle an incoming Firebase user message
    this.challengeList = null; // Reload challenge list
    this.gameList = null; // Reload game list
    m.redraw();
  }

  function handleMoveMessage(json) {
    // Handle an incoming Firebase move message
    if (this.game) {
      this.game.update(json);
      m.redraw();
    }
  }

}

function createView() {

  // Start a blinker interval function
  window.setInterval(blinker, 500);

  // The view interface exposes only the vwApp view function.
  // Additionally, a view instance has a current dialog window stack.

  // Map of available dialogs
  var dialogViews = {
    "userprefs":
      function(model, actions, args) {
        return vwUserPrefs.call(this, model, actions);
      },
    "userinfo":
      function(model, actions, args) {
        return vwUserInfo.call(this, model, actions, args);
      },
    "challenge":
      function(model, actions, args) {
        return vwChallenge.call(this, model, actions, args);
      },
    "promo":
      function(model, actions, args) {
        return vwPromo.call(this, model, actions, args);
      },
    "spinner":
      function(model, actions, args) {
        return vwSpinner.call(this, model, actions);
      }
  };

  return {
    appView: vwApp,
    dialogStack: [],
    dialogViews: dialogViews,
    pushDialog: pushDialog,
    popDialog: popDialog,
    popAllDialogs: popAllDialogs,
    notifyMediaChange: notifyMediaChange,
    notifyChatMessage: notifyChatMessage,
    startSpinner: startSpinner,
    stopSpinner: stopSpinner,
    isDialogShown: isDialogShown,
    showUserInfo: showUserInfo
  };

  function vwApp(model, actions) {
    // Select the view based on the current route
    // Display the appropriate content for the route,
    // also considering active dialogs
    var views = [];
    var move;
    switch (model.routeName) {
      case "login":
        views.push(vwLogin.call(this, model, actions));
        break;
      case "main":
        views.push(vwMain.call(this, model, actions));
        break;
      case "game":
        views.push(vwGame.call(this, model, actions));
        break;
      case "review":
        views.push(vwReview.call(this, model, actions));
        break;
      case "help":
        // A route parameter of ?q=N goes directly to the FAQ number N
        // A route parameter of ?tab=N goes directly to tab N (0-based)
        views.push(
          vwHelp.call(this, model, actions,
            m.route.param("tab"),
            m.route.param("faq")
          )
        );
        break;
      default:
        console.log("Unknown route name: " + model.routeName);
        return m("div", "Þessi vefslóð er ekki rétt");
    }
    // Push any open dialogs
    for (var i = 0; i < this.dialogStack.length; i++) {
      var dialog = this.dialogStack[i];
      var v = this.dialogViews[dialog.name];
      if (v === undefined)
        console.log("Unknown dialog name: " + dialog.name);
      else
        views.push(v.call(this, model, actions, dialog.args));
    }
    // Overlay a spinner, if active
    if (model.spinners > 0)
      views.push(vwSpinner.call(this, model, actions));
    return views;
  }

  // Dialog support

  function pushDialog(dialogName, dialogArgs) {
    this.dialogStack.push({ name: dialogName, args : dialogArgs });
    m.redraw(); // Ensure that the dialog is shown
  }

  function popDialog() {
    if (this.dialogStack.length > 0) {
      this.dialogStack.pop();
      m.redraw();
    }
  }

  function popAllDialogs() {
    if (this.dialogStack.length > 0) {
      this.dialogStack = [];
      m.redraw();
    }
  }

  function isDialogShown() {
    return this.dialogStack.length > 0;
  }

  function notifyMediaChange(model) {
    // The view is changing, between mobile and fullscreen
    // and/or between portrait and landscape: ensure that
    // we don't end up with a selected game tab that is not visible
    if (model.game) {
      if ($state.uiFullscreen || $state.uiLandscape) {
        // In this case, there is no board tab:
        // show the movelist
        model.game.sel = "movelist";
        scrollMovelistToBottom();
      }
      else {
        // Mobile: we default to the board tab
        model.game.sel = "board";
      }
    }
    // When switching between landscape and portrait,
    // close all current dialogs
    this.popAllDialogs();
  }

  function notifyChatMessage() {
    // A fresh chat message has arrived
    m.redraw();
  }

  function showUserInfo(userid, nick, fullname) {
    // Show a user info dialog
    this.pushDialog("userinfo", { userid: userid, nick: nick, fullname: fullname });
  }

  // Globally available controls

  function vwInfo() {
    // Info icon, invoking the help screen
    return m(".info",
      { title: "Upplýsingar og hjálp" },
      m(m.route.Link,
        { href: "/help", class: "iconlink" },
        glyph("info-sign")
      )
    );
  }

  function vwUserId() {
    // User identifier at top right, opens user preferences
    if ($state.userId == "")
      // Don't show the button if there is no logged-in user
      return "";
    return m(".userid",
      {
        title: "Upplýsingar um leikmann",
        onclick: function(ev) {
          // Overlay the userprefs dialog
          this.pushDialog("userprefs");
          ev.preventDefault();
        }.bind(this)
      },
      [ glyph("address-book"), nbsp(), $state.userNick ]
    );
  }

  function vwLogo() {
    // The Netskrafl logo
    return m(".logo",
      m(m.route.Link,
        { href: '/main', class: "nodecorate" }, 
        m("img",
          {
            alt: 'Netskrafl',
            width: 46, height: 400,
            src: '/static/Netskrafl.png'
          }
        )
      )
    );
  }

  // Login screen

  function vwLogin(model, actions) {
    // Login dialog

    function vwLoginLarge() {
      // Full screen version of login page
      return [
        vwLogo(),
        vwInfo(),
        m(".loginform-large",
        [
          m(".loginhdr", "Velkomin í Netskrafl!"),
          m(".blurb", "Skemmtilegt | skerpandi | ókeypis"),
          m("div", { id: 'board-pic' }, 
            m("img",
              {
                width: 310, height: 300,
                src: '/static/Board.png'
              }
            )
          ),
          m(".welcome",
            [
              "Netskrafl er vettvangur ",
              m("b", "yfir 16.000 íslenskra skraflara"),
              " á netinu."
            ]
          ),
          m(".welcome", 
            "Netskrafl notar Google Accounts innskráningu, þá " +
            "sömu og er notuð m.a. í Gmail."
          ),
          m(".welcome", 
            "Netskrafl safnar hvorki persónuupplýsingum né geymir þær."
          ),
          m(".welcome",
            [
              "Þú getur alltaf fengið ",
              m(m.route.Link,
                { href: '/help' },
                "hjálp"
              ),
              " með því að smella á ",
              m(m.route.Link,
                { href: '/help' },
                [ "bláa", nbsp(), nbsp(), glyph("info-sign"), " - merkið" ]
              ),
              " hér til vinstri."
            ]
          ),
          m("div", { style: { float: "right" } },
            m("button.login",
              {
                type: 'submit',
                onclick: function(ev) {
                  window.location.href = "/login"; // !!! TODO: FIXME
                }
              },
              [ glyph("ok"), nbsp(), nbsp(), "Skrá mig inn" ]
            )
          )
        ]
      )];
    }

    function vwLoginSmall() {
      // Mobile version of login page
      return m(".loginform-small",
        [
          m("div", 
            { id: 'logo-pic' }, 
            m("img",
              {
                height: 375, width: 375,
                src: '/static/LoginLogo750.png'
              }
            )
          ),
          m(".blurb", "Skemmtilegt | skerpandi | ókeypis"),
          m("div", { style: { "text-align": "center" } }, 
            m("button.login",
              {
                type: 'submit',
                onclick: function(ev) {
                  window.location.href = "/login"; // !!! TODO: FIXME
                }
              },
              [ glyph("ok"), nbsp(), nbsp(), "Skrá mig inn" ]
            )
          )
        ]
      );
    }

    return $state.uiFullscreen ? vwLoginLarge() : vwLoginSmall();
  }

  // A control that rigs up a tabbed view of raw HTML

  function vwTabsFromHtml(html, id, tabNumber, createFunc) {
    // The function assumes that 'this' is the current view object
    if (!html)
      return "";
    var view = this;
    return m("div",
      {
        oninit: function(vnode) { vnode.state.selected = tabNumber || 1; },
        oncreate: makeTabs.bind(view, id, createFunc, true)
        /* onupdate: updateSelection */
      },
      m.trust(html)
    );
  }

  // Help screen

  function vwHelp(model, actions, tabNumber, faqNumber) {

    function wireQuestions(vnode) {
      // Clicking on a question brings the corresponding answer into view
      // This is achieved by wiring up all contained a[href="#faq-*"] links

      function showAnswer(href, ev) {
        // this points to the vnode
        this.state.selected = 1; // FAQ tab
        this.dom.querySelector(href).scrollIntoView();
        ev.preventDefault();
      }

      var i, anchors = vnode.dom.querySelectorAll("a");
      for (i = 0; i < anchors.length; i++) {
        var href = anchors[i].getAttribute("href");
        if (href.slice(0, 5) == "#faq-")
          // This is a direct link to a question: wire it up
          anchors[i].onclick = showAnswer.bind(vnode, href);
      }
      if (faqNumber !== undefined) {
        // Go to the FAQ tab and scroll the requested question into view
        selectTab(vnode, 1);
        vnode.state.selected = 1; // FAQ tab
        vnode.dom.querySelector("#faq-" + faqNumber.toString()).scrollIntoView();
      }
    }

    // Output literal HTML obtained from rawhelp.html on the server
    return [
      vwLogo(),
      vwUserId.call(this),
      m("main",
        vwTabsFromHtml.call(this, model.helpHTML, "tabs", tabNumber, wireQuestions)
      )
    ];
  }

  // User preferences screen

  function vwUserPrefsDialog(model) {

    var user = model.user;
    var err = model.userErrors || { };
    var view = this;

    function vwErrMsg(propname) {
      // Show a validation error message returned from the server
      return err.hasOwnProperty(propname) ?
        m(".errinput", [ glyph("arrow-up"), nbsp(), err[propname] ]) : "";
    }

    function playAudio(elemId) {
      // Play an audio file
      var sound = document.getElementById(elemId);
      if (sound)
        sound.play();
    }

    // A nice graphical toggler control

    function vwToggler(id, state, tabindex, opt1, opt2, func) {

      function doToggle(elemId, func) {
        // Perform the toggling, on a mouse click or keyboard input (space bar)
        var cls1 = document.querySelector("#" + elemId + " #opt1").classList;
        var cls2 = document.querySelector("#" + elemId + " #opt2").classList;
        cls1.toggle("selected");
        cls2.toggle("selected");
        if (func !== undefined && cls2.contains("selected"))
          // Toggling the swith to ON and we have an associated function:
          // call it
          func();
      }

      return [
        m("input.checkbox." + id,
          {
            type: 'checkbox',
            id: id,
            name: id,
            checked: state,
            value: 'True'
          }
        ),
        m(".toggler",
          {
            id: id + '-toggler',
            tabindex: tabindex,
            onclick: function(ev) {
              doToggle(id + "-toggler", func);
            },
            onkeypress: function(ev) {
              if (ev.keyCode === 0 || ev.keyCode == 32)
                doToggle(id + "-toggler", func);
            }
          },
          [
            m(".option" + (state ? "" : ".selected"), { id: "opt1" }, opt1),
            m(".option" + (state ? ".selected" : ""), { id: "opt2" }, opt2)
          ]
        )
      ];
    }

    function getToggle(elemId) {
      var cls2 = document.querySelector("#" + elemId + "-toggler #opt2").classList;
      return cls2.contains("selected");
    }

    function validate() {
      // Move data back to the model.user object
      // before sending it to the server
      user.nickname = getInput("nickname");
      user.full_name = getInput("full_name");
      user.email = getInput("email");
      user.audio = getToggle("audio");
      user.fanfare = getToggle("fanfare");
      user.beginner = getToggle("beginner");
      user.newbag = getToggle("newbag");
      user.fairplay = getToggle("fairplay");
      // When done, pop the current dialog
      model.saveUser(function() { this.popDialog(); }.bind(view));
    }

    function initFocus(vnode) {
      // Set the focus on the nickname field when the dialog is displayed
      vnode.dom.querySelector("#nickname").focus();
    }

    return m(".modal-dialog",
      {
        id: 'user-dialog',
        oncreate: initFocus
        // onupdate: initFocus
      },
      m(".ui-widget.ui-widget-content.ui-corner-all", { id: 'user-form' },
        [
          m(".loginhdr", [ glyph("address-book"), " Upplýsingar um leikmann" ]),
          m("div", 
            m("form", { action: '', id: 'frm1', method: 'post', name: 'frm1' },
              [
                m(".dialog-spacer",
                  [
                    m("span.caption", "Einkenni:"),
                    m(TextInput,
                      {
                        initialValue: user.nickname || "",
                        class: "username",
                        maxlength: 15,
                        id: "nickname"
                      }
                    ),
                    nbsp(), m("span", { style: { color: "red" } }, "*")
                  ]
                ),
                m(".explain", "Verður að vera útfyllt"),
                vwErrMsg("nickname"),
                m(".dialog-spacer",
                  [
                    m("span.caption", "Fullt nafn:"),
                    m(TextInput,
                      {
                        initialValue: user.full_name || "",
                        class: "fullname",
                        maxlength: 32,
                        id: "full_name"
                      }
                    )
                  ]
                ),
                m(".explain", "Valfrjálst - sýnt í notendalistum Netskrafls"),
                vwErrMsg("full_name"),
                m(".dialog-spacer",
                  [
                    m("span.caption", "Tölvupóstfang:"),
                    m(TextInput,
                      {
                        initialValue: user.email || "",
                        class: "email",
                        maxlength: 32,
                        id: "email"
                      }
                    )
                  ]
                ),
                m(".explain", "Ef póstfang er gefið upp mun Netskrafl geta " +
                  "sent tölvupóst þegar þú átt leik"),
                vwErrMsg("email"),
                m(".dialog-spacer",
                  [
                    m("span.caption", "Hljóðmerki:"),
                    vwToggler("audio", user.audio, 4,
                      glyph("volume-off"), glyph("volume-up"),
                      function() { playAudio("your-turn"); }),
                    m("span.subcaption", "Lúðraþytur eftir sigur:"),
                    vwToggler("fanfare", user.fanfare, 5,
                      glyph("volume-off"), glyph("volume-up"),
                      function() { playAudio("you-win"); })
                  ]
                ),
                m(".explain", 
                  "Stillir hvort hljóðmerki heyrast t.d. þegar andstæðingur " +
                  "leikur og þegar sigur vinnst"
                ),
                m(".dialog-spacer",
                  [
                    m("span.caption", "Sýna reitagildi:"),
                    vwToggler("beginner", user.beginner, "6",
                      nbsp(), glyph("ok")),
                    m(".subexplain",
                      [
                        "Stillir hvort ",
                        m("strong", "minnismiði"),
                        " um margföldunargildi reita er sýndur við borðið"
                      ]
                    )
                  ]
                ),
                m(".dialog-spacer",
                  [
                    m("span.caption", "Nýi skraflpokinn:"),
                    vwToggler("newbag", user.newbag, 7, nbsp(), glyph("shopping-bag")),
                    m(".subexplain",
                      [
                        "Gefur til kynna hvort þú sért reiðubúin(n) að\nskrafla með ",
                        m("strong", "nýja íslenska skraflpokanum")
                      ]
                    )
                  ]
                ),
                m(".dialog-spacer",
                  [
                    m("span.caption", "Án hjálpartækja:"),
                    vwToggler("fairplay", user.fairplay, 8, nbsp(), glyph("edit")),
                    m(".subexplain",
                      [
                        "Með því að velja þessa merkingu lýsir þú því yfir " +
                        " að þú\nskraflir við aðra leikmenn ",
                        m("strong", "án stafrænna hjálpartækja"),
                        " af nokkru tagi"
                      ]
                    )
                  ]
                )
              ]
            )
          ),
          vwDialogButton("user-ok", "Vista", validate, glyph("ok"), 9),
          vwDialogButton("user-cancel", "Hætta við",
            function(ev) {
              this.popDialog();
              ev.preventDefault();
            }.bind(view),
            glyph("remove"), 10),
          vwDialogButton("user-logout", "Skrá mig út",
            function(ev) {
              window.location.href = user.logout_url;
              ev.preventDefault();
            },
            [ glyph("log-out"), nbsp(), "Skrá mig út" ], 11),
          user.friend ?
            vwDialogButton("user-unfriend", "Hætta sem vinur",
              function(ev) { /* !!! TBD */ },
              [ glyph("coffee-cup"), nbsp(), nbsp(), "Þú ert vinur Netskrafls!" ], 12
            )
          :
            vwDialogButton("user-friend", "Gerast vinur",
              function(ev) {
                // Invoke the friend promo dialog
                this.pushDialog("promo", { key: "friend" });
              }.bind(view),
              [ glyph("coffee-cup"), nbsp(), nbsp(), "Gerast vinur Netskrafls" ], 12
            )
        ]
      )
    );
  }

  function vwUserPrefs(model, actions) {
    if (model.user === null)
      model.loadUser(true); // Activate spinner while loading
    if (!model.user)
      // Nothing to edit (the spinner should be showing in this case)
      return "";
    return vwUserPrefsDialog.call(this, model);
  }

  function vwUserInfo(model, actions, args) {
    return m(UserInfoDialog,
      {
        model: model,
        view: this,
        userid: args.userid,
        nick: args.nick,
        fullname: args.fullname
      }
    );
  }

  function vwPromo(model, actions, args) {
    return m(PromoDialog,
      {
        model: model,
        view: this,
        key: args.key
      }
    );
  }

  function vwChallenge(model, actions, item) {
    // Show a dialog box for a new challenge being issued
    var manual = $state.hasPaid; // If paying user, allow manual challenges
    var fairPlay = item.fairplay && $state.fairPlay; // Both users are fair-play
    var oldBag = !item.newbag && !$state.newBag; // Neither user wants new bag
    return m(".modal-dialog",
      { id: 'chall-dialog', style: { visibility: 'visible' } }, 
      m(".ui-widget.ui-widget-content.ui-corner-all", { id: 'chall-form' },
        [
          m(".chall-hdr", 
            m("table", 
              m("tbody", 
                m("tr",
                  [
                    m("td", m("h1.chall-icon", glyph("hand-right"))),
                    m("td.l-border",
                      [
                        m(OnlinePresence, { id: "chall-online", userId : item.userid }),
                        m("h1", item.nick),
                        m("h2", item.fullname)
                      ]
                    )
                  ]
                )
              )
            )
          ),
          m("div", { style: { "text-align": "center" } },
            [
              m(".promo-fullscreen",
                [
                  m("p", [ m("strong", "Ný áskorun"), " - veldu lengd viðureignar:" ]),
                  m(MultiSelection,
                    { initialSelection: 0, defaultClass: 'chall-time' },
                    [
                      m("div", { id: 'chall-none', tabindex: 1 },
                        "Viðureign án klukku"
                      ),
                      m("div", { id: 'chall-10', tabindex: 2 },
                        [ glyph("time"), "2 x 10 mínútur" ]
                      ),
                      m("div", { id: 'chall-15', tabindex: 3 },
                        [ glyph("time"), "2 x 15 mínútur" ]
                      ),
                      m("div", { id: 'chall-20', tabindex: 4 },
                        [ glyph("time"), "2 x 20 mínútur" ]
                      ),
                      m("div", { id: 'chall-25', tabindex: 5 },
                        [ glyph("time"), "2 x 25 mínútur" ]
                      ),
                      m("div", { id: 'chall-30', tabindex: 6 },
                        [ glyph("time"), "2 x 30 mínútur" ]
                      )
                    ]
                  )
                ]
              ),
              m(".promo-mobile",
                [
                  m("p", m("strong", "Ný áskorun")),
                  m(".chall-time.selected", { id: 'extra-none', tabindex: 1 },
                    "Viðureign án klukku"
                  )
                ]
              )
            ]
          ),
          manual ? m("div", { id: "chall-manual" },
            [
              m("span.caption.wide",
                [
                  "Nota", m("strong", "handvirka véfengingu"),
                  m("br"), "(\"keppnishamur\")"
                ]
              ),
              m(".toggler[id='manual-toggler'][tabindex='7']",
                [
                  m(".option.selected[id='opt1']", m("span", nbsp())),
                  m(".option[id='opt2']", glyph("lightbulb"))
                ]
              )
            ]
          ) : "",
          fairPlay ? m("div", { id: "chall-fairplay" },
            [
              "Báðir leikmenn lýsa því yfir að þeir skrafla ",
              m("strong", "án stafrænna hjálpartækja"),
              " af nokkru tagi."
            ]
          ) : "",
          oldBag ? m("div", { id: "chall-oldbag" },
            m("table", 
              m("tr",
                [
                  m("td", glyph("exclamation-sign")),
                  m("td",
                    [ "Viðureign með", m("br"), m("strong", "gamla skraflpokanum") ]
                  )
                ]
              )
            )
          ) : "",
          m(DialogButton,
            {
              id: "chall-cancel",
              title: "Hætta við",
              tabindex: 8,
              onclick: function(ev) {
                this.popDialog();
                ev.preventDefault();
              }.bind(this),
            },
            glyph("remove")
          ),
          m(DialogButton,
            {
              id: "chall-ok",
              title: "Skora á",
              tabindex: 9,
              onclick: function(ev) {
                // Issue a new challenge
                var duration = document.querySelector("div.chall-time.selected").id.slice(6);
                if (duration == "none")
                  duration = 0;
                else
                  duration = parseInt(duration);
                item.chall = true;
                model.modifyChallenge(
                  {
                    destuser: item.userid,
                    action: "issue",
                    duration: duration,
                    fairplay: fairPlay,
                    newbag: !oldBag,
                    manual: manual
                  }
                );
                this.popDialog();
                ev.preventDefault();
              }.bind(this),
            },
            glyph("ok")
          )
        ]
      )
    );
  }

  // Main screen

  function vwMain(model, actions) {
    // Main screen with tabs

    var view = this;

    function vwMainTabs() {

      function vwMainTabHeader() {
        var numGames = 0;
        var numChallenges = 0;
        if (model.gameList)
          // Sum up games where it's the player's turn, as well as zombie games
          numGames = model.gameList.reduce(function(acc, item) {
            return acc + (item.my_turn || item.zombie ? 1 : 0);
          }, 0);
        if (model.challengeList)
          // Sum up received challenges
          numChallenges = model.challengeList.reduce(function(acc, item) {
            return acc + (item.received ? 1 : 0);
          }, 0);
        return m("ul",
          [
            m("li", 
              m("a[href='#tabs-1']",
                [
                  glyph("th"), m("span.tab-legend", "Viðureignir"), nbsp(),
                  m("span",
                    { id: 'numgames', style: numGames ? 'display: inline-block' : '' },
                    numGames
                  )
                ]
              )
            ),
            m("li", 
              m("a[href='#tabs-2']",
                [
                  glyph("hand-right"), m("span.tab-legend", "Áskoranir"), nbsp(),
                  m("span.opp-ready",
                    { id: 'numchallenges', style: numChallenges ? 'display: inline-block' : '' },
                    numChallenges
                  )
                ]
              )
            ),
            m("li", 
              m("a[href='#tabs-3']",
                [ glyph("user"), m("span.tab-legend", "Andstæðingar") ]
              )
            ),
            m("li.no-mobile-list", 
              m("a[href='#tabs-4']",
                [ glyph("bookmark"), m("span.tab-legend", "Ferill") ]
              )
            )
          ]
        );
      }

      function showUserInfo(userid, nick, fullname) {
        view.pushDialog("userinfo", { userid: userid, nick: nick, fullname: fullname });
      }

      function vwGamelist() {

        function vwList() {

          function viewGameList() {

            if (!model.gameList)
              return "";
            return model.gameList.map(function(item, i) {

              // Show a list item about a game in progress (or recently finished)

              function vwOpp() {
                var arg = item.oppid === null ? [ glyph("cog"), nbsp(), item.opp ] : item.opp;
                return m("span.list-opp", { title: item.fullname }, arg);
              }

              function vwTurn() {
                var turnText;
                var flagClass;
                if (item.my_turn) {
                  turnText = "Þú átt leik";
                  flagClass = "";
                }
                else
                if (item.zombie) {
                  turnText = "Viðureign lokið";
                  flagClass = ".zombie";
                }
                else {
                  turnText = item.opp + " á leik";
                  flagClass = ".grayed";
                }
                return m("span.list-myturn",
                  m("span.glyphicon.glyphicon-flag" + flagClass, { title: turnText })
                );
              }

              function vwOverdue() {
                if (item.overdue)
                  return glyph("hourglass",
                    { title: item.my_turn ? "Er að renna út á tíma" : "Getur þvingað fram uppgjöf" }
                  );
                return glyphGrayed("hourglass");
              }

              function vwTileCount() {
                var winLose = item.sc0 < item.sc1 ? ".losing" : "";
                return m(".tilecount",
                  m(".tc" + winLose, { style: { width: item.tile_count.toString() + "%" } })
                );
              }

              function gameUUID() {
                // Convert old-style /board?game=UUID URL to UUID
                if (item.url.slice(0, BOARD_PREFIX_LEN) == BOARD_PREFIX)
                  return item.url.slice(BOARD_PREFIX_LEN);
                // Otherwise, assume that item.url contains the UUID
                return item.url;
              }

              return m(".listitem" + (i % 2 === 0 ? ".oddlist" : ".evenlist"),
                [
                  m(m.route.Link,
                    { href: "/game/" + gameUUID() },
                    [
                      vwTurn(),
                      m("span.list-overdue", vwOverdue()),
                      m("span.list-ts-short", item.ts),
                      vwOpp()
                    ]
                  ),
                  m("span.list-info",
                    item.oppid === null ?
                      nbsp() :
                      m("span.usr-info",
                        {
                          title: "Skoða feril",
                          onclick: function(ev) {
                            // Show opponent track record
                            showUserInfo(item.oppid, item.opp, item.fullname);
                          },
                        },
                        ""
                      )
                  ),
                  m("span.list-s0", item.sc0),
                  m("span.list-colon", ":"),
                  m("span.list-s1", item.sc1),
                  m("span.list-tc", vwTileCount()),
                  m("span.list-manual",
                    item.manual ? glyph("lightbulb", { title: "Keppnishamur" }) : glyphGrayed("lightbulb")
                  )
                ]
              );
            });
          }

          if (model.gameList === null)
            model.loadGameList();
          return m("div", { id: 'gamelist' }, viewGameList());
        }

        function vwHint() {
          // Show some help if the user has no games in progress
          if (model.gameList === undefined || (model.gameList !== null && model.gameList.length > 0))
            // Either we have games in progress or the game list is being loaded
            return "";
          return m(".hint", { style: { display: "block" } },
            [
              m("p",
                [
                  "Ef þig vantar einhvern til að skrafla við, veldu flipann ",
                  m(m.route.Link,
                    { href: "/main?tab=2" },
                    [ glyph("user"), nbsp(), "Andstæðingar" ]
                  ),
                  " og skoraðu á tölvuþjarka - ",
                  glyph("cog"), nbsp(), m("b", "Amlóða"),
                  ", ",
                  glyph("cog"), nbsp(), m("b", "Miðlung"),
                  " eða ",
                  glyph("cog"), nbsp(), m("b", "Fullsterkan"),
                  " - eða veldu þér annan leikmann úr stafrófs\u00ADlistunum " + // Soft hyphen
                  " sem þar er að finna til að skora á."
                ]
              ),
              m("p",
                [
                  "Þú stofnar áskorun með því að smella á bendi-teiknið ",
                  glyph("hand-right", { style: { "margin-left": "6px", "margin-right": "6px" } }),
                  " vinstra megin við nafn andstæðingsins."
                ]
              ),
              m("p", 
                "Tölvuþjarkarnir eru ætíð reiðubúnir að skrafla og viðureign við þá " +
                " hefst strax. Aðrir leikmenn þurfa að samþykkja áskorun áður en viðureign hefst."
              ),
              m("p.no-mobile-block",
                [
                  m(m.route.Link, { href: "/help" }, "Hjálp"),
                  " má fá með því að smella á bláa ",
                  glyph("info-sign"), nbsp(), "-", nbsp(),
                  "teiknið hér til vinstri."
                ]
              ),
              m("p.no-mobile-block", 
                "Þú kemst alltaf aftur í þessa aðalsíðu með því að smella á " +
                "örvarmerkið efst vinstra megin við skraflborðið."
              )
            ]
          );
        }

        return [
          m(".listitem.listheader",
            [
              m("span.list-myturn", glyphGrayed("flag", { title: 'Átt þú leik?' } )),
              m("span.list-overdue", 
                glyphGrayed("hourglass", { title: 'Langt frá síðasta leik?' })
              ),
              m("span.list-ts-short", "Síðasti leikur"),
              m("span.list-opp", "Andstæðingur"),
              m("span.list-info-hdr", "Ferill"),
              m("span.list-scorehdr", "Staða"),
              m("span.list-tc", "Framvinda"),
              m("span.list-manual", glyphGrayed("lightbulb", { title: 'Keppnishamur' }))
            ]
          ),
          vwList(),
          vwHint()
        ];
      }

      function vwChallenges(showReceived) {

        function vwList() {

          function itemize(item, i) {

            // Generate a list item about a pending challenge (issued or received)

            function challengeDescription(json) {
               /* Return a human-readable string describing a challenge
                  according to the enclosed preferences */
               if (!json || json.duration === undefined || json.duration === 0)
                  /* Normal unbounded (untimed) game */
                  return "Venjuleg ótímabundin viðureign";
               return "Með klukku, 2 x " + json.duration.toString() + " mínútur";
            }

            function markChallenge(ev) {
              // Clicked the icon at the beginning of the line,
              // to decline a received challenge or retract an issued challenge
              var action = item.received ? "decline" : "retract";
              model.modifyChallenge({ destuser: item.userid, action: action });
              ev.preventDefault();
            }

            function clickReceived(ev) {
              // Clicked the hotspot area to accept a received challenge
              if (item.received)
                // Ask the server to create a new game and route to it
                model.newGame(item.userid, false);
              ev.preventDefault();
            }

            // var oppReady = !item.received && item.opp_ready;
            var descr = challengeDescription(item.prefs);

            return m(".listitem" + (i % 2 === 0 ? ".oddlist" : ".evenlist"),
              [
                m("span.list-icon",
                  { onclick: markChallenge },
                  item.received ?
                    glyph("thumbs-down", { title: "Hafna" })
                    :
                    glyph("hand-right", { title: "Afturkalla" })
                ),
                m(item.received ? "a" : "span",
                  {
                    href: "#",
                    onclick: clickReceived
                  },
                  [
                    m("span.list-ts", item.ts),
                    m("span.list-nick", { title: item.fullname }, item.opp),
                    m("span.list-chall",
                      [
                        item.prefs.fairplay ? m("span.fairplay-btn", { title: "Án hjálpartækja" }) : "",
                        item.prefs.manual ? m("span.manual-btn", { title: "Keppnishamur" }) : "",
                        descr
                      ]
                    )
                  ]
                ),
                m("span.list-info",
                  {
                    title: "Skoða feril",
                    // Show opponent track record
                    onclick: function(ev) { showUserInfo(item.userid, item.opp, item.fullname); }
                  },
                  m("span.usr-info", "")
                ),
                m("span.list-newbag", glyph("shopping-bag", { title: "Gamli pokinn" }, item.prefs.newbag)
                )
              ]
            );
          }

          var cList;
          if (!model.challengeList)
            cList = [];
          else
            cList = showReceived ?
              model.challengeList.filter(function(item) { return item.received; }) :
              model.challengeList.filter(function(item) { return !item.received; });

          return m("div",
            {
              id: showReceived ? 'chall-received' : 'chall-sent',
              oninit: function(vnode) {
                if (model.challengeList === null)
                  model.loadChallengeList();
              }
            },
            cList.map(itemize)
          );
        }

        if (showReceived)
          // Challenges received
          return [
            m(".listitem.listheader",
              [
                m("span.list-icon", glyphGrayed("thumbs-down", { title: 'Hafna' })),
                m("span.list-ts", "Hvenær"),
                m("span.list-nick", "Áskorandi"),
                m("span.list-chall", "Hvernig"),
                m("span.list-info-hdr", "Ferill"),
                m("span.list-newbag", glyphGrayed("shopping-bag", { title: 'Gamli pokinn' }))
              ]
            ),
            vwList()
          ];
        else
          // Challenges sent
          return [
            m(".listitem.listheader",
              [
                m("span.list-icon", glyphGrayed("hand-right", { title: 'Afturkalla' })),
                m("span.list-ts", "Hvenær"),
                m("span.list-nick", "Andstæðingur"),
                m("span.list-chall", "Hvernig"),
                m("span.list-info-hdr", "Ferill"),
                m("span.list-newbag", glyphGrayed("shopping-bag", { title: 'Gamli pokinn' }))
              ]
            ),
            vwList()
          ];
      }

      function vwRecentList() {

        function vwList() {
          if (model.recentList === null)
            model.loadRecentList();
          return m(RecentList,
            {
              id: "recentlist",
              recentList: model.recentList
            }
          );
        }

        return [
          m(".listitem.listheader",
            [
              m("span.list-win", glyphGrayed("bookmark", { title: 'Sigur' })),
              m("span.list-ts-short", "Viðureign lauk"),
              m("span.list-nick", "Andstæðingur"),
              m("span.list-scorehdr", "Úrslit"),
              m("span.list-elo-hdr",
                [
                  m("span.glyphicon.glyphicon-user.elo-hdr-left[title='Mennskir andstæðingar']"),
                  " Elo ",
                  m("span.glyphicon.glyphicon-cog.elo-hdr-right[title='Allir andstæðingar']")
                ]
              ),
              m("span.list-duration", "Lengd"),
              m("span.list-manual", glyphGrayed("lightbulb", { title: 'Keppnishamur' }))
            ]
          ),
          vwList()
        ];
      }

      function vwUserButton(id, icon, text) {
        // Select the type of user list (robots, fav, alike, elo)
        var sel = model.userListCriteria ? model.userListCriteria.query : "robots";
        var spec = (id == "elo") ? "human" : "";
        return m("span",
          {
            className: (id == sel ? "shown" : ""),
            id: id,
            onclick: function(ev) {
              model.loadUserList({ query: id, spec: spec }, true);
              ev.preventDefault();
            }
          },
          [ glyph(icon, { style: { padding: 0 } }), nbsp(), text ]
        );
      }

      function vwUserList() {

        function vwUserList(listType, list) {

          function itemize(item, i) {

            // Generate a list item about a user

            var isRobot = item.userid.indexOf("robot-") === 0;
            var fullname = [];

            if (item.ready && !isRobot)
              fullname.push(m("span.ready-btn", { title: "Álínis og tekur við áskorunum" }));
            if (item.ready_timed)
              fullname.push(m("span.timed-btn", { title: "Til í viðureign með klukku" }));
            fullname.push(item.fullname);

            function fav() {
              if (isRobot)
                return m("span.list-fav", { style: { cursor: "default" } }, glyph("star-empty"));
              return m("span.list-fav",
                {
                  title: "Uppáhald",
                  onclick: function(ev) {
                    this.fav = !this.fav;
                    model.markFavorite(this.userid, this.fav);
                    ev.preventDefault();
                  }.bind(item)
                },
                glyph(item.fav ? "star" : "star-empty")
              );
            }

            function issueChallenge() {
              if (item.chall) {
                // Retracting challenge
                item.chall = false;
                model.modifyChallenge({ destuser: item.userid, action: "retract" });
              }
              else
              if (isRobot)
                // Challenging a robot: game starts immediately
                model.newGame(item.userid, false);
              else
                // Challenging a user: show a challenge dialog
                view.pushDialog("challenge", item);
            }

            function userLink() {
              if (isRobot)
                return m("a",
                  {
                    href: "",
                    onclick: function(ev) { model.newGame(item.userid, false); ev.preventDefault(); }
                  },
                  [
                    m("span.list-nick", [ glyph("cog"), nbsp(), item.nick ]),
                    m("span.list-fullname-robot", fullname)
                  ]
                );
              else
                return [
                  m("span.list-nick", item.nick),
                  m("span.list-fullname", fullname),
                  m("span.list-human-elo", item.human_elo)
                ];
            }

            return m(".listitem" + (i % 2 === 0 ? ".oddlist" : ".evenlist"),
              [
                m("span.list-ch",
                  {
                    title: "Skora á",
                    onclick: function(ev) {
                      issueChallenge();
                      ev.preventDefault();
                    }
                  },
                  glyph("hand-right", undefined, !item.chall)
                ),
                fav(),
                userLink(),
                m("span.list-info",
                  {
                    title: "Skoða feril",
                    onclick: function(ev) {
                      showUserInfo(this.userid, this.nick, this.fullname);
                      ev.preventDefault();
                    }.bind(item)
                  },
                  isRobot ? "" : m("span.usr-info")
                ),
                isRobot ? "" : m("span.list-newbag", { title: "Gamli pokinn" },
                  glyph("shopping-bag", undefined, item.newbag))
              ]
            );
          }

          return m("div", { id: "userlist" }, list.map(itemize));
        }

        var listType = model.userListCriteria ? model.userListCriteria.query : "robots";
        if (listType == "elo")
          // Show Elo list
          return m(EloPage, { id: "elolist", model: model, view: view });
        // Show normal user list
        var list = [];
        if (model.userList === undefined)
          // We are loading a fresh user list
          ;
        else
        if (model.userList === null || model.userListCriteria.query != listType)
          model.loadUserList({ query: listType, spec: "" }, true);
        else
          list = model.userList;
        var nothingFound = list.length === 0 && model.userListCriteria !== undefined &&
          listType == "search" && model.userListCriteria.spec !== "";
        return [
          m(".listitem.listheader",
            [
              m("span.list-ch", glyphGrayed("hand-right", { title: 'Skora á' })),
              m("span.list-fav", glyph("star-empty", { title: 'Uppáhald' })),
              m("span.list-nick", "Einkenni"),
              m("span.list-fullname", "Nafn og merki"),
              listType == "robots" ? "" : m("span.list-human-elo[id='usr-list-elo']", "Elo"),
              listType == "robots" ? "" : m("span.list-info-hdr[id='usr-list-info']", "Ferill"),
              listType == "robots" ? "" : m("span.list-newbag", glyphGrayed("shopping-bag", { title: 'Gamli pokinn' }))
            ]
          ),
          vwUserList(listType, list),
          // Show indicator if search didn't find any users matching the criteria
          nothingFound ?
            m("div",
                { id: "user-no-match", style: { display: "block" } },
                [ glyph("search"), " ", m("span", { id: "search-prefix" }, model.userListCriteria.spec), " finnst ekki" ]
              )
            : ""
        ];
      }

      function vwStats() {
        // View the user's own statistics summary
        var ownStats = model.ownStats;
        if (model.ownStats === null)
          model.loadOwnStats();
        return m(StatsDisplay, { id: 'own-stats', ownStats: ownStats });
      }

      function vwBest() {
        // View the user's own best game and word scores
        var ownStats = model.ownStats;
        if (model.ownStats === null)
          model.loadOwnStats();
        return m(BestDisplay, { id: 'own-best', ownStats: ownStats, myself: true });
      }

      return m(".tabbed-page",
        m("div", { id: 'main-tabs' },
          [
            vwMainTabHeader(),
            m("div", { id: 'tabs-1' },
              [
                m("p.no-mobile-block",
                  [
                    m("strong", "Viðureignir sem standa yfir"),
                    " - smelltu á viðureign til að skoða stöðuna og leika ef ",
                    glyph("flag"), " þú átt leik"
                  ]
                ),
                vwGamelist()
              ]
            ),
            m("div", { id: 'tabs-2' },
              [
                m("p.no-mobile-block",
                  [
                    m("strong", "Skorað á þig"),
                    " - smelltu á áskorun til að taka henni og hefja viðureign, eða á ",
                    glyph("thumbs-down", { style: { "margin-left": "6px", "margin-right": "6px" } }),
                    " til að hafna henni"
                  ]
                ),
                vwChallenges(true),
                m("p.no-mobile-block",
                  [
                    m("strong", "Þú skorar á aðra"),
                    " - smelltu á ",
                    glyph("hand-right", { style: { "margin-left": "6px", "margin-right": "6px" } }),
                    " til að afturkalla áskorun"
                  ]
                ),
                vwChallenges(false)
              ]
            ),
            m("div", { id: 'tabs-4' },
              [
                vwStats(),
                vwBest(),
                m("p.no-mobile-block",
                  [
                    m("strong", "Nýlegar viðureignir þínar"),
                    " - smelltu á viðureign til að skoða hana og rifja upp"
                  ]
                ),
                vwRecentList()
              ]
            ),
            m("div", { id: 'tabs-3' },
              [
                m("div", { id: 'initials' },
                  [
                    m(".user-cat[id='user-headings']",
                      [
                        vwUserButton("robots", "cog", "Þjarkar"),
                        " ",
                        vwUserButton("fav", "star", "Uppáhalds"),
                        " ",
                        vwUserButton("live", "flash", "Álínis"),
                        " ",
                        vwUserButton("alike", "resize-small", "Svipaðir"),
                        " ",
                        vwUserButton("elo", "crown", "Topp 100")
                      ]
                    ),
                    m(SearchButton, { model: model })
                  ]
                ),
                vwUserList()
              ]
            )
          ]
        )
      );
    }

    return [
      vwLogo(),
      vwUserId.call(this),
      vwInfo(),
      m("main",
        m("div",
          {
            oncreate: makeTabs.bind(this, "main-tabs", undefined, false),
            onupdate: updateSelection
          },
          vwMainTabs()
        )
      )
    ];
  }

  function vwPlayerName(view, game, side) {
    // Displays a player name, handling both human and robot players
    // as well as left and right side, and local and remote colors
    var apl0 = game && game.autoplayer[0];
    var apl1 = game && game.autoplayer[1];
    var nick0 = game ? game.nickname[0] : "";
    var nick1 = game ? game.nickname[1] : "";
    var player = game ? game.player : 0;
    var localturn = game ? game.localturn : false;
    var tomove;
    var gameover = game ? game.over : true;

    function lookAtPlayer(player, side, ev) {
      if (!$state.uiFullscreen)
        // Don't do anything on mobile, and allow the click
        // to propagate to the parent
        return;
      if (player === 0 || player === 1) {
        if (player == side) {
          // The player is clicking on himself:
          // overlay a user preference dialog
          view.pushDialog("userprefs");
        }
        else
        if (!game.autoplayer[side]) {
          // The player is clicking on the opponent:
          // show the opponent's track record, if not an autoplayer
          view.showUserInfo(game.userid[side], game.nickname[side], game.fullname[side]);
        }
      }
      ev.stopPropagation();
      ev.preventDefault();
    }

    if (side == "left") {
      // Left side player
      if (apl0)
        // Player 0 is a robot (autoplayer)
        return m(".robot-btn.left", [ glyph("cog"), nbsp(), nick0 ]);
      tomove = gameover || (localturn ^ (player === 0)) ? "" : ".tomove";
      return m((player === 0 || player === 1) ? ".player-btn.left" + tomove : ".robot-btn.left",
        { id: "player-0", onclick: lookAtPlayer.bind(null, player, 0) },
        [ m("span.left-to-move"), nick0 ]
      );
    }
    else {
      // Right side player
      if (apl1)
        // Player 1 is a robot (autoplayer)
        return m(".robot-btn.right", [ glyph("cog"), nbsp(), nick1 ]);
      tomove = gameover || (localturn ^ (player === 1)) ? "" : ".tomove";
      return m((player === 0 || player === 1) ? ".player-btn.right" + tomove : ".robot-btn.right",
        { id: "player-1", onclick: lookAtPlayer.bind(null, player, 1) },
        [ m("span.right-to-move"), nick1 ]
      );
    }
  }

  // Game screen

  function vwGame(model, actions) {
    // A view of a game, in-progress or finished

    var game = model.game;
    var view = this;

    function vwRightColumn() {
      // A container for the right-side header and area components

      function vwRightHeading() {
        // The right-side heading on the game screen

        var fairplay = game ? game.fairplay : false;
        var player = game ? game.player : 0;
        var sc0 = game ? game.scores[0].toString() : "";
        var sc1 = game ? game.scores[1].toString() : "";
        return m(".heading",
          {
            // On mobile only: If the header is clicked, go to the main screen
            onclick: function(ev) {
              if (!$state.uiFullscreen) m.route.set("/main");
            }
          },
          [
            m("h3.playerleft" + (player == 1 ? ".autoplayercolor" : ".humancolor"),
              vwPlayerName(view, game, "left")),
            m("h3.playerright" + (player == 1 ? ".humancolor" : ".autoplayercolor"),
              vwPlayerName(view, game, "right")),
            m("h3.scoreleft", sc0),
            m("h3.scoreright", sc1),
            m("h3.clockleft"),
            m("h3.clockright"),
            m(".clockface", glyph("time")),
            m(".fairplay",
              fairplay ? { style: { display: "block" } } : { },
              m("span.fairplay-btn.large", { title: "Skraflað án hjálpartækja" } ))
          ]
        );
      }

      function vwRightArea() {
        // A container for the tabbed right-side area components
        var sel = (game && game.sel) ? game.sel : "movelist";
        // Show the chat tab unless the opponent is an autoplayer
        var component = null;
        if (sel == "movelist")
          component = vwMovelist.call(view, game);
        else
        if (sel == "twoletter")
          component = m(vwTwoLetter);
        else
        if (sel == "chat")
          component = vwChat(game);
        else
        if (sel == "games")
          component = vwGames(game);
        var tabgrp = vwTabGroup(game);
        return m(".right-area", component ? [ tabgrp, component ] : [ tabgrp ]);
      }

      return m(".rightcol", [ vwRightHeading(), vwRightArea() ]);
    }

    if (game === undefined || game === null)
      // No associated game
      return m("div", [ vwBack(), m("main", m(".game-container")) ]);

    var bag = game ? game.bag : "";
    var newbag = game ? game.newbag : true;
    return m("div", // Removing this div messes up Mithril
      {
        // Allow tiles to be dropped on the background,
        // thereby transferring them back to the rack
        ondragenter: function(ev) {
          ev.preventDefault();
          ev.dataTransfer.dropEffect = 'move';
          ev.redraw = false;
          return false;
        },
        ondragover: function(ev) {
          // This is necessary to allow a drop
          ev.preventDefault();
          ev.redraw = false;
          return false;
        },
        ondrop: function(ev) {
          ev.stopPropagation();
          // Move the tile from the source to the destination
          var from = ev.dataTransfer.getData("text");
          // Move to the first available slot in the rack
          game.attemptMove(from, "R1");
          return false;
        }
      },
      [
        vwBack(),
        $state.beginner ? vwBeginner(game) : "",
        vwInfo(),
        m("main",
          m(".game-container",
            [
              vwBoardArea(game),
              vwRightColumn(),
              vwBag(bag, newbag),
              game.askingForBlank ? vwBlankDialog(game) : ""
            ]
          )
        )
      ]
    );
  }

  // Review screen

  function vwReview(model, actions) {
    // A review of a finished game

    var game = model.game;
    var move = model.reviewMove;
    var bestMoves = model.bestMoves || [];
    var view = this;

    function vwRightColumn() {
      // A container for the right-side header and area components

      function vwRightHeading() {
        // The right-side heading on the game screen

        var fairplay = game ? game.fairplay : false;
        var player = game ? game.player : 0;
        var sc0 = game ? game.scores[0].toString() : "";
        var sc1 = game ? game.scores[1].toString() : "";
        return m(".heading",
          {
            // On mobile only: If the header is clicked, go to the main screen
            onclick: function(ev) {
              if (!$state.uiFullscreen) m.route.set("/main");
            }
          },
          [
            m("h3.playerleft" + (player == 1 ? ".autoplayercolor" : ".humancolor"),
              vwPlayerName(view, game, "left")),
            m("h3.playerright" + (player == 1 ? ".humancolor" : ".autoplayercolor"),
              vwPlayerName(view, game, "right")),
            m("h3.scoreleft", sc0),
            m("h3.scoreright", sc1),
            m(".fairplay",
              fairplay ? { style: { display: "block" } } : { },
              m("span.fairplay-btn.large", { title: "Skraflað án hjálpartækja" } ))
          ]
        );
      }

      function vwRightArea() {
        // A container for the list of best possible moves
        return m(".right-area", vwBestMoves.call(view, game, move, bestMoves));
      }

      return m(".rightcol", [ vwRightHeading(), vwRightArea() ]);
    }

    if (game === undefined || game === null)
      // No associated game
      return m("div", [ vwBack(), m("main", m(".game-container")) ]);

    var bag = game ? game.bag : "";
    var newbag = game ? game.newbag : true;
    // Create a list of major elements that we're showing
    var r = [];
    r.push(vwBoardReview(game, move));
    r.push(vwRightColumn());
    if (move === null)
      // Only show the stats overlay if move is null.
      // This means we don't show the overlay if move is 0.
      r.push(vwStatsReview(game));
    return m("div", // Removing this div messes up Mithril
      [
        vwBack(), // Button to go back to main screen
        vwInfo(), // Help button
        m("main",
          m(".game-container", r)
        )
      ]
    );
  }

  function vwTabGroup(game) {
    // A group of clickable tabs for the right-side area content
    var showchat = game ? !(game.autoplayer[0] || game.autoplayer[1]) : false;
    var r = [
      vwTab(game, "board", "Borðið", "grid"),
      vwTab(game, "movelist", "Leikir", "show-lines"),
      vwTab(game, "twoletter", "Tveggja stafa orð", "life-preserver"),
      vwTab(game, "games", "Viðureignir", "flag")
    ];
    if (showchat)
      // Add chat tab
      r.push(vwTab(game, "chat", "Spjall", "conversation",
        function() {
          // The tab has been clicked
          if (game.markChatShown())
            m.redraw();
        },
        !game.chatShown) // Show chat icon in red if chat messages are unseen
      );
    return m.fragment({}, r);
  }

  function vwTab(game, tabid, title, icon, func, alert) {
    // A clickable tab for the right-side area content
    var sel = (game && game.sel) ? game.sel : "movelist";
    return m(".right-tab" + (sel == tabid ? ".selected" : ""),
      {
        id: "tab-" + tabid,
        className: alert ? "alert" : "",
        title: title,
        onclick: function(ev) {
          // Select this tab
          if (game && game.sel != tabid) {
            game.sel = tabid;
            if (func !== undefined)
              func();
          }
        }
      },
      glyph(icon)
    );
  }

  function vwChat(game) {
    // The chat tab

    function decodeTimestamp(ts) {
       // Parse and split an ISO timestamp string, formatted as YYYY-MM-DD HH:MM:SS
       return {
          year: parseInt(ts.substr(0, 4)),
          month: parseInt(ts.substr(5, 2)),
          day: parseInt(ts.substr(8, 2)),
          hour: parseInt(ts.substr(11, 2)),
          minute: parseInt(ts.substr(14, 2)),
          second: parseInt(ts.substr(17, 2))
       };
    }

    function dateFromTimestamp(ts) {
       // Create a JavaScript millisecond-based representation of an ISO timestamp
       var dcTs = decodeTimestamp(ts);
       return Date.UTC(dcTs.year, dcTs.month - 1, dcTs.day,
          dcTs.hour, dcTs.minute, dcTs.second);
    }

    function timeDiff(dtFrom, dtTo) {
       // Return the difference between two JavaScript time points, in seconds
       return Math.round((dtTo - dtFrom) / 1000.0);
    }

    var dtLastMsg = null;

    function makeTimestamp(ts) {
      // Decode the ISO format timestamp we got from the server
      var dtTs = dateFromTimestamp(ts);
      var result = null;
      if (dtLastMsg === null || timeDiff(dtLastMsg, dtTs) >= 5 * 60) {
        // If 5 minutes or longer interval between messages,
        // insert a time
        var ONE_DAY = 24 * 60 * 60 * 1000; // 24 hours expressed in milliseconds
        var dtNow = new Date().getTime();
        var dtToday = dtNow - dtNow % ONE_DAY; // Start of today (00:00 UTC)
        var dtYesterday = dtToday - ONE_DAY; // Start of yesterday
        var strTs;
        if (dtTs < dtYesterday)
           // Older than today or yesterday: Show full timestamp YYYY-MM-DD HH:MM
           strTs = ts.slice(0, -3);
        else
        if (dtTs < dtToday)
           // Yesterday
           strTs = "Í gær " + ts.substr(11, 5);
        else
           // Today
           strTs = ts.substr(11, 5);
        result = m(".chat-ts", strTs);
      }
      dtLastMsg = dtTs;
      return result;
    }

    var player = game ? game.player : 0;

    function chatMessages() {
      var r = [];
      if (game && game.messages) {
        var mlist = game.messages;
        for (var i = 0; i < mlist.length; i++) {
          var p = player;
          if (mlist[i].from_userid != $state.userId)
            p = 1 - p;
          var mTs = makeTimestamp(mlist[i].ts);
          if (mTs)
            r.push(mTs);
          var escMsg = escapeHtml(mlist[i].msg);
          escMsg = replaceEmoticons(escMsg);
          r.push(m(".chat-msg" +
            (p === 0 ? ".left" : ".right") +
            (p === player ? ".local" : ".remote"),
            { key: i },
            m.trust(escMsg))
          );
        }
      }
      return r;
    }

    function scrollChatToBottom() {
      // Scroll the last chat message into view
      var chatlist = document.querySelectorAll("#chat-area .chat-msg");
      var target;
      if (chatlist.length) {
        target = chatlist[chatlist.length - 1];
        target.parentNode.scrollTop = target.offsetTop;
      }
    }

    function focus(vnode) {
      // Put the focus on the DOM object associated with the vnode
      vnode.dom.focus();
    }

    function sendMessage() {
      var msg = getInput("msg").trim();
      if (game && msg.length > 0) {
        game.sendMessage(msg);
        setInput("msg", "");
      }
    }

    var numMessages = (game && game.messages) ? game.messages.length : 0;
    var uuid = game ? game.uuid : "";

    if (game && game.messages === null)
      // No messages loaded yet: kick off async message loading
      // for the current game
      game.loadMessages();
    else
      game.markChatShown();

    return m(".chat",
      {
        style: "z-index: 6", // Appear on top of board on mobile
        key: uuid
      },
      [
        m(".chat-area",
          {
            id: 'chat-area',
            // Make sure that we see the bottom-most chat message
            oncreate: scrollChatToBottom,
            onupdate: scrollChatToBottom
          },
          chatMessages()),
        m(".chat-input",
          [
            m("input.chat-txt",
              {
                type: "text",
                id: "msg",
                name: "msg",
                maxlength: 254,
                disabled: (numMessages >= MAX_CHAT_MESSAGES),
                oncreate: focus,
                onupdate: focus,
                onkeypress: function(ev) { if (ev.key == "Enter") sendMessage(); }
              }
            ),
            m(DialogButton,
              {
                id: "chat-send",
                title: "Senda",
                onclick: function(ev) { sendMessage(); }
              },
              glyph("chat")
            )
          ]
        )
      ]
    );
  }

  function vwMovelist(game) {
    // The move list tab

    var view = this;

    function movelist() {
      var mlist = game ? game.moves : []; // All moves made so far in the game
      var r = [];
      var leftTotal = 0;
      var rightTotal = 0;
      for (var i = 0; i < mlist.length; i++) {
        var player = mlist[i][0];
        var co = mlist[i][1][0];
        var tiles = mlist[i][1][1];
        var score = mlist[i][1][2];
        if (player === 0)
          leftTotal = Math.max(leftTotal + score, 0);
        else
          rightTotal = Math.max(rightTotal + score, 0);
        r.push(
          vwMove.call(view, game, mlist[i],
            {
              key: i.toString(),
              leftTotal: leftTotal, rightTotal: rightTotal,
              player: player, co: co, tiles: tiles, score: score
            }
          )
        );
      }
      return r;
    }

    var bag = game ? game.bag : "";
    var newbag = game ? game.newbag : true;
    return m(".movelist-container",
      [
        m(".movelist",
          {
            onupdate: scrollMovelistToBottom
          },
          movelist()
        ),
        vwBag(bag, newbag) // Visible on mobile
      ]
    );
  }

  function vwBestMoves(game, move, bestMoves) {
    // List of best moves, in a game review

    var view = this;

    function bestHeader(co, tiles, score) {
      // Generate the header of the best move list
      var wrdclass = "wordmove";
      var dispText;
      if (co.length > 0) {
        // Regular move
        dispText = [
          m("i", tiles.split("?").join("")),
          " (" + co + ")"
        ];
      }
      else {
        /* Not a regular tile move */
        wrdclass = "othermove";
        if (tiles == "PASS")
          /* Pass move */
          dispText = "Pass";
        else
        if (tiles.indexOf("EXCH") === 0) {
          /* Exchange move - we don't show the actual tiles exchanged, only their count */
          var numtiles = tiles.slice(5).length;
          dispText = "Skipti um " + numtiles.toString() + (numtiles == 1 ? " staf" : " stafi");
        }
        else
        if (tiles == "RSGN")
          /* Resigned from game */
          dispText = "Gaf viðureign";
        else
        if (tiles == "CHALL")
          /* Challenge issued */
          dispText = "Véfengdi lögn";
        else
        if (tiles == "RESP") {
          /* Challenge response */
          if (score < 0)
             dispText = "Lögn óleyfileg";
          else
             dispText = "Röng véfenging";
        }
        else
        if (tiles == "OVER") {
          /* Game over */
          dispText = "Leik lokið";
          wrdclass = "gameover";
        }
        else {
          // The rack leave at the end of the game (which is always in lowercase
          // and thus cannot be confused with the above abbreviations)
          wrdclass = "wordmove";
          dispText = tiles;
        }
      }
      return m(".reviewhdr",
        [
          m("span.movenumber", "#" + move),
          m("span", { class: wrdclass }, dispText)
        ]
      );
    }

    function bestMoveList() {
      var r = [];
      // Use a 1-based index into the move list
      // (We show the review summary if move==0)
      if (!move || move > game.moves.length)
        return r;
      // Prepend a header that describes the move being reviewed
      var m = game.moves[move - 1];
      var co = m[1][0];
      var tiles = m[1][1];
      var score = m[1][2];
      r.push(bestHeader(co, tiles, score));
      var mlist = bestMoves;
      for (var i = 0; i < mlist.length; i++) {
        var player = mlist[i][0];
        co = mlist[i][1][0];
        tiles = mlist[i][1][1];
        score = mlist[i][1][2];
        r.push(
          vwBestMove.call(view, game, mlist[i],
            {
              key: i.toString(),
              player: player, co: co, tiles: tiles, score: score
            }
          )
        );
      }
      return r;
    }

    return m(".movelist-container",
      [
        m(".movelist.bestmoves", bestMoveList())
      ]
    );
  }

  function scrollMovelistToBottom() {
    // If the length of the move list has changed,
    // scroll the last move into view
    var movelist = document.querySelectorAll("div.movelist .move");
    if (!movelist || !movelist.length)
      return;
    var target = movelist[movelist.length - 1];
    var parent = target.parentNode;
    var len = parent.getAttribute("data-len");
    if (!len) {
      len = 0;
    }
    else {
      len = parseInt(len);
    }
    if (movelist.length > len) {
      // The list has grown since we last updated it:
      // scroll to the bottom and mark its length
      parent.scrollTop = target.offsetTop;
    }
    parent.setAttribute("data-len", movelist.length);
  }

  function vwMove(game, move, info) {
    // Displays a single move

    var view = this;

    function highlightMove(co, tiles, playerColor, show) {
       /* Highlight a move's tiles when hovering over it in the move list */
       var vec = toVector(co);
       var col = vec.col;
       var row = vec.row;
       for (var i = 0; i < tiles.length; i++) {
          var tile = tiles[i];
          if (tile == '?')
             continue;
          var sq = coord(row, col);
          game.tiles[sq].highlight = show ? playerColor : undefined;
          col += vec.dx;
          row += vec.dy;
       }
    }

    var player = info.player;
    var co = info.co;
    var tiles = info.tiles;
    var score = info.score;
    var leftTotal = info.leftTotal;
    var rightTotal = info.rightTotal;

    function gameOverMove(tiles) {
      return m(".move.gameover",
        [
          m("span.gameovermsg", tiles),
          m("span.statsbutton",
            {
              onclick: function(uuid, ev) {
                if (true || $state.hasPaid) // !!! TODO
                  // Show the game review
                  m.route.set("/review/" + uuid);
                else
                  // Show a friend promotion dialog
                  this.pushDialog("promo", { key: "friend" });
                ev.preventDefault();
              }.bind(view, game.uuid)
            },
            "Skoða yfirlit"
          )
        ]
      );
    }

    // Add a single move to the move list
    var wrdclass = "wordmove";
    var rawCoord = co;
    var tileMoveIncrement = 0; // +1 for tile moves, -1 for successful challenges
    if (co === "") {
      /* Not a regular tile move */
      wrdclass = "othermove";
      if (tiles == "PASS") {
        /* Pass move */
        tiles = " Pass ";
        score = "";
      }
      else
      if (tiles.indexOf("EXCH") === 0) {
        /* Exchange move - we don't show the actual tiles exchanged, only their count */
        var numtiles = tiles.slice(5).length;
        tiles = "Skipti um " + numtiles.toString() + (numtiles == 1 ? " staf" : " stafi");
        score = "";
      }
      else
      if (tiles == "RSGN")
        /* Resigned from game */
        tiles = " Gaf viðureign "; // Extra space intentional
      else
      if (tiles == "CHALL") {
        /* Challenge issued */
        tiles = " Véfengdi lögn "; // Extra space intentional
        score = "";
      }
      else
      if (tiles == "RESP") {
        /* Challenge response */
        if (score < 0) {
          tiles = " Óleyfileg lögn "; // Extra space intentional
          tileMoveIncrement = -1; // Subtract one from the actual tile moves on the board
        }
        else
          tiles = " Röng véfenging "; // Extra space intentional
      }
      else
      if (tiles == "TIME") {
        /* Overtime adjustment */
        tiles = " Umframtími "; // Extra spaces intentional
      }
      else
      if (tiles == "OVER") {
        /* Game over */
        tiles = "Viðureign lokið";
        wrdclass = "gameover";
      }
      else {
        /* The rack leave at the end of the game (which is always in lowercase
           and thus cannot be confused with the above abbreviations) */
        wrdclass = "wordmove";
      }
    }
    else {
      // Normal tile move
      co = "(" + co + ")";
      // Note: String.replace() will not work here since there may be two question marks in the string
      tiles = tiles.split("?").join(""); /* !!! TODO: Display wildcard characters differently? */
      tileMoveIncrement = 1;
    }
    if (wrdclass == "gameover")
      // Game over message at bottom of move list
      return gameOverMove(tiles);
    // Normal game move
    var title = (tileMoveIncrement > 0 && !game.manual) ? "Smelltu til að fletta upp" : "";
    var playerColor = "0";
    var lcp = game.player;
    var cls;
    if (player === lcp || (lcp == -1 && player === 0)) // !!! TBD: Check -1 case
      cls = "humangrad" + (player === 0 ? "_left" : "_right"); /* Local player */
    else {
      cls = "autoplayergrad" + (player === 0 ? "_left" : "_right"); /* Remote player */
      playerColor = "1";
    }
    var attribs = { title: title };
    if ($state.uiFullscreen && tileMoveIncrement > 0) {
      if (!game.manual)
        // Tile move and not a manual game: allow word lookup
        attribs.onclick = function() { window.open('http://malid.is/leit/' + tiles, 'malid'); };
      // Highlight the move on the board while hovering over it
      attribs.onmouseout = function() {
        move.highlighted = false;
        highlightMove(rawCoord, tiles, playerColor, false);
      };
      attribs.onmouseover = function() {
        move.highlighted = true;
        highlightMove(rawCoord, tiles, playerColor, true);
      };
    }
    if (player === 0) {
      // Move by left side player
      return m(".move.leftmove." + cls, attribs,
        [
          m("span.total", leftTotal),
          m("span.score" + (move.highlighted ? ".highlight" : ""), score),
          m("span." + wrdclass, [ m("i", tiles), nbsp(), co ])
        ]
      );
    }
    else {
      // Move by right side player
      return m(".move.rightmove." + cls, attribs,
        [
          m("span." + wrdclass, [ co, nbsp(), m("i", tiles) ]),
          m("span.score" + (move.highlighted ? ".highlight" : ""), score),
          m("span.total", rightTotal)
        ]
      );
    }
  }

  function vwBestMove(game, move, info) {
    // Displays a move in a list of best available moves

    var view = this;

    function highlightMove(co, tiles, playerColor, show) {
       /* Highlight a move's tiles when hovering over it in the move list */
       var vec = toVector(co);
       var col = vec.col;
       var row = vec.row;
       for (var i = 0; i < tiles.length; i++) {
          var tile = tiles[i];
          if (tile == '?')
             continue;
          var sq = coord(row, col);
          if (game.tiles[sq] !== undefined)
            game.tiles[sq].highlight = show ? playerColor : undefined;
          col += vec.dx;
          row += vec.dy;
       }
    }

    var player = info.player;
    var co = info.co;
    var tiles = info.tiles;
    var score = info.score;

    // Add a single move to the move list
    var rawCoord = co;
    // Normal tile move
    co = "(" + co + ")";
    // Note: String.replace() will not work here since there may be two question marks in the string
    tiles = tiles.split("?").join(""); /* !!! TODO: Display wildcard characters differently? */
    // Normal game move
    var title = "Smelltu til að fletta upp";
    var playerColor = "0";
    var lcp = game.player;
    var cls;
    if (player === lcp || (lcp == -1 && player === 0)) // !!! TBD: Check -1 case
      cls = "humangrad" + (player === 0 ? "_left" : "_right"); /* Local player */
    else {
      cls = "autoplayergrad" + (player === 0 ? "_left" : "_right"); /* Remote player */
      playerColor = "1";
    }
    var attribs = { title: title };
    // Word lookup
    attribs.onclick = function() { window.open('http://malid.is/leit/' + tiles, 'malid'); };
    // Highlight the move on the board while hovering over it
    attribs.onmouseout = function() {
      move.highlighted = false;
      highlightMove(rawCoord, tiles, playerColor, false);
    };
    attribs.onmouseover = function() {
      move.highlighted = true;
      highlightMove(rawCoord, tiles, playerColor, true);
    };
    if (player === 0) {
      // Move by left side player
      return m(".move.leftmove." + cls, attribs,
        [
          m("span.score" + (move.highlighted ? ".highlight" : ""), score),
          m("span.wordmove", [ m("i", tiles), nbsp(), co ])
        ]
      );
    }
    else {
      // Move by right side player
      return m(".move.rightmove." + cls, attribs,
        [
          m("span.wordmove", [ co, nbsp(), m("i", tiles) ]),
          m("span.score" + (move.highlighted ? ".highlight" : ""), score)
        ]
      );
    }
  }

  function vwGames(game) {
    // The game list tab

    function games() {
      var r = [];
      // var numMyTurns = 0;
      if (game.gamelist === null)
        // No games to show now, but we'll load them
        // and they will be automatically refreshed when ready
        game.loadGames();
      else {
        var numGames = game.gamelist.length;
        var gameId = game ? game.uuid : "";
        for (var i = 0; i < numGames; i++) {
          var item = game.gamelist[i];
          if (item.uuid == gameId)
            continue; // Don't show this game
          if (!item.my_turn && !item.zombie)
            continue; // Only show pending games
          var opp;
          if (item.oppid === null)
            // Mark robots with a cog icon
            opp = [ glyph("cog"), nbsp(), item.opp ];
          else
            opp = [ item.opp ];
          var winLose = item.sc0 < item.sc1 ? ".losing" : "";
          var title = "Staðan er " + item.sc0 + ":" + item.sc1;
          // Add the game-timed class if the game is a timed game.
          // These will not be displayed in the mobile UI.
          r.push(
            m(".games-item" + (item.timed ? ".game-timed" : ""),
              { key: item.uuid, title: title },
              m(m.route.Link,
                { href: "/game/" + item.url.slice(-36), }, // !!! TO BE FIXED
                [
                  m(".at-top-left", m(".tilecount", m(".oc", opp))),
                  m(".at-top-left",
                    m(".tilecount.trans",
                      m(".tc" + winLose, { style: { width: item.tile_count.toString() + "%" } }, opp)
                    )
                  )
                ]
              )
            )
          );
          // numMyTurns++;
        }
      }
      return r;
    }

    return m(".games", { style: "z-index: 6" }, games());
  }

  function vwBag(bag, newbag) {
    // The bag of tiles
    var lenbag = bag.length;

    function tiles() {
      var r = [];
      var ix = 0;
      var count = lenbag;
      while (count > 0) {
        // Rows
        var cols = [];
        // Columns: max BAG_TILES_PER_LINE tiles per row
        for (var i = 0; i < BAG_TILES_PER_LINE && count > 0; i++) {
          var tile = bag[ix++];
          if (tile == "?")
             // Show wildcard tiles '?' as blanks
             tile = "&nbsp;";
          cols.push(m("td", m.trust(tile)));
          count--;
        }
        r.push(m("tr", cols));
      }
      return r;
    }

    var cls = "";
    if (lenbag <= RACK_SIZE)
      cls += ".empty";
    else
    if (newbag)
      cls += ".new";
    return m(".bag",
      { title: 'Flísar sem eftir eru í pokanum' },
      m("table.bag-content" + cls, tiles(bag))
    );
  }

  function vwBlankDialog(game) {
    // A dialog for choosing the meaning of a blank tile

    function blankLetters() {
      var len = LEGAL_LETTERS.length;
      var ix = 0;
      var r = [];
      while (len > 0) {
        /* Rows */
        var c = [];
        /* Columns: max BLANK_TILES_PER_LINE tiles per row */
        for (var i = 0; i < BLANK_TILES_PER_LINE && len > 0; i++) {
          var letter = LEGAL_LETTERS[ix++];
          c.push(
            m("td",
              {
                onclick: function(letter, ev) {
                  ev.preventDefault();
                  game.placeBlank(letter);
                }.bind(null, letter),
                onmouseover: buttonOver,
                onmouseout: buttonOut
              },
              m(".blank-choice.tile.racktile", letter)
            )
          );
          len--;
        }
        r.push(m("tr", c));
      }
      return r;
    }

    return m(".modal-dialog",
      {
        id: 'blank-dialog',
        style: { visibility: "visible" }
      },
      m(".ui-widget.ui-widget-content.ui-corner-all", { id: 'blank-form' },
        [
          m("p", "Hvaða staf táknar auða flísin?"),
          m(".rack.blank-rack", m("table.board", { id: 'blank-meaning' }, blankLetters())),
          m(DialogButton,
            {
              id: 'blank-close',
              title: 'Hætta við',
              onclick: function(ev) {
                ev.preventDefault();
                game.cancelBlankDialog();
              }
            },
            glyph("remove")
          )
        ]
      )
    );
  }

  function vwBack() {
    // Icon for going back to the main screen
    return m(".logo-back", 
      m(m.route.Link,
        { href: "/main", class: "backlink" },
        glyph("download", { title: "Aftur í aðalskjá" })
      )
    );
  }

  function vwBoardArea(game) {
    // Collection of components in the board (left-side) area
    var r = [];
    if (game) {
      r = [
        vwBoard(game),
        vwRack(game),
        vwButtons(game),
        vwErrors(game),
        vwCongrats(game)
      ];
      r = r.concat(vwDialogs(game));
    }
    return m(".board-area", r);
  }

  function vwBoardReview(game, move) {
    // The board area within a game review screen
    var r = [];
    if (game) {
      r = [
        vwBoard(game),
        vwRack(game),
        vwButtonsReview(game, move)
      ];
    }
    return m(".board-area", r);
  }

  function vwTile(game, coord) {
    // A single tile, on the board or in the rack
    var t = game.tiles[coord];
    var classes = [ ".tile" ];
    var attrs = {};
    if (t.tile == '?')
      classes.push("blanktile");
    if (coord[0] == 'R' || t.draggable) {
      classes.push("racktile");
      if (coord[0] == 'R' && game.showingDialog == "exchange") {
        // Rack tile, and we're showing the exchange dialog
        if (t.xchg)
          // Chosen as an exchange tile
          classes.push("xchgsel");
        // Exchange dialog is live: add a click handler for the
        // exchange state
        attrs.onclick = function(tile, ev) {
          // Toggle the exchange status
          tile.xchg = !tile.xchg;
          ev.preventDefault();
        }.bind(null, t);
      }
    }
    if (t.freshtile) {
      classes.push("freshtile");
      // Make fresh tiles appear sequentally by animation
      var ANIMATION_STEP = 150; // Milliseconds
      var delay = (t.index * ANIMATION_STEP).toString() + "ms";
      attrs.style = "animation-delay: " + delay + "; " +
        "-webkit-animation-delay: " + delay + ";";
    }
    if (coord == game.selectedSq)
      classes.push("sel"); // Blinks red
    if (t.highlight !== undefined) {
      // highlight0 is the local player color (yellow/orange)
      // highlight1 is the remote player color (green)
      classes.push("highlight" + t.highlight);
      if (t.player == parseInt(t.highlight))
        // This tile was originally laid down by the other player
        classes.push("dim");
    }
    if (game.showingDialog === null && !game.over) {
      if (t.draggable) {
        // Make the tile draggable, unless we're showing a dialog
        attrs.draggable = "true";
        attrs.ondragstart = function(coord, ev) {
          // ev.dataTransfer.effectAllowed = "copyMove";
          game.selectedSq = null;
          ev.dataTransfer.effectAllowed = "move";
          ev.dataTransfer.setData("text", coord);
          ev.redraw = false;
        }.bind(null, coord);
        attrs.onclick = function(coord, ev) {
          // When clicking a tile, make it selected (blinking)
          if (coord == game.selectedSq)
            // Clicking again: deselect
            game.selectedSq = null;
          else
            game.selectedSq = coord;
          ev.stopPropagation();
        }.bind(null, coord);
      }
    }
    return m(classes.join("."), attrs,
      [ t.letter == ' ' ? nbsp() : t.letter, m(".letterscore", t.score) ]
    );
  }

  function vwDropTarget(game, coord, child) {
    // Return a td element that is a target for dropping tiles
    var cls = "";
    // Mark the cell with the 'blinking' class if it is the drop
    // target of a pending blank tile dialog
    if (game.askingForBlank !== null && game.askingForBlank.to == coord)
      cls += ".blinking";
    return m("td" + cls,
      {
        id: coord,
        key: coord,
        ondragenter: function(ev) {
          ev.preventDefault();
          ev.dataTransfer.dropEffect = 'move';
          ev.currentTarget.classList.add("over");
          ev.redraw = false;
          return false;
        },
        ondragleave: function(ev) {
          ev.preventDefault();
          ev.currentTarget.classList.remove("over");
          ev.redraw = false;
          return false;
        },
        ondragover: function(ev) {
          // This is necessary to allow a drop
          ev.preventDefault();
          ev.redraw = false;
          return false;
        },
        ondrop: function(to, ev) {
          ev.stopPropagation();
          ev.currentTarget.classList.remove("over");
          // Move the tile from the source to the destination
          var from = ev.dataTransfer.getData("text");
          game.attemptMove(from, to);
          return false;
        }.bind(null, coord),
        onclick: function(to, ev) {
          // If a square is selected (blinking red) and
          // we click on an empty square, move the selected tile
          // to the clicked square
          if (game.selectedSq !== null) {
            ev.stopPropagation();
            game.attemptMove(game.selectedSq, to);
            game.selectedSq = null;
            ev.currentTarget.classList.remove("sel");
            return false;
          }
        }.bind(null, coord),
        onmouseover: function(ev) {
          // If a tile is selected, show a red selection square
          // around this square when the mouse is over it
          if (game.selectedSq !== null)
            ev.currentTarget.classList.add("sel");
        },
        onmouseout: function(ev) {
          ev.currentTarget.classList.remove("sel");
        }
      },
      child || ""
    );
  }

  function vwBoard(game) {
    // The game board, a 15x15 table plus row (A-O) and column (1-15) identifiers

    function colid() {
      // The column identifier row
      var r = [];
      r.push(m("td"));
      for (var col = 1; col <= 15; col++)
        r.push(m("td", col.toString()));
      return m("tr.colid", r);
    }

    function row(rowid) {
      // Each row of the board
      var r = [];
      r.push(m("td.rowid", { key: "R" + rowid }, rowid));
      for (var col = 1; col <= 15; col++) {
        var coord = rowid + col.toString();
        if (game && (coord in game.tiles))
          // There is a tile in this square: render it
          r.push(m("td",
            {
              id: coord,
              key: coord,
              ondragover: function(ev) { ev.stopPropagation(); },
              ondrop: function(ev) { ev.stopPropagation(); }
            },
            vwTile(game, coord))
          );
        else
          // Empty square which is a drop target
          r.push(vwDropTarget(game, coord));
      }
      return m("tr", r);
    }

    function allrows() {
      // Return a list of all rows on the board
      var r = [];
      r.push(colid());
      var rows = "ABCDEFGHIJKLMNO";
      for (var i = 0; i < rows.length; i++)
        r.push(row(rows[i]));
      return r;
    }

    return m(".board", m("table.board", m("tbody", allrows())));
  }

  function vwRack(game) {
    // A rack of 7 tiles
    var r = [];
    for (var i = 1; i <= RACK_SIZE; i++) {
      var coord = 'R' + i.toString();
      if (game && (coord in game.tiles))
        // We have a tile in this rack slot, but it is a drop target anyway
        r.push(vwDropTarget(game, coord, vwTile(game, coord)));
      else
        // Empty rack slot which is a drop target
        r.push(vwDropTarget(game, coord));
    }
    return m(".rack", m("table.board", m("tbody", m("tr", r))));
  }

  function vwScore(game) {
    // Shows the score of the current word
    var sc = [ ".score" ];
    if (game.manual)
      sc.push("manual");
    else
    if (game.wordGood) {
      sc.push("word-good");
      if (game.currentScore >= 50)
        sc.push("word-great");
    }
    return m(
      sc.join("."),
      game.currentScore === undefined ? "?" : game.currentScore
    );
  }

  function vwScoreReview(game, move) {
    // Shows the score of the current move within a game review screen
    var sc = [ ".score" ];
    var mv = move ? game.moves[move - 1] : undefined;
    var score = mv ? mv[1][2] : undefined;
    // TODO: Add logic to select class .green or .yellow depending
    // TODO: on whose move it is
    return m(
      sc.join("."),
      score === undefined ? "" : score.toString()
    );
  }

  function vwStatsReview(game) {
    // Shows the game statistics overlay
    if (game.stats === null)
      // No stats yet loaded: do it now
      game.loadStats();

    function fmt(p, digits, value) {
      var txt = value;
      if (txt === undefined && game.stats)
          txt = game.stats[p];
      if (txt === undefined)
        return "";
      if (digits !== undefined && digits > 0)
        txt = txt.toFixed(digits).replace(".", ","); // Convert decimal point to comma
      return txt;
    }

    return m(
      ".gamestats", { style: { visibility: "visible" } },
      [
        m("div", { style: { position: "relative", width: "100%" } },
          [
            m("h3.playerleft", { style: { width: "50%" } }, 
              m(".robot-btn.left",
                game.autoplayer[0] ?
                  [ glyph("cog"), nbsp(), game.nickname[0] ]
                :
                  game.nickname[0]
              )
            ),
            m("h3.playerright", { style: { width: "50%" } },
              m(".robot-btn.right",
                game.autoplayer[1] ?
                  [ glyph("cog"), nbsp(), game.nickname[1] ]
                :
                  game.nickname[1]
              )
            )
          ]
        ),
        m("div", { id: "gamestarted" },
          [
            m("p",
              [
                "Viðureignin hófst ",
                m("span", fmt("gamestart")), m("br"),
                "og henni lauk ",
                m("span", fmt("gameend"))
              ]
            ),
            game.newbag ?
              m("p",
                [
                  "Leikið var", game.manual ? m("b", " í keppnisham") : "",
                  " með", m("b", " nýja"), " skraflpokanum."
                ]
              )
              :
              m("p",
                [
                  "Leikið var", game.manual ? m("b", " í keppnisham") : "",
                  " með", m("b", " eldri"), " (upphaflega) skraflpokanum."
                ]
              )
          ]
        ),
        m(".statscol", { style: { clear: "left" } },
          [
            m("p",
              [ "Fjöldi leikja: ", m("span", fmt("moves0")) ]
            ),
            m("p",
              [
                "Fjöldi bingóa: ", m("span", fmt("bingoes0")),
                " (bónus ",
                m(
                  "span",
                  fmt("bingopoints0", 0, !game.stats ? 0 : game.stats.bingoes0 * 50)
                ),
                " stig)"
              ]
            ),
            m("p",
              [
                "Stafir lagðir niður: ", m("span", fmt("tiles0")),
                " (þar af ", m("span", fmt("blanks0")), " auðir)"
              ]
            ),
            m("p",
              [
                "Meðalstig stafa (án auðra): ", m("span", fmt("average0", 2))
              ]
            ),
            m("p",
              [
                "Samanlögð stafastig: ", m("span", fmt("letterscore0"))
              ]
            ),
            m("p",
              [
                "Margföldun stafastiga: ", m("span", fmt("multiple0", 2))
              ]
            ),
            m("p",
              [
                "Stig án stafaleifar í lok: ", m("span", fmt("cleantotal0"))
              ]
            ),
            m("p",
              [
                "Meðalstig hvers leiks: ", m("span", fmt("avgmove0", 2))
              ]
            ),
            game.manual ?
              m("p",
                [
                  "Rangar véfengingar andstæðings x 10: ", m("span", fmt("wrongchall0"))
                ]
              )
              : "",
            m("p",
              [
                "Stafaleif og frádráttur í lok: ", m("span", fmt("remaining0"))
              ]
            ),
            m("p",
              [
                "Umframtími: ", m("span", fmt("overtime0"))
              ]
            ),
            m("p",
              [
                "Stig: ",
                m(
                  "span",
                  fmt("total0", 0, !game.stats ? 0 : game.stats.scores[0])
                ),
                " (", m("span", fmt("ratio0", 1)), "%)"
              ]
            )
          ]
        ),
        m(".statscol",
          [
            m("p",
              [ "Fjöldi leikja: ", m("span", fmt("moves1")) ]
            ),
            m("p",
              [
                "Fjöldi bingóa: ", m("span", fmt("bingoes1")),
                " (bónus ",
                m(
                  "span",
                  fmt("bingopoints0", 0, !game.stats ? 0 : game.stats.bingoes1 * 50)
                ),
                " stig)"
              ]
            ),
            m("p",
              [
                "Stafir lagðir niður: ", m("span", fmt("tiles1")),
                " (þar af ", m("span", fmt("blanks1")), " auðir)"
              ]
            ),
            m("p",
              [
                "Meðalstig stafa (án auðra): ", m("span", fmt("average1", 2))
              ]
            ),
            m("p",
              [
                "Samanlögð stafastig: ", m("span", fmt("letterscore1"))
              ]
            ),
            m("p",
              [
                "Margföldun stafastiga: ", m("span", fmt("multiple1", 2))
              ]
            ),
            m("p",
              [
                "Stig án stafaleifar í lok: ", m("span", fmt("cleantotal1"))
              ]
            ),
            m("p",
              [
                "Meðalstig hvers leiks: ", m("span", fmt("avgmove1", 2))
              ]
            ),
            game.manual ?
              m("p",
                [
                  "Rangar véfengingar andstæðings x 10: ", m("span", fmt("wrongchall1"))
                ]
              )
              : "",
            m("p",
              [
                "Stafaleif og frádráttur í lok: ", m("span", fmt("remaining1"))
              ]
            ),
            m("p",
              [
                "Umframtími: ", m("span", fmt("overtime1"))
              ]
            ),
            m("p",
              [
                "Stig: ",
                m(
                  "span",
                  fmt("total1", 0, !game.stats ? 0 : game.stats.scores[1])
                ),
                " (", m("span", fmt("ratio1", 1)), "%)"
              ]
            )
          ]
        ),
        m(".closebtn",
          {
            id: "review-close",
            onclick: function(ev) {
              // Navigate to move #1
              m.route.set("/review/" + game.uuid, { move: 1 });
              ev.preventDefault();
            },
            onmouseover: buttonOver,
            onmouseout: buttonOut
          },
          [ glyph("play"), " Rekja" ]
        )
      ]
    );
  }

  function makeButton(cls, disabled, func, title, children, id) {
    // Create a button element, wrapping the disabling logic
    // and other boilerplate
    var attr = {
      onmouseout: buttonOut,
      onmouseover: buttonOver,
      title: title
    };
    if (id !== undefined)
      attr.id = id;
    if (disabled)
      attr.onclick = function(ev) { ev.preventDefault(); };
    else
      attr.onclick = function(func, ev) {
        if (func)
          func();
        ev.preventDefault();
      }.bind(null, func);
    return m("." + cls + (disabled ? ".disabled" : ""),
      attr, children // children may be omitted
    );
  }

  function vwButtons(game) {
    // The set of buttons below the game board, alongside the rack

    var tilesPlaced = game.tilesPlaced().length > 0;
    var gameOver = game.over;
    var localTurn = game.localturn;
    var gameIsManual = game.manual;
    var challengeAllowed = game.chall;
    var lastChallenge = game.last_chall;
    var showingDialog = game.showingDialog !== null;
    var exchangeAllowed = game.xchg;
    var tardyOpponent = !localTurn && !gameOver && game.overdue;
    var showResign = false;
    var showExchange = false;
    var showPass = false;
    var showRecall = false;
    var showScramble = false;
    var showMove = false;
    var showChallenge = false;
    var showChallengeInfo = false;
    if (localTurn && !gameOver)
      // This player's turn
      if (lastChallenge) {
        showChallenge = true;
        showPass = true;
        showChallengeInfo = true;
      }
      else {
        showMove = tilesPlaced;
        showExchange = !tilesPlaced;
        showPass = !tilesPlaced;
        showResign = !tilesPlaced;
        showChallenge = !tilesPlaced && gameIsManual && challengeAllowed;
      }
    if (!gameOver)
      if (tilesPlaced)
        showRecall = true;
      else
        showScramble = true;
    var r = [];
    r.push(m(".word-check" +
      (game.wordGood ? ".word-good" : "") +
      (game.wordBad ? ".word-bad" : "")));
    if (showChallenge)
      r.push(
        makeButton(
          "challenge", (tilesPlaced && !lastChallenge) || showingDialog,
          function() { game.submitChallenge(); },
          'Véfenging (röng kostar 10 stig)'
        )
      );
    if (showChallengeInfo)
      r.push(m(".chall-info"));
    if (showRecall)
      r.push(
        makeButton(
          "recallbtn", false,
          function() { game.resetRack(); },
          "Færa stafi aftur í rekka", glyph("down-arrow")
        )
      );
    if (showScramble)
      r.push(
        makeButton("scramblebtn", showingDialog,
          function() { game.rescrambleRack(); },
          "Stokka upp rekka", glyph("random")
        )
      );
    if (showMove)
      r.push(
        makeButton(
          "submitmove", !tilesPlaced || showingDialog,
          function() { game.submitMove(); },
          "Leika", [ "Leika", nbsp(), glyph("play") ]
        )
      );
    if (showPass)
      r.push(
        makeButton(
          "submitpass", (tilesPlaced && !lastChallenge) || showingDialog,
          function() { game.submitPass(); },
          "Pass", glyph("forward")
        )
      );
    if (showExchange)
      r.push(
        makeButton(
          "submitexchange", tilesPlaced || showingDialog || !exchangeAllowed,
          function() { game.submitExchange(); },
          "Skipta stöfum", glyph("refresh")
        )
      );
    if (showResign)
      r.push(
        makeButton(
          "submitresign", showingDialog,
          function() { game.submitResign(); },
          "Gefa viðureign", glyph("fire")
        )
      );
    if (!gameOver && !localTurn)
      // Indicate that it is the opponent's turn; offer to force a resignation
      // if the opponent hasn't moved for 14 days
      r.push(m(".opp-turn", { style: { visibility: "visible" } },
        [
          m("span.move-indicator"), m("strong", game.nickname[1 - game.player]), " á leik",
          tardyOpponent ? m("span.yesnobutton",
            {
              id: 'force-resign',
              onclick: function(ev) { ev.preventDefault(); }, // !!! TBD !!!
              onmouseout: buttonOut,
              onmouseover: buttonOver,
              title: '14 dagar liðnir án leiks'
            },
            "Þvinga til uppgjafar"
          ) : ""
        ]
      ));
    if (tilesPlaced)
      r.push(vwScore(game));
    // Is the server processing a move?
    if (game.moveInProgress)
      r.push(m(".waitmove", { style: { display: "block" } }));
    return r;
  }

  function vwButtonsReview(game, move) {
    // The navigation buttons below the board on the review screen
    var r = [];
    r.push(
      makeButton(
        "navbtn", !move,
        function(move) {
          // Navigate to previous move
          m.route.set(
            "/review/" + game.uuid,
            { move: Math.max(move - 1, 0) }
          );
        }.bind(null, move || 0),
        "Sjá fyrri leik",
        m("span",
          { id: "nav-next-visible" },
          [ glyph("chevron-left"), " Fyrri" ]
        ),
        "navprev"
      )
    );
    r.push(
      makeButton(
        "navbtn", (move === null) || (move >= game.moves.length),
        function(move) {
          // Navigate to next move
          m.route.set(
            "/review/" + game.uuid,
            { move: move + 1 }
          );
        }.bind(null, move || 0),
        "Sjá næsta leik",
        m("span",
          { id: "nav-prev-visible" },
          [ "Næsti ", glyph("chevron-right") ]
        ),
        "navnext"
      )
    );
    r.push(vwScoreReview(game, move));
    return r;
  }

  function vwErrors(game) {
    // Error messages, selectively displayed
    var msg = game.currentMessage || "";
    var errorMessages = {
      1: "Enginn stafur lagður niður",
      2: "Fyrsta orð verður að liggja um miðjureitinn",
      3: "Orð verður að vera samfellt á borðinu",
      4: "Orð verður að tengjast orði sem fyrir er",
      5: "Reitur þegar upptekinn",
      6: "Ekki má vera eyða í orði",
      7: [ "'", m("span.errword", msg), "' finnst ekki í orðasafni" ],
      8: [ "'", m("span.errword", msg), "' finnst ekki í orðasafni" ],
      9: "Of margir stafir lagðir niður",
      10: "Stafur er ekki í rekkanum",
      11: "Of fáir stafir eftir, skipting ekki leyfð",
      12: "Of mörgum stöfum skipt",
      13: "Leik vantar á borðið - notið F5/Refresh",
      14: "Notandi ekki innskráður - notið F5/Refresh",
      15: "Rangur eða óþekktur notandi",
      16: "Viðureign finnst ekki",
      17: "Viðureign er ekki utan tímamarka",
      18: "Netþjónn gat ekki tekið við leiknum - reyndu aftur",
      19: "Véfenging er ekki möguleg í þessari viðureign",
      20: "Síðasti leikur er ekki véfengjanlegur",
      21: "Aðeins véfenging eða pass leyfileg",
      server: "Netþjónn gat ekki tekið við leiknum - reyndu aftur"
    };

    if (game.currentError in errorMessages) {
      return m(".error", { style: { visibility: "visible" } },
        [
          glyph("exclamation-sign"),
          errorMessages[game.currentError]
        ]
      );
    }
    return "";
  }

  function vwCongrats(game) {
    return game.congratulate ?
      m("div", { id: "congrats", style: { visibility: "visible" } },
        [
          glyph("bookmark"),
          " ",
          m("strong", "Til hamingju með sigurinn!")
        ]
      )
      : "";
  }

  function vwDialogs(game) {
    // Show prompt dialogs below game board, if any
    var r = [];
    if (game.showingDialog === null)
      return r;
    if (game.showingDialog == "chall-info")
      r.push(m(".chall-info", { style: { visibility: "visible" } },
        [
          glyph("info-sign"), nbsp(),
          m("span.pass-explain", "Andstæðingur tæmdi rekkann - þú getur véfengt eða sagt pass")
        ]
      ));
    if (game.showingDialog == "resign")
      r.push(m(".resign", { style: { visibility: "visible" } },
        [
          glyph("exclamation-sign"), nbsp(), "Viltu gefa leikinn?", nbsp(),
          m("span.mobile-break", m("br")),
          m("span.yesnobutton", { onclick: function() { game.confirmResign(true); } },
            [ glyph("ok"), " Já" ]
          ),
          m("span.mobile-space"),
          m("span.yesnobutton", { onclick: function() { game.confirmResign(false); } },
            [ glyph("remove"), " Nei" ]
          )
        ]
      ));
    if (game.showingDialog == "pass")
      r.push(m(".pass", { style: { visibility: "visible" } },
        [
          glyph("forward"), nbsp(), "Segja pass?",
          m("span.pass-explain", "2x3 pöss í röð ljúka viðureign"),
          nbsp(), m("span.mobile-break", m("br")),
          m("span.yesnobutton", { onclick: function() { game.confirmPass(true); } },
            [ glyph("ok"), " Já" ]
          ),
          m("span.mobile-space"),
          m("span.yesnobutton", { onclick: function() { game.confirmPass(false); } },
            [ glyph("remove"), " Nei" ]
          )
        ]
      ));
    if (game.showingDialog == "pass-last")
      r.push(m(".pass-last", { style: { visibility: "visible" } },
        [
          glyph("forward"), nbsp(), "Segja pass?",
          m("span.pass-explain", "Viðureign lýkur þar með"),
          nbsp(),
          m("span.mobile-break", m("br")),
          m("span.yesnobutton", { onclick: function() { game.confirmPass(true); } },
            [ glyph("ok"), " Já" ]
          ),
          m("span.mobile-space"),
          m("span.yesnobutton", { onclick: function() { game.confirmPass(false); } },
            [ glyph("remove"), " Nei" ]
          )
        ]
      ));
    if (game.showingDialog == "exchange")
      r.push(m(".exchange", { style: { visibility: "visible" } },
        [
          glyph("refresh"), nbsp(),
          "Smelltu á flísarnar sem þú vilt skipta", nbsp(),
          m("span.mobile-break", m("br")),
          m("span.yesnobutton[title='Skipta']",
            { onclick: function() { game.confirmExchange(true); } },
            glyph("ok")),
          m("span.mobile-space"),
          m("span.yesnobutton[title='Hætta við']",
            { onclick: function() { game.confirmExchange(false); } },
            glyph("remove"))
        ]
      ));
    if (game.showingDialog == "chall")
      r.push(m(".chall", { style: { visibility: "visible" } },
        [
          glyph("ban-circle"), nbsp(), "Véfengja lögn?",
          m("span.pass-explain", "Röng véfenging kostar 10 stig"), nbsp(),
          m("span.mobile-break", m("br")),
          m("span.yesnobutton",
            { onclick: function() { game.confirmChallenge(true); } },
            [ glyph("ok"), " Já" ]
          ),
          m("span.mobile-space"),
          m("span.yesnobutton",
            { onclick: function() { game.confirmChallenge(false); } },
            [ glyph("remove"), " Nei" ]
          )
        ]
      ));
    return r;
  }

  function vwTwoLetter() {
    // The two-letter-word list tab
    var page0 =
      m(".twoletter-area[title='Smelltu til að raða eftir seinni staf']", 
        m("span",
          m.trust(
            "<b>a</b>ð af ak al an ar as at ax<br>" +
            "<b>á</b>a áð ái ál ám án ár ás át<br>" +
            "<b>b</b>í bú bý bæ&nbsp;&nbsp;" +
            "<b>d</b>á do dó dý<br>" +
            "<b>e</b>ð ef eg ei ek el em en er es et ex ey<br>" +
            "<b>é</b>g él ét&nbsp;&nbsp;" +
            "<b>f</b>a fá fé fæ&nbsp;&nbsp;" +
            "<b>g</b>á<br>" +
            "<b>h</b>a há hí hó hý hæ&nbsp;&nbsp;" +
            "<b>i</b>ð il im&nbsp;&nbsp;" +
            "<b>í</b>ð íl ím ís<br>" +
            "<b>j</b>á je jó jú&nbsp;&nbsp;" +
            "<b>k</b>á ku kú&nbsp;&nbsp;" +
            "<b>l</b>a lá lé ló lú lý læ<br>" +
            "<b>m</b>á mi mó mý&nbsp;&nbsp;" +
            "<b>n</b>á né nó nú ný næ<br>" +
            "<b>o</b>f og oj ok op or<br>" +
            "<b>ó</b>a óð óf ói ók ól óm ón óp ós óx<br>" +
            "<b>p</b>í pu pú pæ&nbsp;&nbsp;" +
            "<b>r</b>á re ré rí ró rú rý ræ<br>" +
            "<b>s</b>á sé sí so sú sý sæ&nbsp;&nbsp;" +
            "<b>t</b>á te té ti tí tó tý<br>" +
            "<b>u</b>m un&nbsp;&nbsp;" +
            "<b>ú</b>a úð úf úi úr út<br>" +
            "<b>v</b>á vé ví vó&nbsp;&nbsp;" +
            "<b>y</b>l ym yr ys<br>" +
            "<b>ý</b>f ýg ýi ýk ýl ýr ýs ýt&nbsp;&nbsp;" +
            "<b>þ</b>á þó þú þý<br>" +
            "<b>æ</b>ð æf æg æi æl æp ær æs æt<br>" +
            "<b>ö</b>l ör ös öt öx"
            )
        )
      );
    var page1 = 
      m(".twoletter-area[title='Smelltu til að raða eftir fyrri staf']", 
        m("span",
          m.trust(
            "á<b>a</b> fa ha la óa úa&nbsp;&nbsp;" +
            "d<b>á</b> fá gá há<br>já ká lá má ná rá sá tá vá þá<br>" +
            "a<b>ð</b> áð eð ið íð óð úð æð&nbsp;&nbsp;" +
            "j<b>e</b> re te<br>" +
            "f<b>é</b> lé né ré sé té vé&nbsp;" +
            "a<b>f</b> ef of óf úf ýf æf<br>" +
            "e<b>g</b> ég og ýg æg&nbsp;&nbsp;" +
            "á<b>i</b> ei mi ói ti úi ýi æi<br>" +
            "b<b>í</b> hí pí rí sí tí ví&nbsp;&nbsp;" +
            "o<b>j</b>&nbsp;&nbsp;" +
            "a<b>k</b> ek ok ók ýk<br>" +
            "a<b>l</b> ál el él il íl ól yl ýl æl öl<br>" +
            "á<b>m</b> em im ím óm um ym<br>" +
            "a<b>n</b> án en ón un&nbsp;&nbsp;" +
            "d<b>o</b> so<br>" +
            "d<b>ó</b> hó jó ló mó nó ró tó vó þó<br>" +
            "o<b>p</b> óp æp&nbsp;&nbsp;" +
            "a<b>r</b> ár er or úr yr ýr ær ör<br>" +
            "a<b>s</b> ás es ís ós ys ýs æs ös<br>" +
            "a<b>t</b> át et ét út ýt æt öt<br>" +
            "k<b>u</b> pu&nbsp;&nbsp;" +
            "b<b>ú</b> jú kú lú nú pú rú sú þú<br>" +
            "a<b>x</b> ex óx öx&nbsp;&nbsp;" +
            "e<b>y</b><br>" +
            "b<b>ý</b> dý hý lý mý ný rý sý tý þý<br>" +
            "b<b>æ</b> fæ hæ læ næ pæ ræ sæ"
          )
        )
      );

    return {
      page: 0, // Local state, held within the component
      view: function(vnode) {
        return m(".twoletter",
          {
            // Switch between pages when clicked
            onclick: function() { this.page = 1 - this.page; }.bind(this),
            style: "z-index: 6" // Appear on top of board on mobile
          },
          // Show the requested page
          this.page === 0 ? page0 : page1
        );
      }
    };
  }

  function vwBeginner(game) {
    // Show the board color guide
    return m(".board-help",
      { title: 'Hvernig reitirnir margfalda stigin' },
      [
        m(".board-help-close[title='Loka þessari hjálp']",
          {
            onclick: function (ev) {
              // Close the guide and set a preference not to see it again
              $state.beginner = false;
              game.setUserPref({ beginner: false });
              ev.preventDefault();
            }
          },
          glyph("remove")
        ),
        m(".board-colors",
          [
            m(".board-color[id='triple-word']", ["3 x", m("br"), "orð"] ),
            m(".board-color[id='double-word']", ["2 x", m("br"), "orð"] ),
            m(".board-color[id='triple-letter']", ["3 x", m("br"), "stafur"] ),
            m(".board-color[id='double-letter']", ["2 x", m("br"), "stafur"] ),
            m(".board-color[id='single-letter']", ["1 x", m("br"), "stafur"] )
          ]
        )
      ]
    );
  }

  function vwDialogButton(id, title, func, content, tabindex) {
    // Create a .modal-close dialog button
    var attrs = {
      id: id,
      onclick: func,
      title: title
    };
    if (tabindex !== undefined)
      attrs.tabindex = tabindex;
    return m(DialogButton, attrs, content);
  }

  function blinker() {
    // Toggle the 'over' class on all elements having the 'blinking' class
    var blinkers = document.getElementsByClassName('blinking');
    for (var i = 0; i < blinkers.length; i++)
      blinkers[i].classList.toggle("over");
  }

  function vwSpinner(model, actions) {
    // Show a spinner wait box
    return m(
      ".modal-dialog",
      { id: 'spinner-dialog', style: { visibility: 'visible' } },
      m("div", { id: "user-load", style: { display: "block" } })
    );
  }

  function startSpinner() {
    this.pushDialog("spinner");
  }

  function stopSpinner() {
    this.popDialog();
  }

} // createView

function createActions(model, view) {

  initMediaListener();
  initFirebaseListener();
  attachListenerToUser();

  return {
    onNavigateTo: onNavigateTo,
    onFullScreen: onFullScreen,
    onMobileScreen: onMobileScreen,
    onMoveMessage: onMoveMessage,
    onChatMessage: onChatMessage
  };

  function onNavigateTo(routeName, params) {
    // We have navigated to a new route
    // If navigating to something other than help,
    // we need to have a logged-in user
    model.routeName = routeName;
    model.params = params;
    if (routeName == "game") {
      // New game route: initiate loading of the game into the model
      if (model.game !== null) {
        detachListenerFromGame(model.game.uuid);
        model.game = null;
      }
      // Load the game, and attach it to the Firebase listener once it's loaded
      model.loadGame(params.uuid, attachListenerToGame.bind(this, params.uuid));
    }
    else
    if (routeName == "review") {
      // A game review: detach listener, if any, and load
      // new game if necessary
      if (model.game !== null)
        // !!! This may cause an extra detach - we assume that's OK
        detachListenerFromGame(model.game.uuid);
      if (model.game === null || model.game.uuid != params.uuid)
        // Different game than we had before: load it
        model.loadGame(params.uuid, undefined); // No funcComplete
      if (model.game !== null) {
        var move = params.move;
        // Start with move number 0 by default
        move = (!move) ? 0 : parseInt(move);
        if (isNaN(move) || move < 0)
          move = 0;
        // Load the best moves and show them once they're available
        model.loadBestMoves(move);
      }
    }
    else {
      // Not a game route: delete the previously loaded game, if any
      if (model.game !== null) {
        detachListenerFromGame(model.game.uuid);
        model.game = null;
      }
      if (routeName == "help") {
        // Make sure that the help HTML is loaded upon first use
        model.loadHelp();
      }
      else
      if (routeName == "main") {
        // Force reload of lists
        model.gameList = null;
        model.userListCriteria = null;
        model.userList = null;
        model.challengeList = null;
      }
    }
  }

  function onMoveMessage(json) {
    // Handle a move message from Firebase
    console.log("Move message received: " + JSON.stringify(json));
    model.handleMoveMessage(json);
  }

  function onUserMessage(json) {
    // Handle a user message from Firebase
    console.log("User message received: " + JSON.stringify(json));
    model.handleUserMessage(json);
  }

  function onChatMessage(json) {
    // Handle an incoming chat message
    console.log("Chat message received: " + JSON.stringify(json));
    if (json.from_userid != $state.userId) {
      // The message is from the remote user
      // Put an alert on the chat tab if it is not selected
      /*
      if (markChatMsg()) {
         // The message was seen: inform the server
         sendChatSeenMarker();
      }
      */
    }
    if (model.addChatMessage(json.game, json.from_userid, json.msg, json.ts)) {
      // A chat message was successfully added
      view.notifyChatMessage();
    }
  }

  function onFullScreen() {
    // Take action when min-width exceeds 768
    if (!$state.uiFullscreen) {
      $state.uiFullscreen = true;
      view.notifyMediaChange(model);
      m.redraw();
    }
  }

  function onMobileScreen () {
    if ($state.uiFullscreen) {
      $state.uiFullscreen = false;
      view.notifyMediaChange(model);
      m.redraw();
    }
  }

  function onLandscapeScreen() {
    if (!$state.uiLandscape) {
      $state.uiLandscape = true;
      view.notifyMediaChange(model);
      m.redraw();
    }
  }

  function onPortraitScreen() {
    if ($state.uiLandscape) {
      $state.uiLandscape = false;
      view.notifyMediaChange(model);
      m.redraw();
    }
  }

  function mediaMinWidth667(mql) {
     if (mql.matches) {
        // Take action when min-width exceeds 667
        // (usually because of rotation from portrait to landscape)
        // The board tab is not visible, so the movelist is default
        onLandscapeScreen();
     }
     else {
        // min-width is below 667
        // (usually because of rotation from landscape to portrait)
        // Make sure the board tab is selected
        onPortraitScreen();
     }
  }

  function mediaMinWidth768(mql) {
    if (mql.matches) {
      onFullScreen();
    }
    else {
      onMobileScreen();
    }
  }

  function initMediaListener() {
     // Install listener functions for media changes
     var mql;
     mql = window.matchMedia("(min-width: 667px)");
     if (mql) {
        mediaMinWidth667(mql);
        mql.addListener(mediaMinWidth667);
     }
     mql = window.matchMedia("(min-width: 768px)");
     if (mql) {
        mediaMinWidth768(mql);
        mql.addListener(mediaMinWidth768);
     }
  }

  function initFirebaseListener() {
    // Sign into Firebase with the token passed from the server
    loginFirebase($state.firebaseToken);
  }

  function attachListenerToUser() {
    if ($state.userId)
      attachFirebaseListener('user/' + $state.userId, onUserMessage);
  }

  function detachListenerFromUser() {
    // Stop listening to Firebase notifications for the current user
    if ($state.userId)
      detachFirebaseListener('user/' + $state.userId);
  }

  function attachListenerToGame(uuid) {
    // Listen to Firebase events on the /game/[gameId]/[userId] path
    var basepath = 'game/' + uuid + "/" + $state.userId + "/";
    // New moves
    attachFirebaseListener(basepath + "move", onMoveMessage);
    // New chat messages
    attachFirebaseListener(basepath + "chat", onChatMessage);
  }

  function detachListenerFromGame(uuid) {
    // Stop listening to Firebase events on the /game/[gameId]/[userId] path
    var basepath = 'game/' + uuid + "/" + $state.userId + "/";
    detachFirebaseListener(basepath + "move");
    detachFirebaseListener(basepath + "chat");
  }

} // createActions

function createRouteResolver(model, actions, view) {
  return model.paths.reduce(function(acc, item) {
    acc[item.route] = {
      onmatch: function(params, route) {
        // Automatically close all dialogs when navigating to a new route
        view.popAllDialogs();
        if ($state.userId == "" && item.mustLogin)
          // Attempting to navigate to a new path that
          // requires a login, but the user hasn't logged
          // in: go to the login route
          m.route.set("/login");
        else
          actions.onNavigateTo(item.name, params);
      },
      render: function() {
        return view.appView(model, actions);
      }
    };
    return acc;
  }, {});
}

// General-purpose Mithril components

var TextInput = {

  // Generic text input field

  oninit: function(vnode) {
    this.text = vnode.attrs.initialValue;
  },

  view: function(vnode) {
    var cls = vnode.attrs.class;
    if (cls)
      cls = "." + cls.split().join(".");
    else
      cls = "";
    return m("input.text" + cls,
      {
        id: vnode.attrs.id,
        name: vnode.attrs.id,
        maxlength: vnode.attrs.maxlength,
        tabindex: vnode.attrs.tabindex,
        value: this.text,
        oninput: function(ev) { this.text = ev.target.value; }.bind(this)
      }
    );
  }

};

var MultiSelection = {

  // A multiple-selection div where users can click on child nodes
  // to select them, giving them an addional selection class,
  // typically .selected

  oninit: function(vnode) {
    this.sel = vnode.attrs.initialSelection || 0;
    this.defaultClass = vnode.attrs.defaultClass || "";
    this.selectedClass = vnode.attrs.selectedClass || "selected";
  },

  view: function(vnode) {
    return m("div",
      {
        onclick: function(ev) {
          // Catch clicks that are propagated from children up
          // to the parent div. Find which child originated the
          // click (possibly in descendant nodes) and set
          // the current selection accordingly.
          for (var i = 0; i < this.dom.childNodes.length; i++)
            if (this.dom.childNodes[i].contains(ev.target))
              this.state.sel = i;
          ev.stopPropagation();
        }.bind(vnode),
      },
      vnode.children.map(function(item, i) {
        // A pretty gross approach, but it works: clobber the childrens' className
        // attribute depending on whether they are selected or not
        if (i == this.sel)
          item.attrs.className = this.defaultClass + " " + this.selectedClass;
        else
          item.attrs.className = this.defaultClass;
        return item;
      }.bind(vnode.state))
    );
  }

};

var OnlinePresence = {

  // Shows an icon in grey or green depending on whether a given user
  // is online or not

  _update: function(vnode) {
    m.request({
      method: "POST",
      url: "/onlinecheck",
      body: { user: vnode.attrs.userId }
    }).then(function(json) {
      this.online = json && json.online;
    }.bind(this));
  },

  oninit: function(vnode) {
    this.online = false;
    this._update(vnode);
  },

  view: function(vnode) {
    return m("span",
      {
        id: vnode.attrs.id,
        title: this.online ? "Er álínis" : "Álínis?",
        class: this.online ? "online" : ""
      }
    );
  }

};

var EloPage = {

  // Show the header of an Elo ranking list and then the list itself

  oninit: function(vnode) {
    this.sel = "human"; // Default: show ranking for human games only
  },

  view: function(vnode) {
    return [
      m(".listitem.listheader", { key: vnode.attrs.key },
        [
          m("span.list-ch", glyphGrayed("hand-right", { title: 'Skora á' })),
          m("span.list-rank", "Röð"),
          m("span.list-rank-no-mobile[title='Röð í gær']", "1d"),
          m("span.list-rank-no-mobile[title='Röð fyrir viku']", "7d"),
          m("span.list-nick-elo", "Einkenni"),
          m("span.list-elo[title='Elo-stig']", "Elo"),
          m("span.list-elo-no-mobile[title='Elo-stig í gær']", "1d"),
          m("span.list-elo-no-mobile[title='Elo-stig fyrir viku']", "7d"),
          m("span.list-elo-no-mobile[title='Elo-stig fyrir mánuði']", "30d"),
          m("span.list-games[title='Fjöldi viðureigna']", glyph("th")),
          m("span.list-ratio[title='Vinningshlutfall']", glyph("bookmark")),
          m("span.list-avgpts[title='Meðalstigafjöldi']", glyph("dashboard")),
          m("span.list-info-hdr", "Ferill"),
          m("span.list-newbag", glyphGrayed("shopping-bag", { title: 'Gamli pokinn' })),
          m(".toggler[id='elo-toggler'][title='Með þjörkum eða án']",
            [
              m(".option.x-small",
                {
                  // Show ranking for human games only
                  className: (this.sel == "human" ? "selected" : ""),
                  onclick: function(ev) { this.sel = "human"; }.bind(this),
                },
                glyph("user")
              ),
              m(".option.x-small",
                {
                  // Show ranking for all games, including robots
                  className: (this.sel == "all" ? "selected" : ""),
                  onclick: function(ev) { this.sel = "all"; }.bind(this),
                },
                glyph("cog")
              )
            ]
          )
        ]
      ),
      m(EloList,
        {
          id: vnode.attrs.id,
          sel: this.sel,
          model: vnode.attrs.model,
          view: vnode.attrs.view
        }
      )
    ];
  }

};

var EloList = {

  view: function(vnode) {

    function itemize(item, i) {

      // Generate a list item about a user in an Elo ranking table

      function rankStr(rank, ref) {
         // Return a rank string or dash if no rank or not meaningful
         // (i.e. if the reference, such as the number of games, is zero)
         if (rank === 0 || (ref !== undefined && ref === 0))
            return "--";
         return rank.toString();
      }

      var isRobot = item.userid.indexOf("robot-") === 0;
      var nick = item.nick;
      var ch = "";
      var info = nbsp();
      var newbag = item.newbag;
      if (item.userid != $state.userId && !item.inactive)
        ch = glyph("hand-right", { title: "Skora á" }, !item.chall);
      if (isRobot) {
        nick = m("span", [ glyph("cog"), nbsp(), nick ]);
        newbag = $state.newBag; // Imitates the logged-in user
      }
      else
      if (item.userid != $state.userId)
        info = m("span.usr-info",
          {
            onclick: function(ev) {
              vnode.attrs.view.showUserInfo(this.userid, this.nick, this.fullname);
            }.bind(item)
          }
        );
      if (item.fairplay && !isRobot)
        nick = m("span",
          [ m("span.fairplay-btn", { title: "Skraflar án hjálpartækja" }), nick ]);

      return m(".listitem",
        {
          key: vnode.attrs.sel + i,
          className : (i % 2 === 0 ? "oddlist" : "evenlist")
        },
        [
          m("span.list-ch", ch),
          m("span.list-rank.bold", rankStr(item.rank)),
          m("span.list-rank-no-mobile", rankStr(item.rank_yesterday)),
          m("span.list-rank-no-mobile", rankStr(item.rank_week_ago)),
          m("span.list-nick-elo", { title: item.fullname }, nick),
          m("span.list-elo.bold", item.elo),
          m("span.list-elo-no-mobile", rankStr(item.elo_yesterday, item.games_yesterday)),
          m("span.list-elo-no-mobile", rankStr(item.elo_week_ago, item.games_week_ago)),
          m("span.list-elo-no-mobile", rankStr(item.elo_month_ago, item.games_month_ago)),
          m("span.list-games.bold", item.games),
          m("span.list-ratio", item.ratio),
          m("span.list-avgpts", item.avgpts),
          m("span.list-info", { title: "Skoða feril" }, info),
          m("span.list-newbag", glyph("shopping-bag", { title: "Gamli pokinn" }, newbag))
        ]
      );
    }

    var model = vnode.attrs.model;
    var list = [];
    if (model.userList === undefined)
      ; // Loading in progress
    else
    if (model.userList === null || model.userListCriteria.query != "elo" ||
      model.userListCriteria.spec != vnode.attrs.sel)
      // We're not showing the correct list: request a new one
      model.loadUserList({ query: "elo", spec: vnode.attrs.sel }, true);
    else
      list = model.userList;
    return m("div", { id: vnode.attrs.id }, list.map(itemize));
  }

};

var RecentList = {

  // Shows a list of recent games, stored in vnode.attrs.recentList

  view: function(vnode) {

    function itemize(item, i) {

      // Generate a list item about a recently completed game

      function durationDescription() {
        // Format the game duration
        var duration = "";
        if (item.duration === 0) {
          if (item.days || item.hours || item.minutes) {
            if (item.days > 1)
              duration = item.days.toString() + " dagar";
            else
            if (item.days == 1)
              duration = "1 dagur";
            if (item.hours > 0) {
              if (duration.length)
                duration += " og ";
              duration += item.hours.toString() + " klst";
            }
            if (item.days === 0) {
              if (duration.length)
                duration += " og ";
              if (item.minutes == 1)
                duration += "1 mínúta";
              else
                duration += item.minutes.toString() + " mínútur";
            }
          }
        }
        else
          // This was a timed game
          duration = [
            m("span.timed-btn", { title: 'Viðureign með klukku' }),
            " 2 x " + item.duration + " mínútur"
          ];
        return duration;
      }

      // Show the Elo point adjustments resulting from the game
      var eloAdj = item.elo_adj ? item.elo_adj.toString() : "";
      var eloAdjHuman = item.human_elo_adj ? item.human_elo_adj.toString() : "";
      var eloAdjClass, eloAdjHumanClass;
      // Find out the appropriate class to use depending on the adjustment sign
      if (item.elo_adj !== null)
        if (item.elo_adj > 0) {
          eloAdj = "+" + eloAdj;
          eloAdjClass = "elo-win";
        }
        else
        if (item.elo_adj < 0)
          eloAdjClass = "elo-loss";
        else {
          eloAdjClass = "elo-neutral";
          eloAdj = glyph("stroller", { title: 'Byrjandi' });
        }
      if (item.human_elo_adj !== null)
        if (item.human_elo_adj > 0) {
          eloAdjHuman = "+" + eloAdjHuman;
          eloAdjHumanClass = "elo-win";
        }
        else
        if (item.human_elo_adj < 0)
          eloAdjHumanClass = "elo-loss";
        else {
          eloAdjHumanClass = "elo-neutral";
          eloAdjHuman = glyph("stroller", { title: 'Byrjandi' });
        }
      eloAdj = m("span",
        { class: 'elo-btn right ' + eloAdjClass + (eloAdj == "" ? " invisible" : "") },
        eloAdj
      );
      eloAdjHuman = m("span",
        { class: 'elo-btn left ' + eloAdjHumanClass + (eloAdjHuman == "" ? " invisible" : "") },
        eloAdjHuman
      );

      return m(".listitem" + (i % 2 === 0 ? ".oddlist" : ".evenlist"),
        m(m.route.Link,
          // Clicking on the link opens up the game
          { href: "/game/" + item.url.slice(-36) },
          [
            m("span.list-win",
              item.sc0 >= item.sc1 ?
                glyph("bookmark", { title: item.sc0 == item.sc1 ? "Jafntefli" : "Sigur" }) :
                glyphGrayed("bookmark", { title: "Tap" })
            ),
            m("span.list-ts-short", item.ts_last_move),
            m("span.list-nick",
              item.opp_is_robot ? [ glyph("cog"), nbsp(), item.opp ] : item.opp
            ),
            m("span.list-s0", item.sc0),
            m("span.list-colon", ":"),
            m("span.list-s1", item.sc1),
            m("span.list-elo-adj", eloAdjHuman),
            m("span.list-elo-adj", eloAdj),
            m("span.list-duration", durationDescription()),
            m("span.list-manual",
              item.manual ? { title: "Keppnishamur" } : { },
              glyph("lightbulb", undefined, !item.manual)
            )
          ]
        )
      );
    }

    var list = vnode.attrs.recentList;
    return m("div", { id: vnode.attrs.id }, !list ? "" : list.map(itemize));
  }

};

var UserInfoDialog = {

  // A dialog showing the track record of a given user, including
  // recent games and total statistics

  _updateStats: function(vnode) {
    // Fetch the statistics of the given user
    vnode.attrs.model.loadUserStats(vnode.attrs.userid,
      function(json) {
        if (json && json.result === 0)
          this.stats = json;
        else
          this.stats = { };
      }.bind(this)
    );
  },

  _updateRecentList: function(vnode) {
    // Fetch the recent game list of the given user
    vnode.attrs.model.loadUserRecentList(vnode.attrs.userid,
      this.versusAll ? null : $state.userId,
      function(json) {
        if (json && json.result === 0)
          this.recentList = json.recentlist;
        else
          this.recentList = [];
      }.bind(this)
    );
  },

  _setVersus: function(vnode, state, ev) {
    if (this.versusAll != state) {
      this.versusAll = state;
      this._updateRecentList(vnode);
    }
  },

  oninit: function(vnode) {
    this.stats = { };
    this.recentList = [];
    this.versusAll = true; // Show games against all opponents or just the current user?
    this._updateRecentList(vnode);
    this._updateStats(vnode);
  },

  view: function(vnode) {
    return m(".modal-dialog",
      { id: 'usr-info-dialog', style: { visibility: "visible" } },
      m(".ui-widget.ui-widget-content.ui-corner-all", { id: 'usr-info-form' },
        [
          m(".usr-info-hdr",
            [
              m("h1.usr-info-icon",
                this.stats.friend ? glyph("coffee-cup", { title: 'Vinur Netskrafls' }) : glyph("user")
              ),
              nbsp(),
              m("h1[id='usr-info-nick']", vnode.attrs.nick),
              m("span.vbar", "|"),
              m("h2[id='usr-info-fullname']", vnode.attrs.fullname),
              m(".usr-info-fav",
                {
                  title: 'Uppáhald',
                  onclick: function(ev) {
                    // Toggle the favorite setting
                    this.favorite = !this.favorite;
                    vnode.attrs.model.markFavorite(vnode.attrs.userid, this.favorite);
                    ev.preventDefault();
                  }.bind(this.stats),
                },
                this.stats.favorite ? glyph("star") : glyph("star-empty")
              )
            ]
          ),
          m("p",
            [
              m("strong", "Nýjustu viðureignir"),
              nbsp(),
              m("span.versus-cat",
                [
                  m("span",
                    {
                      class: this.versusAll ? "shown" : "",
                      onclick: this._setVersus.bind(this, vnode, true) // Set this.versusAll to true
                    },
                    " gegn öllum "
                  ),
                  m("span",
                    {
                      class: this.versusAll ? "" : "shown",
                      onclick: this._setVersus.bind(this, vnode, false) // Set this.versusAll to false
                    },
                    " gegn þér "
                  )
                ]
              )
            ]
          ),
          m(".listitem.listheader",
            [
              m("span.list-win", glyphGrayed("bookmark", { title: 'Sigur' })),
              m("span.list-ts-short", "Viðureign lauk"),
              m("span.list-nick", "Andstæðingur"),
              m("span.list-scorehdr", "Úrslit"),
              m("span.list-elo-hdr",
                [
                  m("span.glyphicon.glyphicon-user.elo-hdr-left[title='Mennskir andstæðingar']"),
                  "Elo",
                  m("span.glyphicon.glyphicon-cog.elo-hdr-right[title='Allir andstæðingar']")
                ]
              ),
              m("span.list-duration", "Lengd"),
              m("span.list-manual", glyphGrayed("lightbulb", { title: 'Keppnishamur' }))
            ]
          ),
          m(RecentList, { id: 'usr-recent', recentList: this.recentList }), // Recent game list
          m(StatsDisplay, { id: 'usr-stats', ownStats: this.stats }),
          m(BestDisplay, { id: 'usr-best', ownStats: this.stats, myself: false }), // Highest word and game scores
          m(DialogButton,
            {
              id: 'usr-info-close',
              title: 'Loka',
              onclick: function(ev) { vnode.attrs.view.popDialog(); }
            },
            glyph("ok")
          )
        ]
      )
    );
  }

};

var BestDisplay = {

  // Display the best words and best games played for a given user

  view: function(vnode) {
    // Populate the highest score/best word field
    var json = vnode.attrs.ownStats || { };
    var best = [];
    if (json.highest_score) {
      best.push("Hæsta skor ");
      best.push(m("b",
        m(m.route.Link,
          { href: "/game/" + json.highest_score_game },
          json.highest_score
        )
      ));
    }
    if (json.best_word) {
      if (best.length)
        if (vnode.attrs.myself)
          best.push(m("br")); // Own stats: Line break between parts
        else
          best.push(" | "); // Opponent stats: Divider bar between parts
      var bw = json.best_word;
      var s = [];
      // Make sure blank tiles get a different color
      for (var i = 0; i < bw.length; i++)
        if (bw[i] == '?') {
          s.push(m("span.blanktile", bw[i+1]));
          i += 1;
        }
        else
          s.push(bw[i]);
      best.push("Besta orð ");
      best.push(m("span.best-word", s));
      best.push(", ");
      best.push(m("b",
        m(m.route.Link,
          { href: "/game/" + json.best_word_game },
          json.best_word_score
        )
      ));
      best.push(" stig");
    }
    return m("p", { id: vnode.attrs.id }, best);
  }

};

var StatsDisplay = {

  // Display key statistics, provided via the ownStats attribute

  oninit: function(vnode) {
    this.sel = 1;
  },

  view: function(vnode) {

    function vwStat(val, icon, suffix) {
      // Display a user statistics figure, eventually with an icon
      var txt = (val === undefined) ? "" : val.toString();
      if (suffix !== undefined)
        txt += suffix;
      return icon ? [ glyph(icon), nbsp(), txt ] : txt;
    }

    // Display statistics about this user
    var s = vnode.attrs.ownStats;
    var winRatio = 0, winRatioHuman = 0;
    if (s !== undefined && s !== null) {
      if (s.games > 0)
        winRatio = Math.round(100.0 * s.wins / s.games);
      if (s.human_games > 0)
        winRatioHuman = Math.round(100.0 * s.human_wins / s.human_games);
    }
    var avgScore = 0, avgScoreHuman = 0;
    if (s !== undefined && s !== null) {
      if (s.games > 0)
        avgScore = Math.round(s.score / s.games);
      if (s.human_games > 0)
        avgScoreHuman = Math.round(s.human_score / s.human_games);
    }

    return m("div", { id: vnode.attrs.id },
      [
        m(".toggler", { id: 'own-toggler', title: 'Með þjörkum eða án' },
          [
            m(".option.small" + (this.sel == 1 ? ".selected" : ""),
              { id: 'opt1', onclick: function(ev) { this.sel = 1; ev.preventDefault(); }.bind(this), },
              glyph("user")
            ),
            m(".option.small" + (this.sel == 2 ? ".selected" : ""),
              { id: 'opt2', onclick: function(ev) { this.sel = 2; ev.preventDefault(); }.bind(this), },
              glyph("cog")
            )
          ]
        ),
        this.sel == 1 ? m("div",
          { id: 'own-stats-human', className: 'stats-box', style: { display: "inline-block"} },
          [
            m(".stats-fig", { title: 'Elo-stig' },
              s ? vwStat(s.human_elo, "crown") : ""),
            m(".stats-fig.stats-games", { title: 'Fjöldi viðureigna' },
              s ? vwStat(s.human_games, "th") : ""),
            m(".stats-fig.stats-win-ratio", { title: 'Vinningshlutfall' },
              vwStat(winRatioHuman, "bookmark", "%")),
            m(".stats-fig.stats-avg-score", { title: 'Meðalstigafjöldi' },
              vwStat(avgScoreHuman, "dashboard"))
          ]
        ) : "",
        this.sel == 2 ? m("div",
          { id: 'own-stats-all', className: 'stats-box', style: { display: "inline-block"} },
          [
            m(".stats-fig", { title: 'Elo-stig' },
              s ? vwStat(s.elo, "crown") : ""),
            m(".stats-fig.stats-games", { title: 'Fjöldi viðureigna' },
              s ? vwStat(s.games, "th") : ""),
            m(".stats-fig.stats-win-ratio", { title: 'Vinningshlutfall' },
              vwStat(winRatio, "bookmark", "%")),
            m(".stats-fig.stats-avg-score", { title: 'Meðalstigafjöldi' },
              vwStat(avgScore, "dashboard"))
          ]
        ) : ""
      ]
    );
  }

};

var PromoDialog = {

  // A dialog showing promotional content fetched from the server

  _fetchContent: function(vnode) {
    // Fetch the content
    vnode.attrs.model.loadPromoContent(vnode.attrs.key,
      function(html) {
        this.html = html;
      }.bind(this)
    );
  },

  oninit: function(vnode) {
    this.html = "";
    this._fetchContent(vnode);
  },

  view: function(vnode) {
    var appView = vnode.attrs.view;
    return m(".modal-dialog",
      { id: "promo-dialog", style: { visibility: "visible" } },
      m(".ui-widget.ui-widget-content.ui-corner-all",
        { id: "promo-form", className: "promo-" + vnode.attrs.key },
        m("div",
          {
            id: "promo-content",
            onupdate: function(vnode) {
              var i, noButtons = vnode.dom.getElementsByClassName("btn-promo-no");
              // Override onclick, onmouseover and onmouseout for No buttons
              for (i = 0; i < noButtons.length; i++) {
                noButtons[i].onclick = function(ev) { this.popDialog(); }.bind(appView);
                noButtons[i].onmouseover = buttonOver;
                noButtons[i].onmouseout = buttonOut;
              }
              // Override onmouseover and onmouseout for Yes buttons
              var yesButtons = vnode.dom.getElementsByClassName("btn-promo-yes");
              for (i = 0; i < yesButtons.length; i++) {
                yesButtons[i].onmouseover = buttonOver;
                yesButtons[i].onmouseout = buttonOut;
              }
            }
          },
          m.trust(this.html)
        )
      )
    );
  }

};

function SearchButton(vnode) {

  // A combination of a button and pattern entry field
  // for user search

  var spec = ""; // The current search pattern
  var model = vnode.attrs.model;
  var promise;

  function newSearch() {
    // There may have been a change of search parameters: react
    if (promise !== undefined) {
      // There was a previous promise, now obsolete: make it
      // resolve without action
      promise.result = false;
      promise = undefined;
    }
    var sel = model.userListCriteria ? model.userListCriteria.query : "robots";
    if (sel != "search") {
      // Not already in a search: load the user list immediately
      model.loadUserList({ query: "search", spec: spec }, true);
      return;
    }
    if (spec == model.userListCriteria.spec)
      // We're already looking at the same search spec: done
      return;
    // We're changing the search spec.
    // In order to limit the number of search queries sent to
    // the server while typing a new criteria, we keep an
    // outstanding promise that resolves in 0.8 seconds,
    // unless cancelled by a new keystroke/promise.
    // Note: since a promise can't be directly cancelled, we use a
    // convoluted route to associate a boolean result with it.
    var newP = {
      result: true,
      p: new Promise(function(resolve, reject) {
        // After 800 milliseconds, resolve to whatever value the
        // result property has at that time. It will be true
        // unless the promise has been "cancelled" by setting
        // its result property to false.
        setTimeout(function() { resolve(newP.result); }, 800);
      })
    };
    promise = newP;
    promise.p.then(function(value) {
      if (value) {
        // Successfully resolved, without cancellation:
        // issue the search query to the server as it now stands
        model.loadUserList({ query: "search", spec: spec }, true);
        promise = undefined;
      }
    });
  }

  return {
    view: function() {
      var sel = model.userListCriteria ? model.userListCriteria.query : "robots";
      return m(".user-cat[id='user-search']",
        [
          glyph("search",
            {
              id: 'search',
              className: (sel == "search" ? "shown" : ""),
              onclick: function(ev) {
                // Reset the search pattern when clicking the search icon
                spec = "";
                newSearch();
                document.getElementById("search-id").focus();
              }
            }
          ),
          nbsp(),
          m("input.text.userid",
            {
              type: 'text',
              id: 'search-id',
              name: 'search-id',
              maxlength: 16,
              placeholder: 'Einkenni eða nafn',
              value: spec,
              onfocus: function(ev) {
                newSearch();
              },
              oninput: function(ev) {
                spec = ev.target.value;
                newSearch();
              }
            }
          )
        ]
      );
    }
  };
}

var DialogButton = {

  view: function(vnode) {
    var attrs = {
      onmouseout: buttonOut,
      onmouseover: buttonOver
    };
    for (var a in vnode.attrs)
      attrs[a] = vnode.attrs[a];
    return m(".modal-close", attrs, vnode.children);
  }

};

// Utility functions

function escapeHtml(string) {
   /* Utility function to properly encode a string into HTML */
  var entityMap = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': '&quot;',
    "'": '&#39;',
    "/": '&#x2F;'
  };
  return String(string).replace(/[&<>"'/]/g, function (s) {
    return entityMap[s];
  });
}

function replaceEmoticons(str) {
  // Replace all emoticon shortcuts in the string str with a corresponding image URL
  var i;
  var emoticons = $state.emoticons;
  for (i = 0; i < emoticons.length; i++)
    if (str.indexOf(emoticons[i].icon) >= 0) {
      // The string contains the emoticon: prepare to replace all occurrences
      var img = "<img src='" + emoticons[i].image + "' height='32' width='32'>";
      // Re the following trick, see http://stackoverflow.com/questions/1144783/
      // replacing-all-occurrences-of-a-string-in-javascript
      str = str.split(emoticons[i].icon).join(img);
    }
  return str;
}

function getInput(id) {
  // Return the current value of a text input field
  return document.getElementById(id).value;
}

function setInput(id, val) {
  // Set the current value of a text input field
  document.getElementById(id).value = val;
}

// Utility functions to set up tabbed views

function updateTabVisibility(vnode) {
  // Shows the tab that is currently selected,
  // i.e. the one whose index is in vnode.state.selected
  var selected = vnode.state.selected;
  var lis = vnode.state.lis;
  vnode.state.ids.map(function(id, i) {
      document.getElementById(id).setAttribute("style", "display: " +
        (i == selected ? "block" : "none"));
      lis[i].classList.toggle("ui-tabs-active", i == selected);
      lis[i].classList.toggle("ui-state-active", i == selected);
    }
  );
}

function selectTab(vnode, i) {
  // Selects the tab with the given index under the tab control vnode
  vnode.state.selected = i;
  updateTabVisibility(vnode);
}

function makeTabs(id, createFunc, wireHrefs, vnode) {
  // When the tabs are displayed for the first time, wire'em up
  var tabdiv = document.getElementById(id);
  if (!tabdiv)
    return;
  var view = this;
  // Add bunch of jQueryUI compatible classes
  tabdiv.setAttribute("class", "ui-tabs ui-widget ui-widget-content ui-corner-all");
  var tabul = document.querySelector("#" + id + " > ul");
  tabul.setAttribute("class", "ui-tabs-nav ui-helper-reset ui-helper-clearfix ui-widget-header ui-corner-all");
  tabul.setAttribute("role", "tablist");
  var tablist = document.querySelectorAll("#" + id + " > ul > li > a");
  var tabitems = document.querySelectorAll("#" + id + " > ul > li");
  var ids = [];
  var lis = []; // The <li> elements
  var i;
  // Iterate over the <a> elements inside the <li> elements inside the <ul>
  for (i = 0; i < tablist.length; i++) {
    ids.push(tablist[i].getAttribute("href").slice(1));
    // Decorate the <a> elements
    tablist[i].onclick = function(i, ev) {
        // When this tab header is clicked, select the associated tab
        selectTab(this, i);
        ev.preventDefault();
      }
      .bind(vnode, i);
    tablist[i].setAttribute("href", null);
    tablist[i].setAttribute("class", "ui-tabs-anchor sp"); // Single-page marker
    tablist[i].setAttribute("role", "presentation");
    // Also decorate the <li> elements
    lis.push(tabitems[i]);
    tabitems[i].setAttribute("class", "ui-state-default ui-corner-top");
    tabitems[i].setAttribute("role", "tab");
    tabitems[i].onmouseover = function(ev) { ev.currentTarget.classList.toggle("ui-state-hover", true); };
    tabitems[i].onmouseout = function(ev) { ev.currentTarget.classList.toggle("ui-state-hover", false); };
    // Find the tab's content <div>
    var tabcontent = document.getElementById(ids[i]);
    // Decorate it
    tabcontent.setAttribute("class", "ui-tabs-panel ui-widget-content ui-corner-bottom");
    tabcontent.setAttribute("role", "tabpanel");
  }
  // Save the list of tab identifiers
  vnode.state.ids = ids;
  // Save the list of <li> elements
  vnode.state.lis = lis;
  // Select the first tab by default
  vnode.state.selected = 0;
  if (wireHrefs) {
    // Wire all hrefs that point to single-page URLs
    var anchors = tabdiv.querySelectorAll("a");
    for (i = 0; i < anchors.length; i++) {
      var a = anchors[i];
      var href = a.getAttribute("href");
      if (href && href.slice(0, ROUTE_PREFIX_LEN) == ROUTE_PREFIX) {
        // Single-page URL: wire it up (as if it had had an m.route.Link on it)
        a.onclick = function(href, ev) {
          var uri = href.slice(ROUTE_PREFIX_LEN); // Cut the /page#!/ prefix off the route
          var qix = uri.indexOf("?");
          var route = (qix >= 0) ? uri.slice(0, qix) : uri;
          var qparams = uri.slice(route.length + 1);
          var params = qparams.length ? getUrlVars(qparams) : { };
          m.route.set(route, params);
          if (window.history)
            window.history.pushState({}, "", href); // Enable the back button
          ev.preventDefault();
        }.bind(null, href);
      }
      else
      if (href && href == "$$userprefs$$") {
        // Special marker indicating that this link invokes
        // a user preference dialog
        a.onclick = function(ev) {
          if ($state.userId != "")
            // Don't show the userprefs if no user logged in
            this.pushDialog("userprefs");
          ev.preventDefault();
        }.bind(view);
      }
      else
      if (href && href == "$$twoletter$$") {
        // Special marker indicating that this link invokes
        // the two-letter word list or the opponents tab
        a.onclick = function(ev) {
          selectTab(this, 2); // Select tab number 2
          ev.preventDefault();
        }.bind(vnode);
      }
      else
      if (href && href == "$$newbag$$") {
        // Special marker indicating that this link invokes
        // the explanation of the new bag
        a.onclick = function(ev) {
          selectTab(this, 3); // Select tab number 3
          ev.preventDefault();
        }.bind(vnode);
      }
    }
  }
  // If a createFunc was specified, run it now
  if (createFunc)
    createFunc(vnode);
  // Finally, make the default tab visible and hide the others
  updateTabVisibility(vnode);
}

function updateSelection(vnode) {
  // Select a tab according to the ?tab= query parameter in the current route
  var tab = m.route.param("tab");
  if (tab !== undefined)
    selectTab(vnode, tab);
}

// Get values from a URL query string
function getUrlVars(url) {
   var hashes = url.split('&');
   var vars = { };
   for (var i = 0; i < hashes.length; i++) {
      var hash = hashes[i].split('=');
      if (hash.length == 2)
        vars[hash[0]] = decodeURIComponent(hash[1]);
   }
   return vars;
}

function buttonOver(ev) {
  var clist = ev.currentTarget.classList;
  if (clist !== undefined && !clist.contains("disabled"))
    clist.add("over");
  ev.redraw = false;
}

function buttonOut(ev) {
  var clist = ev.currentTarget.classList;
  if (clist !== undefined)
    clist.remove("over");
  ev.redraw = false;
}

// Glyphicon utility function: inserts a glyphicon span
function glyph(icon, attrs, grayed) {
  return m("span.glyphicon.glyphicon-" + icon + (grayed ? ".grayed" : ""), attrs);
}

function glyphGrayed(icon, attrs) {
  return m("span.glyphicon.glyphicon-" + icon + ".grayed", attrs);
}

// Utility function: inserts non-breaking space
function nbsp(n) {
  if (!n || n == 1)
    return m.trust("&nbsp;");
  var r = [];
  for (var i = 0; i < n; i++)
    r.push(m.trust("&nbsp;"));
  return r;
}

return main;

} ());

