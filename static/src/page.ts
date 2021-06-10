/*

	Page.ts

	Single page UI for Explo using the Mithril library

  Copyright (C) 2021 Miðeind ehf.
  Author: Vilhjálmur Þorsteinsson

  The GNU Affero General Public License, version 3, applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

  This UI is built on top of Mithril (https://mithril.js.org), a lightweight,
  straightforward JavaScript single-page reactive UI library.

  The page is structured into models, actions and views,
  cf. https://github.com/pakx/the-mithril-diaries/wiki/Basic-App-Structure

*/

export { main };

import { Game, coord, toVector, RackTile, Move } from "./game.js";
import { addPinchZoom, registerSalesCloud } from "./util.js";

import {
  attachFirebaseListener, detachFirebaseListener, loginFirebase
} from "./channel.js";

import {
  m, Vnode, VnodeAttrs, ComponentFunc, EventHandler, MithrilEvent, VnodeChildren
} from "./mithril.js";

// Constants

const RACK_SIZE = 7;
const BAG_TILES_PER_LINE = 19;
const BLANK_TILES_PER_LINE = 6;
const ROUTE_PREFIX = "/page#!";
const ROUTE_PREFIX_LEN = ROUTE_PREFIX.length;
const BOARD_PREFIX = "/board?game=";
const BOARD_PREFIX_LEN = BOARD_PREFIX.length;
const MAX_CHAT_MESSAGES = 250; // Max number of chat messages per game

// Global state
interface GlobalState {
  userId : string;
  userNick: string;
  beginner: boolean;
  fairPlay: boolean;
  newBag: boolean;
  hasPaid: boolean;
  ready: boolean;
  readyTimed: boolean;
  uiFullscreen: boolean;
  uiLandscape: boolean;
  firebaseToken: string;
  emoticons: { icon: string; image: string; }[];
}

var $state: GlobalState;

// Basic Mithril routing settings
type Path = { name: string; route: string; mustLogin: boolean; };
type Paths = Path[];
interface Settings {
  paths: Paths;
  defaultRoute: string;
}

// Possible URL parameters that are passed to routes
interface Params {
  uuid?: string;
  move?: string;
  tab?: string;
  faq?: string;
}

// Items in a game list
interface GameListItem {
  uuid: string;
  fullname: string;
  my_turn: boolean;
  timed: boolean;
  manual: boolean;
  zombie: boolean;
  overdue: boolean;
  oppid: string;
  opp: string;
  sc0: number;
  sc1: number;
  url: string;
  tile_count: number;
  ts: string;
}

interface UserErrors {
  nickname?: string;
  full_name?: string;
  email?: string;
}

function main(state: GlobalState) {
  // The main UI entry point, called from page.html

  $state = state;

  let
    settings = getSettings(),
    model = new Model(settings),
    view = new View(),
    actions = new Actions(model, view),
    routeResolver = createRouteResolver(actions),
    defaultRoute = settings.defaultRoute,
    root = document.getElementById("container");

  // Run the Mithril router
  m.route(root, defaultRoute, routeResolver);
}

function getSettings(): Settings {
  // Returns an app-wide settings object
  let
    paths: Paths = [
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

class Model {

  // A class for the underlying data model, displayed by the View

  paths: Paths = [];
  // The routeName will be "login", "main", "game"...
  routeName?: string = undefined;
  // Eventual parameters within the route URL, such as the game uuid
  params?: Params = undefined;
  // The current game being displayed, if any
  game: Game = null;
  // The current game list
  gameList?: GameListItem[] = null;
  // The current challenge list
  challengeList?: any[] = null;
  // Recent games
  recentList?: any[] = null;
  // The currently displayed user list
  userListCriteria?: { query: string; spec: string; } = null;
  userList?: any[] = null;
  // The user's own statistics
  ownStats: any = null;
  // The current user information being edited, if any
  user: any = null;
  userErrors: UserErrors = null;
  // The help screen contents
  helpHTML?: string = null;
  // Outstanding requests
  spinners: number = 0;
  // The index of the game move being reviewed, if any
  reviewMove?: number = null;
  // The best moves available at this stage, if reviewing game
  bestMoves?: Move[] = null;
  // The index of the best move being highlighted, if reviewing game
  highlightedMove?: number = null;
  // The current scaling of the board
  boardScale: number = 1.0;

  constructor(settings: Settings) {
    this.paths = settings.paths.slice();
  }

  loadGame(uuid: string, funcComplete: () => void) {
    // Fetch a game state from the server, given a uuid
    // console.log("Initiating load of game " + uuid);
    m.request({
      method: "POST",
      url: "/gamestate",
      body: { game: uuid }
    })
    .then((result: { ok: boolean; game: any; }) => {
      if (this.game !== null)
        // We have a prior game in memory:
        // clean it up before allocating the new one
        this.game.cleanup();
      this.game = null;
      this.reviewMove = null;
      this.bestMoves = null;
      this.highlightedMove = null;
      this.boardScale = 1.0;
      if (!result.ok) {
        // console.log("Game " + uuid + " could not be loaded");
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
    });
  }

  loadGameList(includeZombies: boolean = true) {
    // Load the list of currently active games for this user
    this.gameList = undefined; // Loading in progress
    m.request({
      method: "POST",
      url: "/gamelist",
      body: { zombie: includeZombies }
    })
    .then((json: { result: number; gamelist: GameListItem[]; }) => {
      if (!json || json.result !== 0) {
        // An error occurred
        this.gameList = null;
        return;
      }
      this.gameList = json.gamelist || [];
    });
  }

  loadChallengeList() {
    // Load the list of current challenges (received and issued)
    this.challengeList = []; // Prevent concurrent loading
    m.request({
      method: "POST",
      url: "/challengelist"
    })
    .then((json: { result: number; challengelist: any; }) => {
      if (!json || json.result !== 0) {
        // An error occurred
        this.challengeList = null;
        return;
      }
      this.challengeList = json.challengelist;
    });
  }

  loadRecentList() {
    // Load the list of recent games for this user
    this.recentList = []; // Prevent concurrent loading
    m.request({
      method: "POST",
      url: "/recentlist",
      body: { versus: null, count: 40 }
    })
    .then((json: { result: number; recentlist: any; }) => {
      if (!json || json.result !== 0) {
        // An error occurred
        this.recentList = null;
        return;
      }
      this.recentList = json.recentlist;
    });
  }

  loadUserRecentList(userid: string, versus: string, readyFunc: (json: any) => void) {
    // Load the list of recent games for the given user
    m.request({
      method: "POST",
      url: "/recentlist",
      body: { user: userid, versus: versus, count: 40 }
    })
    .then(readyFunc);
  }

  loadUserList(
    criteria: { query: string; spec: string; },
    activateSpinner: boolean
  ) {
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
    var data: { query?: string; spec?: string; kind?: string; } = criteria;
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
    .then((json: { result: number; userlist: any; rating: any; }) => {
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
    });
  }

  loadOwnStats() {
    // Load statistics for the current user
    this.ownStats = { };
    m.request({
      method: "POST",
      url: "/userstats",
      body: { } // Current user is implicit
    })
    .then((json: { result: number; }) => {
      if (!json || json.result !== 0) {
        // An error occurred
        this.ownStats = null;
        return;
      }
      this.ownStats = json;
    });
  }

  loadUserStats(userid: string, readyFunc: (json: any) => void) {
    // Load statistics for the given user
    m.request({
      method: "POST",
      url: "/userstats",
      body: { user: userid }
    })
    .then(readyFunc);
  }

  loadPromoContent(key: string, readyFunc: (html: string) => void) {
    // Load HTML content for promo dialog
    m.request({
      method: "POST",
      url: "/promo",
      body: { key: key },
      responseType: "text",
      deserialize: (str: string) => str
    })
    .then(readyFunc);
  }

  loadBestMoves(move: number) {
    // Load the best moves available at a given state in a game
    if (!this.game || !this.game.uuid)
      return;
    if (!move) {
      this.reviewMove = null;
      this.bestMoves = null;
      this.highlightedMove = null;
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
    .then((json: { result: number; move_number: number; best_moves: Move[]; player_rack: RackTile[]; }) => {
      this.highlightedMove = null;
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
    });
  }

  loadHelp() {
    // Load the help screen HTML from the server
    // (this is done the first time the help is displayed)
    if (this.helpHTML !== null)
      return; // Already loaded
    m.request({
      method: "GET",
      url: "/rawhelp",
      responseType: "text",
      deserialize: (str: string) => str
    })
    .then((result: string) => { this.helpHTML = result; });
  }

  loadUser(activateSpinner: boolean) {
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
    .then((result: { ok: boolean; userprefs: any; }) => {
      if (activateSpinner)
        this.spinners--;
      if (!result.ok) {
        // console.log("Unable to load user preferences");
        this.user = null;
        this.userErrors = null;
      }
      else {
        // console.log("User preferences loaded");
        this.user = result.userprefs;
        this.userErrors = null;
      }
    });
  }

  saveUser(successFunc: () => void) {
    // Update the preferences of the currently logged in user, if any
    m.request({
      method: "POST",
      url: "/saveuserprefs",
      body: this.user
    })
    .then((result: { ok: boolean; err?: UserErrors; }) => {
      if (result.ok) {
        // User preferences modified successfully on the server:
        // update the state variables that we're caching
        $state.userNick = this.user.nickname;
        $state.beginner = this.user.beginner;
        $state.fairPlay = this.user.fairplay;
        $state.newBag = this.user.newbag;
        // Give the game instance a chance to update its state
        if (this.game !== null)
          this.game.notifyUserChange(this.user.nickname);
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
    });
  }

  setUserPref(pref: object) {
    // Set a user preference
    return m.request(
      {
        method: "POST",
        url: "/setuserpref",
        body: pref
      }
    ).then(() => {}); // No result required or expected
  }

  newGame(oppid: string, reverse: boolean) {
    // Ask the server to initiate a new game against the given opponent
    m.request({
      method: "POST",
      url: "/initgame",
      body: { opp: oppid, rev: reverse }
    })
    .then((json: { ok: boolean; uuid: string; }) => {
      if (json.ok) {
        // Go to the newly created game
        m.route.set("/game/" + json.uuid);
      }
    });
  }

  modifyChallenge(parameters: object) {
    // Reject or retract a challenge
    m.request({
      method: "POST",
      url: "/challenge",
      body: parameters
    })
    .then((json: { result: number }) => {
      if (json.result === 0)
        this.loadChallengeList();
    });
  }

  markFavorite(userId: string, status: boolean) {
    // Mark or de-mark a user as a favorite
    m.request({
      method: "POST",
      url: "/favorite",
      body: { destuser: userId, action: status ? "add" : "delete" }
    })
    .then(() => {});
  }

  addChatMessage(game: string, from_userid: string, msg: string, ts: string): boolean {
    // Add a chat message to the game's chat message list
    if (this.game && this.game.uuid == game) {
      this.game.addChatMessage(from_userid, msg, ts);
      return true;
    }
    return false;
  }

  handleUserMessage(json: any) {
    // Handle an incoming Firebase user message
    this.challengeList = null; // Reload challenge list
    this.gameList = null; // Reload game list
    m.redraw();
  }

  handleMoveMessage(json: any) {
    // Handle an incoming Firebase move message
    if (this.game) {
      this.game.update(json);
      m.redraw();
    }
  }

  resetScale() {
    // Reset the board scale (zoom) to 100% and the scroll origin to (0, 0)
    this.boardScale = 1.0;
    var boardParent = document.getElementById("board-parent");
    var board = boardParent.children[0];
    if (board)
      board.setAttribute("style", "transform: scale(1.0)");
    if (boardParent)
      boardParent.scrollTo(0, 0);
  }

  updateScale() {

    // Update the board scale (zoom)

    function scrollIntoView(sq: string) {
      // Scroll a square above and to the left of the placed tile into view
      var offset = 3;
      var vec = toVector(sq);
      var row = Math.max(0, vec.row - offset);
      var col = Math.max(0, vec.col - offset);
      var c = coord(row, col);
      var el = document.getElementById("sq_" + c);
      var boardParent = document.getElementById("board-parent");
      var board = boardParent.children[0];
      // The following seems to be needed to ensure that
      // the transform and hence the size of the board has been 
      // updated in the browser, before calculating the client rects
      if (board)
        board.setAttribute("style", "transform: scale(1.5)");
      var elRect = el.getBoundingClientRect();
      var boardRect = boardParent.getBoundingClientRect();
      boardParent.scrollTo(
        {
          left: elRect.left - boardRect.left,
          top: elRect.top - boardRect.top,
          behavior: "smooth"
        }
      );
    }

    if (!this.game || $state.uiFullscreen || this.game.moveInProgress) {
      // No game or we're in full screen mode: always 100% scale
      // Also, as soon as a move is being processed by the server, we zoom out
      this.boardScale = 1.0; // Needs to be done before setTimeout() call
      setTimeout(this.resetScale);
      return;
    }
    var tp = this.game.tilesPlaced();
    var numTiles = tp.length;
    if (numTiles == 1 && this.boardScale == 1.0) {
      // Laying down first tile: zoom in & position
      this.boardScale = 1.5;
      setTimeout(() => scrollIntoView(tp[0]));
    }
    else
    if (numTiles == 0 && this.boardScale > 1.0) {
      // Removing only remaining tile: zoom out
      this.boardScale = 1.0; // Needs to be done before setTimeout() call
      setTimeout(this.resetScale);
    }
  }

} // class Model

type DialogFunc = (view: View, model: Model, actions: any, args: any) => void;

interface DialogViews {
  userprefs: DialogFunc;
  userinfo: DialogFunc;
  challenge: DialogFunc;
  promo: DialogFunc;
  spinner: DialogFunc;
}

interface Dialog {
  name: string;
  args: any;
}

class View {

  private dialogStack: Dialog[] = [];

  // Map of available dialogs
  private static dialogViews: DialogViews = {
    userprefs:
      (view, model, actions) => view.vwUserPrefs(model, actions),
    userinfo:
      (view, model, actions, args) => view.vwUserInfo(model, actions, args),
    challenge:
      (view, model, actions, args) => view.vwChallenge(model, actions, args),
    promo:
      (view, model, actions, args) => view.vwPromo(model, actions, args),
    spinner:
      (view) => view.vwSpinner(),
  };

  constructor() {

    // Start a blinker interval function
    window.setInterval(this.blinker, 500);

    // The view interface exposes only the vwApp view function.
    // Additionally, a view instance has a current dialog window stack.

  }

  appView(model: Model, actions: Actions) {
    // Select the view based on the current route
    // Display the appropriate content for the route,
    // also considering active dialogs
    var views: any[] = [];
    switch (model.routeName) {
      case "login":
        views.push(this.vwLogin());
        break;
      case "main":
        views.push(this.vwMain(model, actions));
        break;
      case "game":
        views.push(this.vwGame(model));
        break;
      case "review":
        views.push(this.vwReview(model, actions));
        break;
      case "help":
        // A route parameter of ?q=N goes directly to the FAQ number N
        // A route parameter of ?tab=N goes directly to tab N (0-based)
        views.push(
          this.vwHelp(model,
            parseInt(m.route.param("tab") || ""),
            parseInt(m.route.param("faq") || "")
          )
        );
        break;
      default:
        // console.log("Unknown route name: " + model.routeName);
        return m("div", "Þessi vefslóð er ekki rétt");
    }
    // Push any open dialogs
    for (let i = 0; i < this.dialogStack.length; i++) {
      let dialog = this.dialogStack[i];
      let v: DialogFunc = View.dialogViews[dialog.name];
      if (v === undefined)
        console.log("Unknown dialog name: " + dialog.name);
      else
        views.push(v(this, model, actions, dialog.args));
    }
    // Overlay a spinner, if active
    if (model.spinners > 0)
      views.push(this.vwSpinner());
    return views;
  }

  // Dialog support

  pushDialog(dialogName: string, dialogArgs?: any) {
    this.dialogStack.push({ name: dialogName, args: dialogArgs });
    m.redraw(); // Ensure that the dialog is shown
  }

  popDialog() {
    if (this.dialogStack.length > 0) {
      this.dialogStack.pop();
      m.redraw();
    }
  }

  popAllDialogs() {
    if (this.dialogStack.length > 0) {
      this.dialogStack = [];
      m.redraw();
    }
  }

  isDialogShown() {
    return this.dialogStack.length > 0;
  }

  startSpinner() {
    this.pushDialog("spinner");
  }

  stopSpinner() {
    this.popDialog();
  }

  notifyMediaChange(model: Model) {
    // The view is changing, between mobile and fullscreen
    // and/or between portrait and landscape: ensure that
    // we don't end up with a selected game tab that is not visible
    if (model.game) {
      if ($state.uiFullscreen || $state.uiLandscape) {
        // In this case, there is no board tab:
        // show the movelist
        model.game.setSelectedTab("movelist");
        this.scrollMovelistToBottom();
      }
      else {
        // Mobile: we default to the board tab
        model.game.setSelectedTab("board");
      }
    }
    // When switching between landscape and portrait,
    // close all current dialogs
    this.popAllDialogs();
  }

  notifyChatMessage() {
    // A fresh chat message has arrived
    m.redraw();
  }

  showUserInfo(userid: string, nick: string, fullname: string) {
    // Show a user info dialog
    this.pushDialog("userinfo", { userid: userid, nick: nick, fullname: fullname });
  }

  // Globally available controls

  vwInfo() {
    // Info icon, invoking the help screen
    return m(".info",
      { title: "Upplýsingar og hjálp" },
      m(m.route.Link,
        { href: "/help", class: "iconlink" },
        glyph("info-sign")
      )
    );
  }

  vwUserId() {
    // User identifier at top right, opens user preferences
    if ($state.userId == "")
      // Don't show the button if there is no logged-in user
      return "";
    return m(".userid",
      {
        title: "Upplýsingar um leikmann",
        onclick: (ev) => {
          // Overlay the userprefs dialog
          this.pushDialog("userprefs");
          ev.preventDefault();
        }
      },
      [ glyph("address-book"), nbsp(), $state.userNick ]
    );
  }

  vwNetskraflLogo() {
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

  TogglerReady: ComponentFunc<{model: Model}> = (initialVnode) => {
    // Toggle on left-hand side of main screen:
    // User ready and willing to accept challenges

    var model = initialVnode.attrs.model;

    function toggleFunc(state: boolean) {
      $state.ready = state;
      model.setUserPref({ ready: state });
    }

    return {
      view: () => {
        return vwToggler(
          "ready", $state.ready, 2, nbsp(), glyph("thumbs-up"), toggleFunc, true,
          "Tek við áskorunum!"
        );
      }
    };
  };

  TogglerReadyTimed: ComponentFunc<{ model: Model }> = (initialVnode) => {
    // Toggle on left-hand side of main screen:
    // User ready and willing to accept timed challenges

    var model = initialVnode.attrs.model;

    function toggleFunc(state: boolean) {
      $state.readyTimed = state;
      model.setUserPref({ ready_timed: state });
    }

    return {
      view: (vnode) => {
        return vwToggler(
          "timed", $state.readyTimed, 3, nbsp(), glyph("time"), toggleFunc, true,
          "Til í viðureign með klukku!"
        );
      }
    };
  };

  vwDialogButton(
    id: string, title: string, func: EventHandler,
    content: VnodeChildren, tabindex: number
  ) {
    // Create a .modal-close dialog button
    var attrs: VnodeAttrs = {
      id: id,
      onclick: func,
      title: title
    };
    if (tabindex !== undefined)
      attrs.tabindex = tabindex;
    return m(DialogButton, attrs, content);
  }

  blinker() {
    // Toggle the 'over' class on all elements having the 'blinking' class
    var blinkers = document.getElementsByClassName('blinking');
    for (let i = 0; i < blinkers.length; i++)
      blinkers[i].classList.toggle("over");
  }

  vwSpinner() {
    // Show a spinner wait box
    return m(
      ".modal-dialog",
      { id: 'spinner-dialog', style: { visibility: 'visible' } },
      m("div", { id: "user-load", style: { display: "block" } })
    );
  }

  // Login screen

  vwLogin() {
    // Login dialog

    let view = this;

    function vwLoginLarge() {
      // Full screen version of login page
      return [
        view.vwNetskraflLogo(),
        view.vwInfo(),
        m(".loginform-large",
        [
          m(".loginhdr", "Velkomin í Netskrafl!"),
          m(".blurb", "Skemmtilegt | skerpandi | ókeypis"),
          m("div", { id: "board-pic" },
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
              m("b", "yfir 20.000 íslenskra skraflara"),
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
                onclick: () => {
                  window.location.href = "/page";
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
            { id: "logo-pic" },
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
                onclick: () => {
                  window.location.href = "/page";
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

  vwTabsFromHtml(html: string, id: string, tabNumber: number, createFunc: (vnode: Vnode) => void) {
    // The function assumes that 'this' is the current view object
    if (!html)
      return "";
    return m("div",
      {
        oninit: (vnode) => { vnode.state.selected = tabNumber || 1; },
        oncreate: (vnode) => { this.makeTabs(id, createFunc, true, vnode); }
        /* onupdate: updateSelection */
      },
      m.trust(html)
    );
  }

  // Help screen

  vwHelp(model: Model, tabNumber: number, faqNumber: number) {

    function wireQuestions(vnode: Vnode) {
      // Clicking on a question brings the corresponding answer into view
      // This is achieved by wiring up all contained a[href="#faq-*"] links

      function showAnswer(ev: Event, href: string) {
        // this points to the vnode
        vnode.state.selected = 1; // FAQ tab
        vnode.dom.querySelector(href).scrollIntoView();
        ev.preventDefault();
      }

      let anchors = vnode.dom.querySelectorAll("a");
      for (let i = 0; i < anchors.length; i++) {
        let href = anchors[i].getAttribute("href");
        if (href.slice(0, 5) == "#faq-")
          // This is a direct link to a question: wire it up
          anchors[i].onclick = (ev) => { showAnswer(ev, href); };
      }
      if (faqNumber !== undefined && !isNaN(faqNumber)) {
        // Go to the FAQ tab and scroll the requested question into view
        selectTab(vnode, 1);
        vnode.state.selected = 1; // FAQ tab
        vnode.dom.querySelector("#faq-" + faqNumber.toString()).scrollIntoView();
      }
    }

    // Output literal HTML obtained from rawhelp.html on the server
    return [
      // vwNetskraflLogo(),
      m(LeftLogo),
      this.vwUserId(),
      m("main",
        this.vwTabsFromHtml(model.helpHTML, "tabs", tabNumber, wireQuestions)
      )
    ];
  }

  // User preferences screen

  vwUserPrefsDialog(model: Model) {

    var user = model.user;
    var err = model.userErrors || { };
    var view = this;

    function vwErrMsg(propname: string) {
      // Show a validation error message returned from the server
      return err.hasOwnProperty(propname) ?
        m(".errinput", [ glyph("arrow-up"), nbsp(), err[propname] ]) : "";
    }

    function playAudio(elemId: string) {
      // Play an audio file
      const sound = document.getElementById(elemId) as HTMLMediaElement;
      if (sound)
        sound.play();
    }

    function getToggle(elemId: string) {
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
      model.saveUser(() => { view.popDialog(); });
    }

    function initFocus(vnode: Vnode) {
      // Set the focus on the nickname field when the dialog is displayed
      (vnode.dom.querySelector("#nickname") as HTMLElement).focus();
    }

    return m(".modal-dialog",
      {
        id: "user-dialog",
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
                      function(state) { if (state) playAudio("your-turn"); }),
                    m("span.subcaption", "Lúðraþytur eftir sigur:"),
                    vwToggler("fanfare", user.fanfare, 5,
                      glyph("volume-off"), glyph("volume-up"),
                      function(state) { if (state) playAudio("you-win"); })
                  ]
                ),
                m(".explain", 
                  "Stillir hvort hljóðmerki heyrast t.d. þegar andstæðingur " +
                  "leikur og þegar sigur vinnst"
                ),
                m(".dialog-spacer",
                  [
                    m("span.caption", "Sýna reitagildi:"),
                    vwToggler("beginner", user.beginner, 6,
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
          this.vwDialogButton("user-ok", "Vista", validate, glyph("ok"), 9),
          this.vwDialogButton("user-cancel", "Hætta við",
            (ev) => { this.popDialog(); ev.preventDefault(); },
            glyph("remove"), 10),
          this.vwDialogButton("user-logout", "Skrá mig út",
            (ev) => {
              window.location.href = user.logout_url;
              ev.preventDefault();
            },
            [ glyph("log-out"), nbsp(), "Skrá mig út" ], 11),
          user.friend ?
            this.vwDialogButton("user-unfriend", "Hætta sem vinur",
              (ev) => {
                window.location.href = user.unfriend_url;
                ev.preventDefault();
              },
              [ glyph("coffee-cup"), nbsp(), nbsp(), "Þú ert vinur Netskrafls!" ], 12
            )
          :
            this.vwDialogButton("user-friend", "Gerast vinur",
              (ev) => {
                // Invoke the friend promo dialog
                view.pushDialog("promo", { kind: "friend", initFunc: registerSalesCloud });
                ev.preventDefault();
              },
              [ glyph("coffee-cup"), nbsp(), nbsp(), "Gerast vinur Netskrafls" ], 12
            )
        ]
      )
    );
  }

  vwUserPrefs(model: Model, actions) {
    if (model.user === null)
      model.loadUser(true); // Activate spinner while loading
    if (!model.user)
      // Nothing to edit (the spinner should be showing in this case)
      return "";
    return this.vwUserPrefsDialog(model);
  }

  vwUserInfo(model: Model, actions, args: { userid: string; nick: string; fullname: string; }) {
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

  vwPromo(model: Model, actions, args: { kind: string; initFunc: () => void; }) {
    return m(PromoDialog,
      {
        model: model,
        view: this,
        kind: args.kind,
        initFunc: args.initFunc
      }
    );
  }

  vwChallenge(model: Model, actions, item) {
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
                  "Nota ", m("strong", "handvirka véfengingu"),
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
              onclick: (ev) => {
                this.popDialog();
                ev.preventDefault();
              }
            },
            glyph("remove")
          ),
          m(DialogButton,
            {
              id: "chall-ok",
              title: "Skora á",
              tabindex: 9,
              onclick: (ev) => {
                // Issue a new challenge
                var duration: string|number = document.querySelector("div.chall-time.selected").id.slice(6);
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
              }
            },
            glyph("ok")
          )
        ]
      )
    );
  }

  // Main screen

  vwMain(model: Model, actions) {
    // Main screen with tabs

    var view = this;

    function vwMainTabs() {

      function vwMainTabHeader() {
        var numGames = 0;
        var numChallenges = 0;
        if (model.gameList)
          // Sum up games where it's the player's turn, as well as zombie games
          numGames = model.gameList.reduce((acc: number, item) => {
            return acc + (item.my_turn || item.zombie ? 1 : 0);
          }, 0);
        if (model.challengeList)
          // Sum up received challenges
          numChallenges = model.challengeList.reduce((acc: number, item) => {
            return acc + (item.received ? 1 : 0);
          }, 0);
        return m("ul",
          [
            m("li", 
              m("a[href='#tabs-1']",
                [
                  glyph("th"), m("span.tab-legend", "Viðureignir"),
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
                  glyph("hand-right"), m("span.tab-legend", "Áskoranir"),
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

      function showUserInfo(userid: string, nick: string, fullname: string) {
        view.pushDialog("userinfo", { userid: userid, nick: nick, fullname: fullname });
      }

      function vwGamelist() {

        function vwList() {

          function viewGameList() {

            if (!model.gameList)
              return "";
            return model.gameList.map((item, i: number) => {

              // Show a list item about a game in progress (or recently finished)

              function vwOpp() {
                var arg = item.oppid === null ? [ glyph("cog"), nbsp(), item.opp ] : item.opp;
                return m("span.list-opp", { title: item.fullname }, arg);
              }

              function vwTurn() {
                var turnText: string;
                var flagClass: string;
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
                          onclick: () => {
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

      function vwChallenges(showReceived: boolean) {

        function vwList() {

          function itemize(item, i: number) {

            // Generate a list item about a pending challenge (issued or received)

            function challengeDescription(json: { duration?: number; }) {
               /* Return a human-readable string describing a challenge
                  according to the enclosed preferences */
               if (!json || json.duration === undefined || json.duration === 0)
                  /* Normal unbounded (untimed) game */
                  return "Venjuleg ótímabundin viðureign";
               return "Með klukku, 2 x " + json.duration.toString() + " mínútur";
            }

            function markChallenge(ev: Event) {
              // Clicked the icon at the beginning of the line,
              // to decline a received challenge or retract an issued challenge
              var action = item.received ? "decline" : "retract";
              model.modifyChallenge({ destuser: item.userid, action: action });
              ev.preventDefault();
            }

            function clickReceived(ev: Event) {
              // Clicked the hotspot area to accept a received challenge
              if (item.received)
                // Ask the server to create a new game and route to it
                model.newGame(item.userid, false);
              ev.preventDefault();
            }

            // var oppReady = !item.received && item.opp_ready;
            let descr = challengeDescription(item.prefs);

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
                    onclick: (ev) => { showUserInfo(item.userid, item.opp, item.fullname); }
                  },
                  m("span.usr-info", "")
                ),
                m("span.list-newbag", glyph("shopping-bag", { title: "Gamli pokinn" }, item.prefs.newbag)
                )
              ]
            );
          }

          let cList: any[];
          if (!model.challengeList)
            cList = [];
          else
            cList = showReceived ?
              model.challengeList.filter((item) => item.received) :
              model.challengeList.filter((item) => !item.received);

          return m("div",
            {
              id: showReceived ? 'chall-received' : 'chall-sent',
              oninit: () => {
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
                  "Elo",
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

      function vwUserButton(id: string, icon: string, text: string) {
        // Select the type of user list (robots, fav, alike, elo)
        var sel = model.userListCriteria ? model.userListCriteria.query : "robots";
        var spec = (id == "elo") ? "human" : "";
        return m("span",
          {
            className: (id == sel ? "shown" : ""),
            id: id,
            onclick: (ev) => {
              model.loadUserList({ query: id, spec: spec }, true);
              ev.preventDefault();
            }
          },
          [ glyph(icon, { style: { padding: 0 } }), nbsp(), text ]
        );
      }

      function vwUserList() {

        function vwUserList(listType, list) {

          function itemize(item, i: number) {

            // Generate a list item about a user

            var isRobot = item.userid.indexOf("robot-") === 0;
            var fullname = [];

            // Online and accepting challenges
            if (item.ready && !isRobot) {
              fullname.push(m("span.ready-btn", { title: "Álínis og tekur við áskorunum" }));
              fullname.push(nbsp());
            }
            // Willing to accept challenges for timed games
            if (item.ready_timed) {
              fullname.push(m("span.timed-btn", { title: "Til í viðureign með klukku" }));
              fullname.push(nbsp());
            }
            // Fair play commitment
            if (item.fairplay) {
              fullname.push(m("span.fairplay-btn", { title: "Skraflar án hjálpartækja" }));
              fullname.push(nbsp());
            }
            fullname.push(item.fullname);

            function fav() {
              if (isRobot)
                return m("span.list-fav", { style: { cursor: "default" } }, glyph("star-empty"));
              return m("span.list-fav",
                {
                  title: "Uppáhald",
                  onclick: (ev) => {
                    item.fav = !item.fav;
                    model.markFavorite(item.userid, item.fav);
                    ev.preventDefault();
                  }
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
                    onclick: (ev) => { model.newGame(item.userid, false); ev.preventDefault(); }
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
                    onclick: (ev) => {
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
                    onclick: (ev) => {
                      showUserInfo(item.userid, item.nick, item.fullname);
                      ev.preventDefault();
                    }
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

        let listType = model.userListCriteria ? model.userListCriteria.query : "robots";
        if (listType == "elo")
          // Show Elo list
          return m(EloPage, { id: "elolist", model: model, view: view });
        // Show normal user list
        let list: any[] = [];
        if (model.userList === undefined) {
          // We are loading a fresh user list
          /* pass */
        }
        else
        if (model.userList === null || model.userListCriteria.query != listType)
          model.loadUserList({ query: listType, spec: "" }, true);
        else
          list = model.userList;
        let nothingFound = list.length === 0 && model.userListCriteria !== undefined &&
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
                [
                  glyph("search"),
                  " ",
                  m("span", { id: "search-prefix" }, model.userListCriteria.spec),
                  " finnst ekki"
                ]
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
      m(LeftLogo), // No legend, scale up by 50%
      this.vwUserId(),
      this.vwInfo(),
      m(this.TogglerReady, { model: model }),
      m(this.TogglerReadyTimed, { model: model }),
      m("main",
        m("div",
          {
            oncreate: (vnode) => { this.makeTabs("main-tabs", undefined, false, vnode); },
            onupdate: updateSelection
          },
          vwMainTabs()
        )
      )
    ];
  }

  vwPlayerName(game: Game, side: string) {
    // Displays a player name, handling both human and robot players
    // as well as left and right side, and local and remote colors
    let view = this;
    var apl0 = game && game.autoplayer[0];
    var apl1 = game && game.autoplayer[1];
    var nick0 = game ? game.nickname[0] : "";
    var nick1 = game ? game.nickname[1] : "";
    var player: number = game ? game.player : 0;
    var localturn: boolean = game ? game.localturn : false;
    var tomove: string;
    var gameover = game ? game.over : true;

    function lookAtPlayer(ev: Event, player: number, side: number) {
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
      tomove = gameover || (localturn !== (player === 0)) ? "" : ".tomove";
      return m((player === 0 || player === 1) ? ".player-btn.left" + tomove : ".robot-btn.left",
        { id: "player-0", onclick: (ev) => lookAtPlayer(ev, player, 0) },
        [ m("span.left-to-move"), nick0 ]
      );
    }
    else {
      // Right side player
      if (apl1)
        // Player 1 is a robot (autoplayer)
        return m(".robot-btn.right", [ glyph("cog"), nbsp(), nick1 ]);
      tomove = gameover || (localturn !== (player === 1)) ? "" : ".tomove";
      return m((player === 0 || player === 1) ? ".player-btn.right" + tomove : ".robot-btn.right",
        { id: "player-1", onclick: (ev) => lookAtPlayer(ev, player, 1) },
        [ m("span.right-to-move"), nick1 ]
      );
    }
  }

  vwTwoLetter: ComponentFunc<{ game: Game; }> = (initialVnode) => {

    // The two-letter-word list tab
    let page = 0;
    let game = initialVnode.attrs.game;
    let twoLetters = game.twoLetterWords();

    function renderWord(bold: boolean, w: string) {
      // For the first two-letter word in each group,
      // render the former letter in bold
      if (!bold)
        return m(".twoletter-word", w);
      if (page == 0)
        return m(".twoletter-word", [ m("b", w[0]), w[1] ]);
      else
        return m(".twoletter-word", [ w[0], m("b", w[1]) ]);
    }

    return {
      view: (vnode) => {
        let twoLetterWords = twoLetters[page];
        let twoLetterList = [];
        for (let i = 0; i < twoLetterWords.length; i++) {
          let twl = twoLetterWords[i][1];
          let sublist = [];
          for (let j = 0; j < twl.length; j++)
            sublist.push(renderWord(j == 0, twl[j]));
          twoLetterList.push(
            m(".twoletter-group", sublist)
          );
        }
        return m(".twoletter",
          {
            // Switch between pages when clicked
            onclick: () => { page = 1 - page; },
            style: "z-index: 6" // Appear on top of board on mobile
          },
          // Show the requested page
          m(".twoletter-area" + (game.isTimed() ? ".with-clock" : ""),
            {
              title: page == 0 ?
                "Smelltu til að raða eftir seinni staf" :
                "Smelltu til að raða eftir fyrri staf"
            },
            twoLetterList
          )
        );
      }
    };
  };

  buttonState(game: Game) {
    // Calculate a set of booleans describing the state of the game
    let s: any = {};
    s.tilesPlaced = game.tilesPlaced().length > 0;
    s.gameOver = game.over;
    s.congratulate = game.congratulate;
    s.localTurn = game.localturn;
    s.gameIsManual = game.manual;
    s.challengeAllowed = game.chall;
    s.lastChallenge = game.last_chall;
    s.showingDialog = game.showingDialog !== null;
    s.exchangeAllowed = game.xchg;
    s.wordGood = game.wordGood;
    s.wordBad = game.wordBad;
    s.canPlay = false;
    s.tardyOpponent = !s.localTurn && !s.gameOver && game.overdue;
    s.showResign = false;
    s.showExchange = false;
    s.showPass = false;
    s.showRecall = false;
    s.showScramble = false;
    s.showMove = false;
    s.showChallenge = false;
    s.showChallengeInfo = false;
    if (s.localTurn && !s.gameOver) {
      // This player's turn
      if (s.lastChallenge) {
        s.showChallenge = true;
        s.showPass = true;
        s.showChallengeInfo = true;
      }
      else {
        s.showMove = s.tilesPlaced;
        s.showExchange = !s.tilesPlaced;
        s.showPass = !s.tilesPlaced;
        s.showResign = !s.tilesPlaced;
        s.showChallenge = !s.tilesPlaced && s.gameIsManual && s.challengeAllowed;
      }
    }
    if (s.showMove && (s.wordGood || s.gameIsManual))
      s.canPlay = true;
    if (!s.gameOver)
      if (s.tilesPlaced)
        s.showRecall = true;
      else
        s.showScramble = true;
    return s;
  }

  // Game screen

  vwGame(model: Model) {
    // A view of a game, in-progress or finished

    var game = model.game;
    var view = this;

    function vwBeginner() {
      // Show the board color guide
      return m(".board-help",
        { title: 'Hvernig reitirnir margfalda stigin' },
        [
          m(".board-help-close[title='Loka þessari hjálp']",
            {
              onclick: (ev) => {
                // Close the guide and set a preference not to see it again
                $state.beginner = false;
                model.setUserPref({ beginner: false });
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

    function vwRightColumn() {
      // A container for the right-side header and area components

      function vwClock() {
        // Show clock data if this is a timed game
        if (!game.isTimed())
          // Not a timed game
          return m.fragment({}, []);

        function vwClockFace(cls: string, txt: string, runningOut: boolean, blinking: boolean) {
          return m("h3." + cls
            + (runningOut ? ".running-out" : "")
            + (blinking ? ".blink" : ""),
            txt
          );
        }

        return m.fragment({}, [
          vwClockFace("clockleft", game.clockText0, game.runningOut0, game.blinking0),
          vwClockFace("clockright", game.clockText1, game.runningOut1, game.blinking1),
          m(".clockface", glyph("time"))
        ]);
      }

      function vwRightHeading() {
        // The right-side heading on the game screen

        var fairplay = game ? game.fairplay : false;
        var player = game ? game.player : 0;
        var sc0 = game ? game.displayScore(0).toString() : "";
        var sc1 = game ? game.displayScore(1).toString() : "";
        return m(".heading",
          [
            m(".leftplayer" + (player == 1 ? ".autoplayercolor" : ".humancolor"), [
              m(".player", view.vwPlayerName(game, "left")),
              m(".scorewrapper", m(".scoreleft", sc0)),
            ]),
            m(".rightplayer" + (player == 1 ? ".humancolor" : ".autoplayercolor"), [
              m(".player", view.vwPlayerName(game, "right")),
              m(".scorewrapper", m(".scoreright", sc1)),
            ]),
            vwClock(),
            m(".fairplay",
              { style: { visibility: fairplay ? "visible" : "hidden" } },
              m("span.fairplay-btn.large", { title: "Skraflað án hjálpartækja" } ))
            // m(".home", m(".circle", glyph("home", { title: "Aftur í aðalskjá" })))
          ]
        );
      }

      function vwRightArea() {
        // A container for the tabbed right-side area components
        var sel = (game && game.sel) ? game.sel : "movelist";
        // Show the chat tab unless the opponent is an autoplayer
        var component = null;
        switch (sel) {
          case "movelist":
            component = view.vwMovelist(game);
            break;
          case "twoletter":
            component = m(view.vwTwoLetter, { game: game } );
            break;
          case "chat":
            component = view.vwChat(game);
            break;
          case "games":
            component = view.vwGames(model);
            break;
          default:
            break;
        }
        var tabgrp = view.vwTabGroup(game);
        return m(".right-area" + (game.isTimed() ? ".with-clock" : ""),
          component ? [ tabgrp, component ] : [ tabgrp ]
        );
      }

      function vwRightMessage() {
        // Display a status message in the mobile UI
        var s = view.buttonState(game);
        var msg: string | any[] = "";
        var player = game.player;
        var opp = game.nickname[1 - player];
        var move = game.moves.length ? game.moves[game.moves.length - 1] : undefined;
        var mtype = move ? move[1][1] : undefined;
        if (s.congratulate) {
          // This player won
          if (mtype == "RSGN")
            msg = [m("strong", [opp, " resigned!"]), " Congratulations."];
          else
            msg = [m("strong", ["You beat ", opp, "!"]), " Congratulations."];
        }
        else
        if (s.gameOver) {
          // This player lost
          msg = "Game over!";
        }
        else
        if (!s.localTurn) {
          // It's the opponent's turn
          msg = ["It's ", opp, "'s turn. Plan your next move!"];
        }
        else
        if (s.tilesPlaced > 0) {
          if (game.currentScore === undefined) {
            if (move === undefined)
              msg = ["Your first move must cover the ", glyph("star"), " asterisk."];
            else
              msg = "Tiles must be consecutive.";
          }
          else
          if (game.wordGood === false) {
            msg = ["Move is not valid, but would score ", m("strong", game.currentScore.toString()), " points."];
          }
          else {
            msg = ["Valid move, score ", m("strong", game.currentScore.toString()), " points."];
          }
        }
        else
        if (move === undefined) {
          // Initial move
          msg = [m("strong", "You start!"), " Cover the ", glyph("star"), " asterisk with your move."];
        }
        else {
          var co = move[1][0];
          var tiles = mtype;
          var score = move[1][2];
          if (co == "") {
            // Not a regular tile move
            if (tiles == "PASS")
              msg = [opp, " passed."];
            else
            if (tiles.indexOf("EXCH") === 0) {
              var numtiles = tiles.slice(5).length;
              msg = [
                opp, " exchanged ",
                numtiles.toString(),
                (numtiles == 1 ? " tile" : " tiles"),
                "."
              ];
            }
            else
            if (tiles == "CHALL")
              msg = [opp, " challenged your move."];
            else
            if (tiles == "RESP") {
              if (score < 0)
                msg = [opp, " successfully challenged your move."];
              else
                msg = [opp, " unsuccessfully challenged your move and lost 10 points."];
            }
          }
          else {
            // Regular tile move
            tiles = tiles.split("?").join(""); /* TBD: Display wildcard characters differently? */
            msg = [opp, " played ", m("strong", tiles),
              " for ", m("strong", score.toString()), " points"];
          }
        }
        return m(".message", msg);
      }

      return m(".rightcol", [ vwRightHeading(), vwRightArea(), vwRightMessage() ]);
    }

    if (game === undefined || game === null)
      // No associated game
      return m("div", [ m("main", m(".game-container")), m(this.BackButton) ]);

    let bag = game ? game.bag : "";
    let newbag = game ? game.newbag : true;
    return m("div", // Removing this div messes up Mithril
      {
        // Allow tiles to be dropped on the background,
        // thereby transferring them back to the rack
        ondragenter: (ev) => {
          ev.preventDefault();
          ev.dataTransfer.dropEffect = 'move';
          ev.redraw = false;
          return false;
        },
        ondragover: (ev) => {
          // This is necessary to allow a drop
          ev.preventDefault();
          ev.redraw = false;
          return false;
        },
        ondrop: (ev) => {
          ev.stopPropagation();
          // Move the tile from the board back to the rack
          var from = ev.dataTransfer.getData("text");
          // Move to the first available slot in the rack
          game.attemptMove(from, "R1");
          model.updateScale();
          return false;
        }
      },
      [
        // The main game area
        m("main",
          m(".game-container",
            [
              m(this.MobileHeader),
              vwRightColumn(),
              m(this.BoardArea, { model: model }),
              $state.uiFullscreen ? m(this.Bag, { bag: bag, newbag: newbag }) : "", // Visible in fullscreen
              game.askingForBlank ? m(this.BlankDialog, { game: game }) : ""
            ]
          )
        ),
        // The left margin stuff: back button, square color help, info/help button
        m(this.BackButton),
        $state.beginner ? vwBeginner() : "",
        this.vwInfo()
      ]
    );
  }

  MobileHeader() {
    // The header on a mobile screen
    return {
      view: () => {
        return m(".header", [
            m(".header-logo",
              m(m.route.Link,
                {
                  href: "/page",
                  class: "backlink"
                },
                m(ExploLogo, { legend: true, scale: 1.0 })
              )
            ),
            m(".header-button")
          ]
        );
      }
    };
  }

  // Review screen

  vwReview(model: Model, actions: Actions) {
    // A review of a finished game

    let view = this;
    let game = model.game;
    let move = model.reviewMove;
    let bestMoves = model.bestMoves || [];

    function vwRightColumn() {
      // A container for the right-side header and area components

      function vwRightHeading() {
        // The right-side heading on the game screen

        let fairplay = game.fairplay;
        let player = game.player;
        let sc0 = "";
        let sc1 = "";
        if (move) {
          let s0 = 0;
          let s1 = 0;
          for (let i = 0; i < move; i++) {
            // Add up the scores until and including this move
            let m = game.moves[i];
            if (i % 2 == 0)
              s0 += m[1][2];
            else
              s1 += m[1][2];
          }
          sc0 = s0.toString();
          sc1 = s1.toString();
        }
        return m(".heading",
          {
            // On mobile only: If the header is clicked, go to the main screen
            onclick: (ev) => {
              if (!$state.uiFullscreen) m.route.set("/main");
            }
          },
          [
            m(".leftplayer", [
              m(".player" + (player == 1 ? ".autoplayercolor" : ".humancolor"),
                view.vwPlayerName(game, "left")),
              m(".scoreleft", sc0),
            ]),
            m(".rightplayer", [
              m(".player" + (player == 1 ? ".humancolor" : ".autoplayercolor"),
                view.vwPlayerName(game, "right")),
              m(".scoreright", sc1),
            ]),
            m(".fairplay",
              { style: { visibility: fairplay ? "visible" : "hidden" } },
              m("span.fairplay-btn.large", { title: "Skraflað án hjálpartækja" } ))
          ]
        );
      }

      function vwRightArea() {
        // A container for the list of best possible moves
        return m(".right-area", view.vwBestMoves(model, move, bestMoves));
      }

      return m(".rightcol", [ vwRightHeading(), vwRightArea() ]);
    }

    if (game === undefined || game === null)
      // No associated game
      return m("div", [ m("main", m(".game-container")), m(this.BackButton) ]);

    // Create a list of major elements that we're showing
    let r = [];
    r.push(vwRightColumn());
    r.push(m(this.BoardReview, { model: model, move: move }));
    if (move === null)
      // Only show the stats overlay if move is null.
      // This means we don't show the overlay if move is 0.
      r.push(this.vwStatsReview(game));
    return m("div", // Removing this div messes up Mithril
      [
        m("main", m(".game-container", r)),
        m(this.BackButton), // Button to go back to main screen
        this.vwInfo() // Help button
      ]
    );
  }

  vwTabGroup(game: Game) {
    // A group of clickable tabs for the right-side area content
    var showchat = game ? !(game.autoplayer[0] || game.autoplayer[1]) : false;
    var r = [
      this.vwTab(game, "board", "Borðið", "grid"),
      this.vwTab(game, "movelist", "Leikir", "show-lines"),
      this.vwTab(game, "twoletter", "Tveggja stafa orð", "life-preserver"),
      this.vwTab(game, "games", "Viðureignir", "flag")
    ];
    if (showchat)
      // Add chat tab
      r.push(this.vwTab(game, "chat", "Spjall", "conversation",
        () => {
          // The tab has been clicked
          if (game.markChatShown())
            m.redraw();
        },
        !game.chatShown) // Show chat icon in red if chat messages are unseen
      );
    return m.fragment({}, r);
  }

  vwTab(game: Game, tabid: string, title: string, icon: string, func?: Function, alert?: boolean) {
    // A clickable tab for the right-side area content
    var sel = (game && game.sel) ? game.sel : "movelist";
    return m(".right-tab" + (sel == tabid ? ".selected" : ""),
      {
        id: "tab-" + tabid,
        className: alert ? "alert" : "",
        title: title,
        onclick: () => {
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

  vwChat(game: Game) {
    // The chat tab

    function decodeTimestamp(ts: string) {
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

    function dateFromTimestamp(ts: string) {
       // Create a JavaScript millisecond-based representation of an ISO timestamp
       var dcTs = decodeTimestamp(ts);
       return Date.UTC(dcTs.year, dcTs.month - 1, dcTs.day,
          dcTs.hour, dcTs.minute, dcTs.second);
    }

    function timeDiff(dtFrom: number, dtTo: number) {
       // Return the difference between two JavaScript time points, in seconds
       return Math.round((dtTo - dtFrom) / 1000.0);
    }

    let dtLastMsg: number = null;

    function makeTimestamp(ts: string) {
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
        var strTs: string;
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
        for (let i = 0; i < mlist.length; i++) {
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
            // { key: i },
            m.trust(escMsg))
          );
        }
      }
      return r;
    }

    function scrollChatToBottom() {
      // Scroll the last chat message into view
      var chatlist = document.querySelectorAll("#chat-area .chat-msg");
      var target: HTMLElement;
      if (chatlist.length) {
        target = chatlist[chatlist.length - 1] as HTMLElement;
        (target.parentNode as HTMLElement).scrollTop = target.offsetTop;
      }
    }

    function focus(vnode: Vnode) {
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

    if (game && game.messages === null)
      // No messages loaded yet: kick off async message loading
      // for the current game
      game.loadMessages();
    else
      game.markChatShown();

    return m(".chat",
      {
        style: "z-index: 6" // Appear on top of board on mobile
        // key: uuid
      },
      [
        m(".chat-area" + (game.isTimed() ? ".with-clock" : ""),
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
                onkeypress: (ev) => { if (ev.key == "Enter") sendMessage(); }
              }
            ),
            m(DialogButton,
              {
                id: "chat-send",
                title: "Senda",
                onclick: (ev) => { sendMessage(); }
              },
              glyph("chat")
            )
          ]
        )
      ]
    );
  }

  vwMovelist(game: Game) {
    // The move list tab

    let view = this;

    function movelist() {
      var mlist = game ? game.moves : []; // All moves made so far in the game
      var r = [];
      var leftTotal = 0;
      var rightTotal = 0;
      for (let i = 0; i < mlist.length; i++) {
        var move = mlist[i];
        var player = move[0];
        var co = move[1][0];
        var tiles = move[1][1];
        var score = move[1][2];
        if (player === 0)
          leftTotal = Math.max(leftTotal + score, 0);
        else
          rightTotal = Math.max(rightTotal + score, 0);
        r.push(
          view.vwMove(game, move,
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
            onupdate: this.scrollMovelistToBottom
          },
          movelist()
        ),
        !$state.uiFullscreen ? m(this.Bag, { bag: bag, newbag: newbag }) : "" // Visible on mobile
      ]
    );
  }

  vwBestMoves(model: Model, move: number, bestMoves: Move[]) {
    // List of best moves, in a game review

    let view = this;
    var game = model.game;

    function bestHeader(co: string, tiles, score: number) {
      // Generate the header of the best move list
      var wrdclass = "wordmove";
      var dispText: string | any[];
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
      let r = [];
      // Use a 1-based index into the move list
      // (We show the review summary if move==0)
      if (!move || move > game.moves.length)
        return r;
      // Prepend a header that describes the move being reviewed
      let m = game.moves[move - 1];
      let co = m[1][0];
      let tiles = m[1][1];
      let score = m[1][2];
      r.push(bestHeader(co, tiles, score));
      let mlist = bestMoves;
      for (let i = 0; i < mlist.length; i++) {
        let player = mlist[i][0];
        co = mlist[i][1][0];
        tiles = mlist[i][1][1];
        score = mlist[i][1][2];
        r.push(
          view.vwBestMove(model, move, i, mlist[i],
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

  scrollMovelistToBottom() {
    // If the length of the move list has changed,
    // scroll the last move into view
    let movelist = document.querySelectorAll("div.movelist .move");
    if (!movelist || !movelist.length)
      return;
    let target = movelist[movelist.length - 1] as HTMLElement;
    let parent = target.parentNode as HTMLElement;
    let len = parent.getAttribute("data-len");
    let intLen = (!len) ? 0 : parseInt(len);
    if (movelist.length > intLen) {
      // The list has grown since we last updated it:
      // scroll to the bottom and mark its length
      parent.scrollTop = target.offsetTop;
    }
    parent.setAttribute("data-len", movelist.length.toString());
  }

  vwMove(game: Game, move, info) {
    // Displays a single move

    let view = this;

    function highlightMove(co: string, tiles: string, playerColor: 0 | 1, show: boolean) {
       /* Highlight a move's tiles when hovering over it in the move list */
       let vec = toVector(co);
       let col = vec.col;
       let row = vec.row;
       for (let i = 0; i < tiles.length; i++) {
          let tile = tiles[i];
          if (tile == '?')
             continue;
          let sq = coord(row, col);
          if (game.tiles.hasOwnProperty(sq))
            game.tiles[sq].highlight = show ? playerColor : undefined;
          col += vec.dx;
          row += vec.dy;
       }
    }

    let player = info.player;
    let co: string = info.co;
    let tiles: string = info.tiles;
    let score = info.score;
    let leftTotal = info.leftTotal;
    let rightTotal = info.rightTotal;

    function gameOverMove(tiles: string) {
      // Add a 'game over' div at the bottom of the move list
      // of a completed game. The div includes a button to
      // open a review of the game, if the user is a friend of Explo.
      return m(".move.gameover",
        [
          m("span.gameovermsg", tiles),
          m("span.statsbutton",
            {
              onclick: (ev) => {
                if (true || $state.hasPaid) // !!! FIXME
                  // Show the game review
                  m.route.set("/review/" + game.uuid);
                else
                  // Show a friend promotion dialog
                  view.pushDialog("promo", { kind: "friend", initFunc: registerSalesCloud });
                ev.preventDefault();
              }
            },
            "Skoða yfirlit"
          )
        ]
      );
    }

    // Add a single move to the move list
    let wrdclass = "wordmove";
    let rawCoord = co;
    let tileMoveIncrement = 0; // +1 for tile moves, -1 for successful challenges
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
        let numtiles = tiles.slice(5).length;
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
      tiles = tiles.split("?").join(""); /* TBD: Display wildcard characters differently? */
      tileMoveIncrement = 1;
    }
    if (wrdclass == "gameover")
      // Game over message at bottom of move list
      return gameOverMove(tiles);
    // Normal game move
    let title = (tileMoveIncrement > 0 && !game.manual) ? "Smelltu til að fletta upp" : "";
    let playerColor: 0 | 1 = 0;
    let lcp = game.player;
    let cls: string;
    if (player === lcp || (lcp == -1 && player === 0)) // !!! FIXME: Check -1 case
      cls = "humangrad" + (player === 0 ? "_left" : "_right"); /* Local player */
    else {
      cls = "autoplayergrad" + (player === 0 ? "_left" : "_right"); /* Remote player */
      playerColor = 1;
    }
    let attribs: VnodeAttrs = { title: title };
    if ($state.uiFullscreen && tileMoveIncrement > 0) {
      if (!game.manual)
        // Tile move and not a manual game: allow word lookup
        attribs.onclick = () => { window.open('https://malid.is/leit/' + tiles, 'malid'); };
      // Highlight the move on the board while hovering over it
      attribs.onmouseout = () => {
        move.highlighted = false;
        highlightMove(rawCoord, tiles, playerColor, false);
      };
      attribs.onmouseover = () => {
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

  vwBestMove(model: Model, moveIndex: number, bestMoveIndex: number, move, info) {
    // Displays a move in a list of best available moves

    let game = model.game;
    let player = info.player;
    let co = info.co;
    let tiles = info.tiles;
    let score = info.score;

    function highlightMove(co: string, tiles: string, playerColor: 0 | 1, show: boolean) {
      /* Highlight a move's tiles when hovering over it in the best move list */
      let vec = toVector(co);
      let col = vec.col;
      let row = vec.row;
      let nextBlank = false;
      // If we're highlighting a move, show all moves leading up to it on the board
      if (show) {
        model.highlightedMove = bestMoveIndex;
        game.placeTiles(moveIndex - 1, true); // No highlight
      }
      for (let i = 0; i < tiles.length; i++) {
        let tile = tiles[i];
        if (tile == "?") {
          nextBlank = true;
          continue;
        }
        let sq = coord(row, col);
        let letter = tile;
        if (nextBlank)
          tile = '?';
        let tscore = game.tilescore(tile);
        if (show) {
          if (!(sq in game.tiles)) {
            // Showing a tile that was not already on the board
            game.tiles[sq] = {
              player: player,
              tile: tile,
              letter: letter,
              score: tscore,
              draggable: false,
              freshtile: false,
              index: 0,
              xchg: false,
              review: true, // Mark as a 'review tile'
              highlight: playerColor
            };
          }
          else {
            // Highlighting a tile that was already on the board
            game.tiles[sq].highlight = playerColor;
          }
        }
        col += vec.dx;
        row += vec.dy;
        nextBlank = false;
      }
      if (!show) {
        model.highlightedMove = null;
        game.placeTiles(model.reviewMove);
      }
    }

    // Add a single move to the move list
    let rawCoord = co;
    // Normal tile move
    co = "(" + co + ")";
    // Note: String.replace() will not work here since there may be two question marks in the string
    let word = tiles.split("?").join(""); /* TBD: Display wildcard characters differently? */
    // Normal game move
    let title = "Smelltu til að fletta upp";
    let playerColor: 0 | 1 = 0;
    let lcp = game.player;
    let cls: string;
    if (player === lcp || (lcp == -1 && player === 0)) // !!! FIXME: Check -1 case
      cls = "humangrad" + (player === 0 ? "_left" : "_right"); /* Local player */
    else {
      cls = "autoplayergrad" + (player === 0 ? "_left" : "_right"); /* Remote player */
      playerColor = 1;
    }
    let attribs: VnodeAttrs = { title: title };
    // Word lookup
    attribs.onclick = () => { window.open('https://malid.is/leit/' + word, 'malid'); };
    // Highlight the move on the board while hovering over it
    attribs.onmouseover = () => {
      move.highlighted = true;
      highlightMove(rawCoord, tiles, playerColor, true);
    };
    attribs.onmouseout = () => {
      move.highlighted = false;
      highlightMove(rawCoord, tiles, playerColor, false);
    };
    if (player === 0) {
      // Move by left side player
      return m(".move.leftmove." + cls, attribs,
        [
          m("span.score" + (move.highlighted ? ".highlight" : ""), score),
          m("span.wordmove", [ m("i", word), nbsp(), co ])
        ]
      );
    }
    else {
      // Move by right side player
      return m(".move.rightmove." + cls, attribs,
        [
          m("span.wordmove", [ co, nbsp(), m("i", word) ]),
          m("span.score" + (move.highlighted ? ".highlight" : ""), score)
        ]
      );
    }
  }

  vwGames(model: Model) {
    // The game list tab

    function games() {
      let r = [];
      // var numMyTurns = 0;
      let gameList = model.gameList;
      if (gameList === undefined) {
        // Game list is being loaded
      }
      else
      if (gameList === null)
        // No games to show now, but we'll load them
        // and they will be automatically refreshed when ready
        model.loadGameList();
      else {
        let numGames = gameList.length;
        let game = model.game;
        let gameId = game ? game.uuid : "";
        for (let i = 0; i < numGames; i++) {
          let item = gameList[i];
          if (item.uuid == gameId)
            continue; // Don't show this game
          if (!item.my_turn && !item.zombie)
            continue; // Only show pending games
          var opp: any[];
          if (item.oppid === null)
            // Mark robots with a cog icon
            opp = [ glyph("cog"), nbsp(), item.opp ];
          else
            opp = [ item.opp ];
          let winLose = item.sc0 < item.sc1 ? ".losing" : "";
          let title = "Staðan er " + item.sc0 + ":" + item.sc1;
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

  Bag: ComponentFunc<{ bag: string; newbag: string; }> = (initialVnode) => {
    // The bag of tiles

    function tiles(bag: string) {
      let r = [];
      let ix = 0;
      let count = bag.length;
      while (count > 0) {
        // Rows
        let cols = [];
        // Columns: max BAG_TILES_PER_LINE tiles per row
        for (let i = 0; i < BAG_TILES_PER_LINE && count > 0; i++) {
          let tile = bag[ix++];
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

    return {
      view: (vnode) => {
        let bag = vnode.attrs.bag;
        let newbag = vnode.attrs.newbag;
        let cls = "";
        if (bag.length <= RACK_SIZE)
          cls += ".empty";
        else
        if (newbag)
          cls += ".new";
        return m(".bag",
          { title: 'Flísar sem eftir eru í pokanum' },
          m("table.bag-content" + cls, tiles(bag))
        );
      }
    };
  }

  BlankDialog: ComponentFunc<{ game: Game; }> = (initialVnode) => {
    // A dialog for choosing the meaning of a blank tile

    let game = initialVnode.attrs.game;

    function blankLetters() {
      let legalLetters = game.alphabet;
      let len = legalLetters.length;
      let ix = 0;
      let r = [];

      while (len > 0) {
        /* Rows */
        let c = [];
        /* Columns: max BLANK_TILES_PER_LINE tiles per row */
        for (let i = 0; i < BLANK_TILES_PER_LINE && len > 0; i++) {
          let letter = legalLetters[ix++];
          c.push(
            m("td",
              {
                onclick: (ev) => { game.placeBlank(letter); ev.preventDefault(); },
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

    return {
      view: (vnode) => {
        return m(".modal-dialog",
          {
            id: 'blank-dialog',
            style: { visibility: "visible" }
          },
          m(".ui-widget.ui-widget-content.ui-corner-all", { id: 'blank-form' },
            [
              m("p", "Hvaða staf táknar auða flísin?"),
              m(".rack.blank-rack",
                m("table.board", { id: 'blank-meaning' }, blankLetters())
              ),
              m(DialogButton,
                {
                  id: 'blank-close',
                  title: 'Hætta við',
                  onclick: (ev) => {
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
    };
  }

  BackButton: ComponentFunc<{}> = (initialVnode) => {
    // Icon for going back to the main screen
    return {
      view: (vnode) => {
        return m(".logo-back", 
          m(m.route.Link,
            {
              href: "/page",
              class: "backlink"
            },
            m(ExploLogo, { legend: false, scale: 1.5 })
          )
        );
      }
    };
  }

  BoardArea: ComponentFunc<{ model: Model; }> = (initialVnode) => {
    // Collection of components in the board (left-side) area
    let model = initialVnode.attrs.model;
    return {
      view: (vnode) => {
        let game = model.game;
        let r = [];
        if (game) {
          r = [
            m(this.Board, { model: model }),
            m(this.Rack, { model: model }),
            this.vwButtons(model),
            this.vwErrors(game),
            this.vwCongrats(game)
          ];
          r = r.concat(this.vwDialogs(game));
        }
        return m(".board-area", r);
      }
    };
  }

  BoardReview: ComponentFunc<{ model: Model; move: number; }> = (initialVnode) => {
    // The board area within a game review screen
    let model = initialVnode.attrs.model;
    return {
      view: (vnode) => {
        let game = model.game;
        let r = [];
        if (game) {
          r = [
            m(this.Board, { model: model }),
            m(this.Rack, { model: model }),
          ];
          if (vnode.attrs.move !== null)
            // Don't show navigation buttons if currently at overview (move==null)
            r.push(this.vwButtonsReview(model, vnode.attrs.move));
        }
        return m(".board-area", r);
      }
    };
  }

  Tile: ComponentFunc<{ game: Game; coord: string; opponent: boolean; }> = (initialVnode) => {
    // Display a tile on the board or in the rack
    return {
      view: (vnode) => {
        let game = vnode.attrs.game;
        let coord = vnode.attrs.coord;
        let opponent = vnode.attrs.opponent;
        // A single tile, on the board or in the rack
        let t = game.tiles[coord];
        let classes = [ ".tile" ];
        let attrs: VnodeAttrs = {};
        if (t.tile == '?')
          classes.push("blanktile");
        if (t.letter == 'z' || t.letter == 'q' || t.letter == 'x')
          // Wide letter: handle specially
          classes.push("wide");
        if (coord[0] == 'R' || t.draggable) {
          // Rack tile, or at least a draggable one
          classes.push(opponent ? "freshtile" : "racktile");
          if (coord[0] == 'R' && game.showingDialog == "exchange") {
            // Rack tile, and we're showing the exchange dialog
            if (t.xchg)
              // Chosen as an exchange tile
              classes.push("xchgsel");
            // Exchange dialog is live: add a click handler for the
            // exchange state
            attrs.onclick = (ev) => {
              // Toggle the exchange status of this tile
              t.xchg = !t.xchg;
              ev.preventDefault();
            };
          }
        }
        if (t.freshtile) {
          // A fresh tile that has just been played by the opponent
          classes.push("freshtile");
          // Make fresh tiles appear sequentally by animation
          let ANIMATION_STEP = 150; // Milliseconds
          let delay = (t.index * ANIMATION_STEP).toString() + "ms";
          attrs.style = "animation-delay: " + delay + "; " +
            "-webkit-animation-delay: " + delay + ";";
        }
        if (coord == game.selectedSq)
          classes.push("sel"); // Blinks red
        if (t.highlight !== undefined) {
          // highlight0 is the local player color (yellow/orange)
          // highlight1 is the remote player color (green)
          classes.push("highlight" + t.highlight);
          /*
          if (t.player == parseInt(t.highlight))
            // This tile was originally laid down by the other player
            classes.push("dim");
          */
        }
        if (game.showingDialog === null && !game.over) {
          if (t.draggable) {
            // Make the tile draggable, unless we're showing a dialog
            attrs.draggable = "true";
            attrs.ondragstart = (ev) => {
              // ev.dataTransfer.effectAllowed = "copyMove";
              game.selectedSq = null;
              ev.dataTransfer.effectAllowed = "move";
              ev.dataTransfer.setData("text", coord);
              ev.redraw = false;
            };
            attrs.onclick = (ev) => {
              // When clicking a tile, make it selected (blinking)
              if (coord == game.selectedSq)
                // Clicking again: deselect
                game.selectedSq = null;
              else
                game.selectedSq = coord;
              ev.stopPropagation();
            };
          }
        }
        return m(classes.join("."), attrs,
          [ t.letter == ' ' ? nbsp() : t.letter, m(".letterscore", t.score) ]
        );
      }
    };
  }

  ReviewTile: ComponentFunc<{ coord: string, game: Game; }> = (initialVnode) => {
    // Return a td element that wraps an 'inert' tile in a review screen
    return {
      view: (vnode) => {
        let coord = vnode.attrs.coord;
        return m("td",
          {
            key: coord,
            id: "sq_" + coord,
            class: vnode.attrs.game.squareClass(coord)
          },
          vnode.children
        );
      }
    };
  };

  DropTarget: ComponentFunc<{ model: Model; coord: string; }> = (initialVnode) => {
    // Return a td element that is a target for dropping tiles
    return {
      view: (vnode) => {
        let model = vnode.attrs.model;
        let coord = vnode.attrs.coord;
        let game = model.game;
        let cls = "";
        // Mark the cell with the 'blinking' class if it is the drop
        // target of a pending blank tile dialog
        if (game.askingForBlank !== null && game.askingForBlank.to == coord)
          cls += ".blinking";
        if (coord == game.centerSquare)
          // Unoccupied center square, first move
          cls += ".center";
        return m("td" + cls,
          {
            key: coord,
            id: "sq_" + coord,
            class: game.squareClass(coord),
            ondragenter: (ev) => {
              ev.preventDefault();
              ev.dataTransfer.dropEffect = 'move';
              (ev.currentTarget as HTMLElement).classList.add("over");
              ev.redraw = false;
              return false;
            },
            ondragleave: (ev) => {
              ev.preventDefault();
              (ev.currentTarget as HTMLElement).classList.remove("over");
              ev.redraw = false;
              return false;
            },
            ondragover: (ev) => {
              // This is necessary to allow a drop
              ev.preventDefault();
              ev.redraw = false;
              return false;
            },
            ondrop: (ev) => {
              ev.stopPropagation();
              (ev.currentTarget as HTMLElement).classList.remove("over");
              // Move the tile from the source to the destination
              let from = ev.dataTransfer.getData("text");
              game.attemptMove(from, coord);
              model.updateScale();
              return false;
            },
            onclick: (ev) => {
              // If a square is selected (blinking red) and
              // we click on an empty square, move the selected tile
              // to the clicked square
              if (game.selectedSq !== null) {
                ev.stopPropagation();
                game.attemptMove(game.selectedSq, coord);
                game.selectedSq = null;
                (ev.currentTarget as HTMLElement).classList.remove("sel");
                model.updateScale();
                return false;
              }
            },
            onmouseover: (ev) => {
              // If a tile is selected, show a red selection square
              // around this square when the mouse is over it
              if (game.selectedSq !== null)
                (ev.currentTarget as HTMLElement).classList.add("sel");
            },
            onmouseout: (ev) => {
              (ev.currentTarget as HTMLElement).classList.remove("sel");
            }
          },
          vnode.children
        );
      }
    };
  }

  Board: ComponentFunc<{ model: Model; }> = (initialVnode) => {
    // The game board, a 15x15 table plus row (A-O) and column (1-15) identifiers

    let view = this;

    function colid() {
      // The column identifier row
      let r = [];
      r.push(m("td"));
      for (let col = 1; col <= 15; col++)
        r.push(m("td", col.toString()));
      return m("tr.colid", r);
    }

    function row(model: Model, rowid: string) {
      // Each row of the board
      let r = [];
      let game = model.game;
      r.push(m("td.rowid", /* { key: "R" + rowid }, */ rowid));
      for (let col = 1; col <= 15; col++) {
        let coord = rowid + col.toString();
        if (game && (coord in game.tiles))
          // There is a tile in this square: render it
          r.push(m("td",
            {
              // key: coord,
              id: "sq_" + coord,
              class: game.squareClass(coord),
              ondragover: (ev) => ev.stopPropagation(),
              ondrop: (ev) => ev.stopPropagation()
            },
            m(view.Tile, { game: game, coord: coord, opponent: false })
          ));
        else
          // Empty square which is a drop target
          r.push(m(view.DropTarget, { model: model, coord: coord }));
      }
      return m("tr", r);
    }

    function allrows(model: Model) {
      // Return a list of all rows on the board
      let r = [];
      r.push(colid());
      let rows = "ABCDEFGHIJKLMNO";
      for (let i = 0; i < rows.length; i++)
        r.push(row(model, rows[i]));
      return r;
    }

    function zoomIn(model: Model) {
      model.boardScale = 1.5;
    }

    function zoomOut(model: Model) {
      if (model.boardScale != 1.0) {
        model.boardScale = 1.0;
        setTimeout(model.resetScale);
      }
    }

    return {
      view: (vnode) => {
        let model = vnode.attrs.model;
        let scale = model.boardScale || 1.0;
        let attrs: VnodeAttrs = {};
        // Add handlers for pinch zoom functionality
        addPinchZoom(attrs, () => zoomIn(model), () => zoomOut(model));
        if (scale != 1.0)
          attrs.style = "transform: scale(" + scale + ")";
        return m(".board",
          { id: "board-parent" },
          m("table.board", attrs, m("tbody", allrows(model)))
        );
      }
    };
  }

  Rack: ComponentFunc<{ model: Model; }> = (initialVnode) => {
    // A rack of 7 tiles
    let view = this;
    return {
      view: (vnode) => {
        let model = vnode.attrs.model;
        let game = model.game;
        let r = [];
        // If review==true, this is a review rack
        // that is not a drop target and whose color reflects the
        // currently shown move.
        let review = model.reviewMove !== null;
        // If opponent==true, we're showing the opponent's rack
        let opponent = review && (model.reviewMove > 0) && (model.reviewMove % 2 == game.player);
        for (let i = 1; i <= RACK_SIZE; i++) {
          let coord = 'R' + i.toString();
          if (game && (coord in game.tiles)) {
            // We have a tile in this rack slot, but it is a drop target anyway
            if (review) {
              r.push(
                m(view.ReviewTile, { game: game, coord: coord },
                  m(view.Tile, { game: game, coord: coord, opponent: opponent })
                )
              );
            }
            else {
              r.push(
                m(view.DropTarget, { model: model, coord: coord },
                  m(view.Tile, { game: game, coord: coord, opponent: false })
                )
              );
            }
          }
          else
          if (review)
            r.push(m(view.ReviewTile, { game: game, coord: coord }));
          else
            r.push(m(view.DropTarget, { model: model, coord: coord }));
        }
        return m(".rack-row", [
          m(".rack-left", view.vwRackLeftButtons(model)),
          m(".rack", m("table.board", m("tbody", m("tr", r)))),
          m(".rack-right", view.vwRackRightButtons(model))
        ]);
      }
    };
  };

  vwRackLeftButtons(model: Model) {
    // The button to the left of the rack in the mobile UI
    var s = this.buttonState(model.game);
    if (s.showRecall && !s.showingDialog)
      // Show a 'Recall tiles' button
      return this.makeButton(
        "recallbtn", false,
        () => { model.game.resetRack(); model.updateScale(); },
        "Færa stafi aftur í rekka", glyph("down-arrow")
      );
    if (s.showScramble && !s.showingDialog)
      // Show a 'Scramble rack' button
      return this.makeButton(
        "scramblebtn", false,
        () => { model.game.rescrambleRack(); },
        "Stokka upp rekka", glyph("random")
      );
    return [];
  }

  vwRackRightButtons(model: Model) {
    // The button to the right of the rack in the mobile UI
    var s = this.buttonState(model.game);
    if (s.canPlay && !s.showingDialog)
      // Show a 'Submit move' button, with a Play icon
      return this.makeButton(
        "submitmove", false,
        () => { model.game.submitMove(); model.updateScale(); },
        "Leika", glyph("play")
      );
    return [];
  }

  vwScore(game: Game) {
    // Shows the score of the current word
    let sc = [ ".score" ];
    if (game.manual)
      sc.push("manual");
    else
    if (game.wordGood) {
      sc.push("word-good");
      if (game.currentScore >= 50)
        sc.push("word-great");
    }
    let txt = (game.currentScore === undefined ? "?" : game.currentScore.toString())
    return m(sc.join("."), { title: txt }, txt);
  }

  vwScoreReview(game: Game, move?: number) {
    // Shows the score of the current move within a game review screen
    let mv = move ? game.moves[move - 1] : undefined;
    let score = mv ? mv[1][2] : undefined;
    if (score === undefined)
      return undefined;
    let sc = [ ".score" ];
    if (move > 0) {
      if (move % 2 == game.player)
        // Opponent move: show in green
        sc.push("green");
      else
        // Player's move: show in yellow
        sc.push("yellow");
    }
    return m(sc.join("."), score.toString());
  }

  vwScoreDiff(model: Model, move: number) {
    // Shows the score of the current move within a game review screen
    let game = model.game;
    let sc = [ ".scorediff" ];
    let mv = move ? game.moves[move - 1] : undefined;
    let score = mv ? mv[1][2] : undefined;
    let bestScore = model.bestMoves[model.highlightedMove][1][2];
    if (score >= bestScore)
      sc.push("posdiff");
    return m(
      sc.join("."),
      { style: { visibility: "visible" }},
      (score - bestScore).toString()
    );
  }

  vwStatsReview(game: Game) {
    // Shows the game statistics overlay
    if (game.stats === null)
      // No stats yet loaded: do it now
      game.loadStats();

    function fmt(p: string, digits?: number, value?: string | number) : string {
      var txt = value;
      if (txt === undefined && game.stats)
          txt = game.stats[p];
      if (txt === undefined)
        return "";
      if (typeof txt == "number") {
        if (digits !== undefined && digits > 0)
          txt = txt.toFixed(digits).replace(".", ","); // Convert decimal point to comma
        else
          txt = txt.toString();
      }
      return txt;
    }

    let leftPlayerColor: string, rightPlayerColor: string;

    if (game.player == 1) {
      rightPlayerColor = "humancolor";
      leftPlayerColor = "autoplayercolor";
    }
    else {
      leftPlayerColor = "humancolor";
      rightPlayerColor = "autoplayercolor";
    }

    return m(
      ".gamestats", { style: { visibility: "visible" } },
      [
        m("div", { style: { position: "relative", width: "100%" } },
          [
            m(".player", { class: leftPlayerColor, style: { width: "50%" } }, 
              m(".robot-btn.left",
                game.autoplayer[0] ?
                  [ glyph("cog"), nbsp(), game.nickname[0] ]
                :
                  game.nickname[0]
              )
            ),
            m(".player", { class: rightPlayerColor, style: { width: "50%", "text-align": "right" } },
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
            m("p", ["Meðalstig stafa (án auðra): ", m("span", fmt("average0", 2))]),
            m("p", ["Samanlögð stafastig: ", m("span", fmt("letterscore0"))]),
            m("p", ["Margföldun stafastiga: ", m("span", fmt("multiple0", 2))]),
            m("p", ["Stig án stafaleifar í lok: ", m("span", fmt("cleantotal0"))]),
            m("p", ["Meðalstig hvers leiks: ", m("span", fmt("avgmove0", 2))]),
            game.manual ? m("p", ["Rangar véfengingar andstæðings x 10: ", m("span", fmt("wrongchall0"))]) : "",
            m("p", ["Stafaleif og frádráttur í lok: ", m("span", fmt("remaining0"))]),
            m("p", ["Umframtími: ", m("span", fmt("overtime0"))]),
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
            m("p", ["Meðalstig stafa (án auðra): ", m("span", fmt("average1", 2))]),
            m("p", ["Samanlögð stafastig: ", m("span", fmt("letterscore1"))]),
            m("p", ["Margföldun stafastiga: ", m("span", fmt("multiple1", 2))]),
            m("p", ["Stig án stafaleifar í lok: ", m("span", fmt("cleantotal1"))]),
            m("p", ["Meðalstig hvers leiks: ", m("span", fmt("avgmove1", 2))]),
            game.manual ? m("p", ["Rangar véfengingar andstæðings x 10: ", m("span", fmt("wrongchall1"))]) : "",
            m("p", ["Stafaleif og frádráttur í lok: ", m("span", fmt("remaining1"))]),
            m("p", ["Umframtími: ", m("span", fmt("overtime1"))]),
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
            onclick: (ev) => {
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

  makeButton(
    cls: string, disabled: boolean, func: () => void, title: string, children?: any, id?: string
  ) {
    // Create a button element, wrapping the disabling logic
    // and other boilerplate
    let attr: VnodeAttrs = {
      onmouseout: buttonOut,
      onmouseover: buttonOver,
      title: title
    };
    if (id !== undefined)
      attr.id = id;
    if (disabled)
      attr.onclick = (ev) => ev.preventDefault();
    else
      attr.onclick = (ev) => {
        if (func)
          func();
        ev.preventDefault();
      };
    return m("." + cls + (disabled ? ".disabled" : ""),
      attr, children // children may be omitted
    );
  }

  vwButtons(model: Model) {
    // The set of buttons below the game board, alongside the rack
    let game = model.game;
    let s = this.buttonState(game);
    let r = [];
    r.push(m(".word-check" +
      (s.wordGood ? ".word-good" : "") +
      (s.wordBad ? ".word-bad" : "")));
    if (s.showChallenge)
      r.push(
        this.makeButton(
          "challenge", (s.tilesPlaced && !s.lastChallenge) || s.showingDialog,
          () => game.submitChallenge(),
          'Véfenging (röng kostar 10 stig)'
        )
      );
    if (s.showChallengeInfo)
      r.push(m(".chall-info"));
    if (s.showRecall)
      r.push(
        this.makeButton(
          "recallbtn", false,
          () => { game.resetRack(); model.updateScale(); },
          "Færa stafi aftur í rekka", glyph("down-arrow")
        )
      );
    if (s.showScramble)
      r.push(
        this.makeButton("scramblebtn", s.showingDialog,
          () => game.rescrambleRack(),
          "Stokka upp rekka", glyph("random")
        )
      );
    if (s.showMove)
      r.push(
        this.makeButton(
          "submitmove", !s.tilesPlaced || s.showingDialog,
          () => game.submitMove(), // No need to updateScale() here
          "Leika", [ "Leika", nbsp(), glyph("play") ]
        )
      );
    if (s.showPass)
      r.push(
        this.makeButton(
          "submitpass", (s.tilesPlaced && !s.lastChallenge) || s.showingDialog,
          () => game.submitPass(),
          "Pass", glyph("forward")
        )
      );
    if (s.showExchange)
      r.push(
        this.makeButton(
          "submitexchange", s.tilesPlaced || s.showingDialog || !s.exchangeAllowed,
          () => game.submitExchange(),
          "Skipta stöfum", glyph("refresh")
        )
      );
    if (s.showResign)
      r.push(
        this.makeButton(
          "submitresign", s.showingDialog,
          () => game.submitResign(),
          "Gefa viðureign", glyph("fire")
        )
      );
    if (!s.gameOver && !s.localTurn) {
      // Indicate that it is the opponent's turn; offer to force a resignation
      // if the opponent hasn't moved for 14 days
      r.push(
        m(".opp-turn",
          { style: { visibility: "visible" } },
          [
            m("span.move-indicator"),
            nbsp(),
            m("strong", game.nickname[1 - game.player]),
            " á leik",
            nbsp(),
            s.tardyOpponent ? m("span.yesnobutton",
              {
                id: 'force-resign',
                style: { display: "inline" },
                onclick: (ev) => ev.preventDefault(), // !!! FIXME: Implement forced resignation
                onmouseout: buttonOut,
                onmouseover: buttonOver,
                title: '14 dagar liðnir án leiks'
              },
              "Þvinga til uppgjafar"
            ) : ""
          ]
        )
      );
    }
    if (s.tilesPlaced)
      r.push(this.vwScore(game));
    // Is the server processing a move?
    if (game.moveInProgress)
      r.push(
        m(".waitmove", { style: { display: "block" } },
          m("img",
            {
              src: '/static/ajax-loader.gif', border: 0,  // !!! FIXME: Incorrect GIF
              width: 16, height:16
            }
          )
        )
      );
    return r;
  }

  vwButtonsReview(model: Model, move: number) {
    // The navigation buttons below the board on the review screen
    let game = model.game;
    let r = [];
    r.push(
      this.makeButton(
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
      this.makeButton(
        "navbtn", (!move) || (move + 1 >= game.moves.length),
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
    // Show the score difference between an actual move and
    // a particular move on the best move list
    if (model.highlightedMove !== null)
      r.push(this.vwScoreDiff(model, move));
    r.push(this.vwScoreReview(game, move));
    return r;
  }

  vwErrors(game: Game) {
    // Error messages, selectively displayed
    var msg: string = game.currentMessage || "";
    var errorMessages = {
      1: "Enginn stafur lagður niður",
      2: "Fyrsta orð verður að liggja um byrjunarreitinn",
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

  vwCongrats(game: Game) {
    // Congratulations message when a game has been won
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

  vwDialogs(game: Game) {
    // Show prompt dialogs below game board, if any
    let r = [];
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
          m("span.yesnobutton", { onclick: () => game.confirmResign(true) },
            [ glyph("ok"), " Já" ]
          ),
          m("span.mobile-space"),
          m("span.yesnobutton", { onclick: () => game.confirmResign(false) },
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
          m("span.yesnobutton", { onclick: () => game.confirmPass(true) },
            [ glyph("ok"), " Já" ]
          ),
          m("span.mobile-space"),
          m("span.yesnobutton", { onclick: () => game.confirmPass(false) },
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
          m("span.yesnobutton", { onclick: () => game.confirmPass(true) },
            [ glyph("ok"), " Já" ]
          ),
          m("span.mobile-space"),
          m("span.yesnobutton", { onclick: () => game.confirmPass(false) },
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
            { onclick: () => game.confirmExchange(true) },
            glyph("ok")),
          m("span.mobile-space"),
          m("span.yesnobutton[title='Hætta við']",
            { onclick: () => game.confirmExchange(false) },
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
            { onclick: () => game.confirmChallenge(true) },
            [ glyph("ok"), " Já" ]
          ),
          m("span.mobile-space"),
          m("span.yesnobutton",
            { onclick: () => game.confirmChallenge(false) },
            [ glyph("remove"), " Nei" ]
          )
        ]
      ));
    return r;
  }

  makeTabs(id: string, createFunc: (vnode: Vnode) => void, wireHrefs: boolean, vnode: Vnode) {
    // When the tabs are displayed for the first time, wire'em up
    var tabdiv = document.getElementById(id);
    if (!tabdiv)
      return;
    // Add bunch of jQueryUI compatible classes
    tabdiv.setAttribute("class", "ui-tabs ui-widget ui-widget-content ui-corner-all");
    var tabul = document.querySelector("#" + id + " > ul");
    tabul.setAttribute("class", "ui-tabs-nav ui-helper-reset ui-helper-clearfix ui-widget-header ui-corner-all");
    tabul.setAttribute("role", "tablist");
    var tablist = document.querySelectorAll("#" + id + " > ul > li > a") as NodeListOf<HTMLElement>;
    var tabitems = document.querySelectorAll("#" + id + " > ul > li") as NodeListOf<HTMLElement>;
    var ids = [];
    var lis = []; // The <li> elements
    // Iterate over the <a> elements inside the <li> elements inside the <ul>
    for (let i = 0; i < tablist.length; i++) {
      ids.push(tablist[i].getAttribute("href").slice(1));
      // Decorate the <a> elements
      tablist[i].onclick = (ev) => { selectTab(vnode, i); ev.preventDefault(); };
      tablist[i].setAttribute("href", null);
      tablist[i].setAttribute("class", "ui-tabs-anchor sp"); // Single-page marker
      tablist[i].setAttribute("role", "presentation");
      // Also decorate the <li> elements
      lis.push(tabitems[i]);
      tabitems[i].setAttribute("class", "ui-state-default ui-corner-top");
      tabitems[i].setAttribute("role", "tab");
      tabitems[i].onmouseover = (ev) => {
        (ev.currentTarget as HTMLElement).classList.toggle("ui-state-hover", true);
      };
      tabitems[i].onmouseout = (ev) => {
        (ev.currentTarget as HTMLElement).classList.toggle("ui-state-hover", false);
      };
      // Find the tab's content <div>
      let tabcontent = document.getElementById(ids[i]);
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
      let clickURL = (ev: Event, href: string) => {
        var uri = href.slice(ROUTE_PREFIX_LEN); // Cut the /page#!/ prefix off the route
        var qix = uri.indexOf("?");
        var route = (qix >= 0) ? uri.slice(0, qix) : uri;
        var qparams = uri.slice(route.length + 1);
        var params = qparams.length ? getUrlVars(qparams) : { };
        m.route.set(route, params);
        if (window.history)
          window.history.pushState({}, "", href); // Enable the back button
        ev.preventDefault();
      };
      let clickUserPrefs = (ev: Event) => {
        if ($state.userId != "")
          // Don't show the userprefs if no user logged in
          this.pushDialog("userprefs");
        ev.preventDefault();
      };
      let clickTwoLetter = (ev: Event) => {
        selectTab(vnode, 2); // Select tab number 2
        ev.preventDefault();
      };
      let clickNewBag = (ev: Event) => {
        selectTab(vnode, 3); // Select tab number 3
        ev.preventDefault();
      };
      let anchors = tabdiv.querySelectorAll("a");
      for (let i = 0; i < anchors.length; i++) {
        let a = anchors[i];
        let href = a.getAttribute("href");
        if (href && href.slice(0, ROUTE_PREFIX_LEN) == ROUTE_PREFIX) {
          // Single-page URL: wire it up (as if it had had an m.route.Link on it)
          a.onclick = (ev) => clickURL(ev, href);
        }
        else
        if (href && href == "$$userprefs$$") {
          // Special marker indicating that this link invokes
          // a user preference dialog
          a.onclick = clickUserPrefs;
        }
        else
        if (href && href == "$$twoletter$$") {
          // Special marker indicating that this link invokes
          // the two-letter word list or the opponents tab
          a.onclick = clickTwoLetter;
        }
        else
        if (href && href == "$$newbag$$") {
          // Special marker indicating that this link invokes
          // the explanation of the new bag
          a.onclick = clickNewBag;
        }
      }
    }
    // If a createFunc was specified, run it now
    if (createFunc)
      createFunc(vnode);
    // Finally, make the default tab visible and hide the others
    updateTabVisibility(vnode);
  }

} // class View

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
    model.routeName = routeName;
    model.params = params;
    if (routeName == "game") {
      // New game route: initiate loading of the game into the model
      if (model.game !== null) {
        this.detachListenerFromGame(model.game.uuid);
      }
      // Load the game, and attach it to the Firebase listener once it's loaded
      model.loadGame(params.uuid, () => this.attachListenerToGame(params.uuid));
    }
    else
    if (routeName == "review") {
      // A game review: detach listener, if any, and load
      // new game if necessary
      if (model.game !== null) {
        // !!! This may cause an extra detach - we assume that's OK
        this.detachListenerFromGame(model.game.uuid);
      }
      if (model.game === null || model.game.uuid != params.uuid)
        // Different game than we had before: load it
        model.loadGame(params.uuid, undefined); // No funcComplete
      if (model.game !== null) {
        let move: string | number = params.move;
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
        this.detachListenerFromGame(model.game.uuid);
        model.game.cleanup();
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

  onMoveMessage(json: any) {
    // Handle a move message from Firebase
    console.log("Move message received: " + JSON.stringify(json));
    this.model.handleMoveMessage(json);
  }

  onUserMessage(json: any) {
    // Handle a user message from Firebase
    console.log("User message received: " + JSON.stringify(json));
    this.model.handleUserMessage(json);
  }

  onChatMessage(json: { from_userid: string; game: string; msg: string; ts: string; }) {
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
    if (this.model.addChatMessage(json.game, json.from_userid, json.msg, json.ts)) {
      // A chat message was successfully added
      this.view.notifyChatMessage();
    }
  }

  onFullScreen() {
    // Take action when min-width exceeds 768
    if (!$state.uiFullscreen) {
      $state.uiFullscreen = true;
      this.view.notifyMediaChange(this.model);
      m.redraw();
    }
  }

  onMobileScreen () {
    if ($state.uiFullscreen) {
      $state.uiFullscreen = false;
      this.view.notifyMediaChange(this.model);
      m.redraw();
    }
  }

  onLandscapeScreen() {
    if (!$state.uiLandscape) {
      $state.uiLandscape = true;
      this.view.notifyMediaChange(this.model);
      m.redraw();
    }
  }

  onPortraitScreen() {
    if ($state.uiLandscape) {
      $state.uiLandscape = false;
      this.view.notifyMediaChange(this.model);
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
    let mql: MediaQueryList = window.matchMedia("(min-width: 667px)");
    let view = this;
    if (mql) {
      this.mediaMinWidth667(mql);
      mql.addEventListener("change",
        function(ev: MediaQueryListEvent) {
          view.mediaMinWidth667(this);
        }
      );
    }
    mql = window.matchMedia("(min-width: 768px)");
    if (mql) {
      this.mediaMinWidth768(mql);
      mql.addEventListener("change",
        function(ev: MediaQueryListEvent) {
          view.mediaMinWidth768(this);
        }
      );
    }
  }

  initFirebaseListener() {
    // Sign into Firebase with the token passed from the server
    loginFirebase($state.firebaseToken);
  }

  attachListenerToUser() {
    if ($state.userId)
      attachFirebaseListener('user/' + $state.userId, (json) => this.onUserMessage(json));
  }

  detachListenerFromUser() {
    // Stop listening to Firebase notifications for the current user
    if ($state.userId)
      detachFirebaseListener('user/' + $state.userId);
  }

  attachListenerToGame(uuid: string) {
    // Listen to Firebase events on the /game/[gameId]/[userId] path
    var basepath = 'game/' + uuid + "/" + $state.userId + "/";
    // New moves
    attachFirebaseListener(basepath + "move", (json) => this.onMoveMessage(json));
    // New chat messages
    attachFirebaseListener(basepath + "chat", (json) => this.onChatMessage(json));
  }

  detachListenerFromGame(uuid: string) {
    // Stop listening to Firebase events on the /game/[gameId]/[userId] path
    var basepath = 'game/' + uuid + "/" + $state.userId + "/";
    detachFirebaseListener(basepath + "move");
    detachFirebaseListener(basepath + "chat");
  }

} // class Actions

function createRouteResolver(actions: Actions) {

  // Return a map of routes to onmatch and render functions

  let model = actions.model;
  let view = actions.view;

  return model.paths.reduce((acc, item) => {
    acc[item.route] = {

      // Navigating to a new route
      onmatch: (params: Params, route: string) => {
        // Automatically close all dialogs
        view.popAllDialogs();
        if ($state.userId == "" && item.mustLogin)
          // Attempting to navigate to a new path that
          // requires a login, but the user hasn't logged
          // in: go to the login route
          m.route.set("/login");
        else
          actions.onNavigateTo(item.name, params);
      },

      // Render a view on a model
      render: () => view.appView(model, actions)

    };
    return acc;
  }, {});
}

// General-purpose Mithril components

const ExploLogo: ComponentFunc<{ scale: number; legend: boolean; }> = (initialVnode) => {

  // The Explo logo, with or without the legend ('explo')

  var scale = initialVnode.attrs.scale || 1.0;
  var legend = initialVnode.attrs.legend;

  return {
    view: (vnode) => {
      return m("img",
        legend ?
          {
            alt: 'Explo',
            width: 89 * scale, height: 40 * scale,
            src: '/static/explo-logo.svg'
          }
        :
          {
            alt: 'Explo',
            width: 23 * scale, height: 40 * scale,
            src: '/static/explo-logo-only.svg'
          }
      );
    }
  };
};

const LeftLogo: ComponentFunc<{}> = () => {
  return {
    view: () => {
      return m(".logo",
        m(m.route.Link,
          { href: '/main', class: "nodecorate" },
          m(ExploLogo, { legend: false, scale: 1.5 })
        )
      );
    }
  };
};

const TextInput: ComponentFunc<{
  initialValue: string;
  class: string;
  maxlength: number;
  id: string;
  tabindex: number;
}> = (initialVnode) => {

  // Generic text input field

  let text = initialVnode.attrs.initialValue + "";
  let cls = initialVnode.attrs.class;
  if (cls)
    cls = "." + cls.split(" ").join(".");
  else
    cls = "";

  return {
    view: (vnode) => {
      return m("input.text" + cls,
        {
          id: vnode.attrs.id,
          name: vnode.attrs.id,
          maxlength: vnode.attrs.maxlength,
          tabindex: vnode.attrs.tabindex,
          value: text,
          oninput: (ev) => { text = (ev.target as HTMLInputElement).value + ""; }
        }
      );
    }
  };

}

// A nice graphical toggler control

function vwToggler(id: string, state: boolean, tabindex: number, opt1, opt2, func?: Function, small?: boolean, title?: string) {

  var togglerId = id + "-toggler";
  var optionClass = ".option" + (small ? ".small" : "");

  function doToggle() {
    // Perform the toggling, on a mouse click or keyboard input (space bar)
    var cls1 = document.querySelector("#" + togglerId + " #opt1").classList;
    var cls2 = document.querySelector("#" + togglerId + " #opt2").classList;
    cls1.toggle("selected");
    cls2.toggle("selected");
    if (func !== undefined)
      // Toggling the switch and we have an associated function:
      // call it with the boolean state of the switch
      func(cls2.contains("selected"));
  }

  return [
    m("input.checkbox." + id,
      {
        type: "checkbox",
        id: id,
        name: id,
        checked: state,
        value: 'True'
      }
    ),
    m(".toggler",
      {
        id: togglerId,
        tabindex: tabindex,
        title: title,
        onclick: () => doToggle(),
        onkeypress: (ev) => {
          if (ev.key == " ")
            doToggle();
        }
      },
      [
        m(optionClass + (state ? "" : ".selected"), { id: "opt1" }, opt1),
        m(optionClass + (state ? ".selected" : ""), { id: "opt2" }, opt2)
      ]
    )
  ];
}

const MultiSelection: ComponentFunc<{
  initialSelection: number;
  defaultClass: string;
  selectedClass: string;
}> = (initialVnode) => {

  // A multiple-selection div where users can click on child nodes
  // to select them, giving them an addional selection class,
  // typically .selected

  let sel = initialVnode.attrs.initialSelection || 0;
  let defaultClass = initialVnode.attrs.defaultClass || "";
  let selectedClass = initialVnode.attrs.selectedClass || "selected";

  return {
    view: (vnode) => {
      return m("div",
        {
          onclick: (ev) => {
            // Catch clicks that are propagated from children up
            // to the parent div. Find which child originated the
            // click (possibly in descendant nodes) and set
            // the current selection accordingly.
            let childNodes = vnode.dom.childNodes as NodeListOf<HTMLElement>;
            for (let i = 0; i < childNodes.length; i++)
              if (childNodes[i].contains(ev.target as Node))
                sel = i;
            ev.stopPropagation();
          }
        },
        vnode.children.map((item, i) => {
          // A pretty gross approach, but it works: clobber the childrens' className
          // attribute depending on whether they are selected or not
          if (i == sel)
            item.attrs.className = defaultClass + " " + selectedClass;
          else
            item.attrs.className = defaultClass;
          return item;
        })
      );
    }
  };

};

const OnlinePresence: ComponentFunc<{ id: string; userId: string; }> = (initialVnode) => {

  // Shows an icon in grey or green depending on whether a given user
  // is online or not

  var online = false;
  var id = initialVnode.attrs.id;
  var userId = initialVnode.attrs.userId;

  function _update() {
    m.request({
      method: "POST",
      url: "/onlinecheck",
      body: { user: userId }
    })
    .then((json: any) => { online = json && json.online; });
  }

  return {
    oninit: _update,

    view: (vnode) => {
      return m("span",
        {
          id: id,
          title: online ? "Er álínis" : "Álínis?",
          class: online ? "online" : ""
        }
      );
    }
  };

};

const EloPage: ComponentFunc<{ model: Model; view: View; id: string; key: string; }> = (initialVnode) => {

  // Show the header of an Elo ranking list and then the list itself

  let sel = "human"; // Default: show ranking for human games only

  return {
    view: (vnode) => {
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
                    className: (sel == "human" ? "selected" : ""),
                    onclick: () => { sel = "human"; },
                  },
                  glyph("user")
                ),
                m(".option.x-small",
                  {
                    // Show ranking for all games, including robots
                    className: (sel == "all" ? "selected" : ""),
                    onclick: () => { sel = "all"; },
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
            sel: sel,
            model: vnode.attrs.model,
            view: vnode.attrs.view
          }
        )
      ];
    }
  };

};

const EloList: ComponentFunc<{
  view: View;
  model: Model;
  id: string;
  sel: number;
}> = (initialVnode) => {

  return {

    view: (vnode) => {

      function itemize(item, i: number) {

        // Generate a list item about a user in an Elo ranking table

        function rankStr(rank: number, ref?: number): string {
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
              onclick: () => {
                vnode.attrs.view.showUserInfo(item.userid, item.nick, item.fullname);
              }
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
            m("span.list-games.bold", item.games >= 100000 ? Math.round(item.games / 1000) + "K" : item.games),
            m("span.list-ratio", item.ratio + "%"),
            m("span.list-avgpts", item.avgpts),
            m("span.list-info", { title: "Skoða feril" }, info),
            m("span.list-newbag", glyph("shopping-bag", { title: "Gamli pokinn" }, newbag))
          ]
        );
      }

      var model = vnode.attrs.model;
      var list = [];
      if (model.userList === undefined) {
        // Loading in progress
        // pass
      }
      else
      if (model.userList === null || model.userListCriteria.query != "elo" ||
        model.userListCriteria.spec != vnode.attrs.sel.toString()) {
        // We're not showing the correct list: request a new one
        model.loadUserList({ query: "elo", spec: vnode.attrs.sel.toString() }, true);
      }
      else {
        list = model.userList;
      }
      return m("div", { id: vnode.attrs.id }, list.map(itemize));
    }

  };
};

const RecentList: ComponentFunc<{ recentList: any; id: string; }> = (initialVnode) => {
  // Shows a list of recent games, stored in vnode.attrs.recentList
  
  function itemize(item, i: number) {

    // Generate a list item about a recently completed game

    function durationDescription() {
      // Format the game duration
      var duration: string | any[] = "";
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

  return {

    view: (vnode) => {
      let list = vnode.attrs.recentList;
      return m("div", { id: vnode.attrs.id }, !list ? "" : list.map(itemize));
    }

  };
};

const UserInfoDialog: ComponentFunc<{
  model: Model;
  view: View;
  userid: string;
  nick: string;
  fullname: string;
}> = (initialVnode) => {

  // A dialog showing the track record of a given user, including
  // recent games and total statistics

  var stats: { favorite?: boolean; friend?: boolean } = {};
  var recentList = [];
  var versusAll = true; // Show games against all opponents or just the current user?

  function _updateStats(vnode: typeof initialVnode) {
    // Fetch the statistics of the given user
    vnode.attrs.model.loadUserStats(vnode.attrs.userid,
      (json: { result: number; favorite?: boolean; friend?: boolean; }) => {
        if (json && json.result === 0)
          stats = json;
        else
          stats = {};
      }
    );
  }

  function _updateRecentList(vnode: typeof initialVnode) {
    // Fetch the recent game list of the given user
    vnode.attrs.model.loadUserRecentList(vnode.attrs.userid,
      versusAll ? null : $state.userId,
      (json: { result: number; recentlist: any} ) => {
        if (json && json.result === 0)
          recentList = json.recentlist;
        else
          recentList = [];
      }
    );
  }

  function _setVersus(vnode: typeof initialVnode, vsState: boolean) {
    if (versusAll != vsState) {
      versusAll = vsState;
      _updateRecentList(vnode);
    }
  }

  return {

    oninit: (vnode) => {
      _updateRecentList(vnode);
      _updateStats(vnode);
    },

    view: (vnode) => {
      return m(".modal-dialog",
        { id: 'usr-info-dialog', style: { visibility: "visible" } },
        m(".ui-widget.ui-widget-content.ui-corner-all", { id: 'usr-info-form' },
          [
            m(".usr-info-hdr",
              [
                m("h1.usr-info-icon",
                  [stats.friend ? glyph("coffee-cup", { title: 'Friend of Explo' }) : glyph("user"), nbsp()]
                ),
                m("h1[id='usr-info-nick']", vnode.attrs.nick),
                m("span.vbar", "|"),
                m("h2[id='usr-info-fullname']", vnode.attrs.fullname),
                m(".usr-info-fav",
                  {
                    title: 'Uppáhald',
                    onclick: (ev) => {
                      // Toggle the favorite setting
                      stats.favorite = !stats.favorite;
                      vnode.attrs.model.markFavorite(vnode.attrs.userid, stats.favorite);
                      ev.preventDefault();
                    }
                  },
                  stats.favorite ? glyph("star") : glyph("star-empty")
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
                        class: versusAll ? "shown" : "",
                        onclick: () => { _setVersus(vnode, true); } // Set this.versusAll to true
                      },
                      " gegn öllum "
                    ),
                    m("span",
                      {
                        class: versusAll ? "" : "shown",
                        onclick: () => { _setVersus(vnode, false); } // Set this.versusAll to false
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
            m(RecentList, { id: 'usr-recent', recentList: recentList }), // Recent game list
            m(StatsDisplay, { id: 'usr-stats', ownStats: stats }),
            m(BestDisplay, { id: 'usr-best', ownStats: stats, myself: false }), // Highest word and game scores
            m(DialogButton,
              {
                id: 'usr-info-close',
                title: 'Loka',
                onclick: () => { vnode.attrs.view.popDialog(); }
              },
              glyph("ok")
            )
          ]
        )
      );
    }
  };

}

const BestDisplay: ComponentFunc<{ ownStats: any; myself: boolean; id: string; }> = (initialVnode) => {
  // Display the best words and best games played for a given user

  return {

    view: (vnode) => {
      // Populate the highest score/best word field
      let json = vnode.attrs.ownStats || { };
      let best = [];
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
        let bw = json.best_word;
        let s = [];
        // Make sure blank tiles get a different color
        for (let i = 0; i < bw.length; i++)
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
}

const StatsDisplay: ComponentFunc<{ ownStats: any; id: string; }> = (initialVnode) => {
  // Display key statistics, provided via the ownStats attribute

  let sel = 1;

  return {

    view: (vnode) => {

      function vwStat(val: number, icon?: string, suffix?: string): string | any[] {
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
              m(".option.small" + (sel == 1 ? ".selected" : ""),
                { id: 'opt1', onclick: (ev) => { sel = 1; ev.preventDefault(); } },
                glyph("user")
              ),
              m(".option.small" + (sel == 2 ? ".selected" : ""),
                { id: 'opt2', onclick: (ev) => { sel = 2; ev.preventDefault(); } },
                glyph("cog")
              )
            ]
          ),
          sel == 1 ? m("div",
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
          sel == 2 ? m("div",
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
};

const PromoDialog: ComponentFunc<{
  model: Model;
  view: View;
  kind: string;
  initFunc: () => void;
}> = (initialVnode) => {

  // A dialog showing promotional content fetched from the server

  let html = "";

  function _fetchContent(vnode: typeof initialVnode) {
    // Fetch the content
    vnode.attrs.model.loadPromoContent(
      vnode.attrs.kind, (contentHtml) => { html = contentHtml; }
    );
  }

  function _onUpdate(vnode: Vnode, view: View, initFunc: () => void) {
    var noButtons = vnode.dom.getElementsByClassName("btn-promo-no") as HTMLCollectionOf<HTMLElement>;
    // Override onclick, onmouseover and onmouseout for No buttons
    for (let i = 0; i < noButtons.length; i++) {
      noButtons[i].onclick = () => view.popDialog();
      noButtons[i].onmouseover = buttonOver;
      noButtons[i].onmouseout = buttonOut;
    }
    // Override onmouseover and onmouseout for Yes buttons
    var yesButtons = vnode.dom.getElementsByClassName("btn-promo-yes") as HTMLCollectionOf<HTMLElement>;
    for (let i = 0; i < yesButtons.length; i++) {
      yesButtons[i].onmouseover = buttonOver;
      yesButtons[i].onmouseout = buttonOut;
    }
    // Run an initialization function, if specified
    if (initFunc !== undefined)
      initFunc();
  }

  return {

    oninit: _fetchContent,

    view: (vnode) => {
      let view = vnode.attrs.view;
      let initFunc = vnode.attrs.initFunc;
      return m(".modal-dialog",
        { id: "promo-dialog", style: { visibility: "visible" } },
        m(".ui-widget.ui-widget-content.ui-corner-all",
          { id: "promo-form", className: "promo-" + vnode.attrs.kind },
          m("div",
            {
              id: "promo-content",
              onupdate: (vnode) => _onUpdate(vnode, view, initFunc)
            },
            m.trust(html)
          )
        )
      );
    }
  };

};

const SearchButton: ComponentFunc<{ model: Model; }> = (initialVnode) => {

  // A combination of a button and pattern entry field
  // for user search

  let spec = ""; // The current search pattern
  let model = initialVnode.attrs.model;
  let promise;

  function newSearch() {
    // There may have been a change of search parameters: react
    if (promise !== undefined) {
      // There was a previous promise, now obsolete: make it
      // resolve without action
      promise.result = false;
      promise = undefined;
    }
    let sel = model.userListCriteria ? model.userListCriteria.query : "robots";
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
    let newP = {
      result: true,
      p: new Promise((resolve) => {
        // After 800 milliseconds, resolve to whatever value the
        // result property has at that time. It will be true
        // unless the promise has been "cancelled" by setting
        // its result property to false.
        setTimeout(() => { resolve(newP.result); }, 800);
      })
    };
    promise = newP;
    promise.p.then((value: boolean) => {
      if (value) {
        // Successfully resolved, without cancellation:
        // issue the search query to the server as it now stands
        model.loadUserList({ query: "search", spec: spec }, true);
        promise = undefined;
      }
    });
  }

  return {

    view: (vnode) => {
      let sel = model.userListCriteria ? model.userListCriteria.query : "robots";
      return m(".user-cat[id='user-search']",
        [
          glyph("search",
            {
              id: 'search',
              className: (sel == "search" ? "shown" : ""),
              onclick: () => {
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
              onfocus: () => newSearch(),
              oninput: (ev) => {
                spec = (ev.target as HTMLInputElement).value + "";
                newSearch();
              }
            }
          )
        ]
      );
    }
  };
};

const DialogButton: ComponentFunc<{}> = (initialVnode) => {
  return {
    view: (vnode) => {
      let attrs: VnodeAttrs = {
        onmouseout: buttonOut,
        onmouseover: buttonOver
      };
      for (let a in vnode.attrs)
        if (vnode.attrs.hasOwnProperty(a))
          attrs[a] = vnode.attrs[a];
      return m(".modal-close", attrs, vnode.children);
    }
  };
};

// Utility functions

function escapeHtml(string: string): string {
   /* Utility function to properly encode a string into HTML */
  const entityMap = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': '&quot;',
    "'": '&#39;',
    "/": '&#x2F;'
  };
  return String(string).replace(/[&<>"'/]/g, (s) => entityMap[s]);
}

function replaceEmoticons(str: string): string {
  // Replace all emoticon shortcuts in the string str with a corresponding image URL
  let emoticons = $state.emoticons;
  for (let i = 0; i < emoticons.length; i++)
    if (str.indexOf(emoticons[i].icon) >= 0) {
      // The string contains the emoticon: prepare to replace all occurrences
      let img = "<img src='" + emoticons[i].image + "' height='32' width='32'>";
      // Re the following trick, see https://stackoverflow.com/questions/1144783/
      // replacing-all-occurrences-of-a-string-in-javascript
      str = str.split(emoticons[i].icon).join(img);
    }
  return str;
}

function getInput(id: string): string {
  // Return the current value of a text input field
  const elem = document.getElementById(id) as HTMLInputElement;
  return elem.value;
}

function setInput(id: string, val: string) {
  // Set the current value of a text input field
  const elem = document.getElementById(id) as HTMLInputElement;
  elem.value = val;
}

// Utility functions to set up tabbed views

function updateTabVisibility(vnode: Vnode) {
  // Shows the tab that is currently selected,
  // i.e. the one whose index is in vnode.state.selected
  var selected: number = vnode.state.selected;
  var lis = vnode.state.lis;
  vnode.state.ids.map((id: string, i: number) => {
      document.getElementById(id).setAttribute("style", "display: " +
        (i == selected ? "block" : "none"));
      lis[i].classList.toggle("ui-tabs-active", i == selected);
      lis[i].classList.toggle("ui-state-active", i == selected);
    }
  );
}

function selectTab(vnode: Vnode, i: number) {
  // Selects the tab with the given index under the tab control vnode
  vnode.state.selected = i;
  updateTabVisibility(vnode);
}

function updateSelection(vnode: Vnode) {
  // Select a tab according to the ?tab= query parameter in the current route
  var tab = m.route.param("tab");
  if (tab !== undefined)
    selectTab(vnode, parseInt(tab) || 0);
}

// Get values from a URL query string
function getUrlVars(url: string) {
   let hashes = url.split('&');
   let vars: Params = { };
   for (let i = 0; i < hashes.length; i++) {
      let hash = hashes[i].split('=');
      if (hash.length == 2)
        vars[hash[0]] = decodeURIComponent(hash[1]);
   }
   return vars;
}

function buttonOver(ev: Event) {
  const clist = (ev.currentTarget as HTMLElement).classList;
  if (clist !== undefined && !clist.contains("disabled"))
    clist.add("over");
  (ev as MithrilEvent).redraw = false;
}

function buttonOut(ev: Event) {
  const clist = (ev.currentTarget as HTMLElement).classList;
  if (clist !== undefined)
    clist.remove("over");
  (ev as MithrilEvent).redraw = false;
}

function stopPropagation(ev: Event) {
  ev.stopPropagation();
}

// Glyphicon utility function: inserts a glyphicon span
function glyph(icon: string, attrs?: object, grayed?: boolean) {
  return m("span.glyphicon.glyphicon-" + icon + (grayed ? ".grayed" : ""), attrs);
}

function glyphGrayed(icon: string, attrs?: object) {
  return m("span.glyphicon.glyphicon-" + icon + ".grayed", attrs);
}

// Utility function: inserts non-breaking space
function nbsp(n?: number) {
  if (!n || n == 1)
    return m.trust("&nbsp;");
  var r = [];
  for (let i = 0; i < n; i++)
    r.push(m.trust("&nbsp;"));
  return r;
}
