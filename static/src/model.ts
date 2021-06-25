/*

  Model.ts

  Single page UI for Explo using the Mithril library

  Copyright (C) 2021 Miðeind ehf.
  Author: Vilhjálmur Þorsteinsson

  The GNU Affero General Public License, version 3, applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

  This file implements the Model class and related global state.
  A Model encapsulates the data, including the Game instance,
  that is being displayed live by the current view.

*/

export {
  Model, GlobalState, getSettings,
  UserListItem, ChallengeListItem, RecentListItem,
  ChallengeAction, MoveInfo, Params
};

import { Game, ServerGame, Move, RackTile  } from "./game.js";

import { m } from "./mithril.js";

// Maximum number of concurrent games per user
const MAX_GAMES = 50;
// Maximum number of concurrent games for non-paying users
const MAX_FREE_GAMES = 8; // !!! FIXME: Lower number for Explo

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

// Items in a list of recent games
interface RecentListItem {
  opp: string;
  opp_is_robot: boolean;
  sc0: number;
  sc1: number;
  ts_last_move: string;
  manual: boolean;
  duration: number;
  days: number;
  hours: number;
  minutes: number;
  elo_adj: number;
  human_elo_adj: number;
  url: string;
}

// Items in a list of challenges (sent or received)
interface ChallengeListItem {
  key: string;
  received: boolean;
  userid: string;
  opp: string;
  fullname: string;
  prefs: any;
  ts: string;
  opp_ready: boolean;
  live: boolean;
  image: string;
  fav: boolean;
}

type ChallengeAction = "issue" | "retract" | "decline" | "accept";

interface ChallengeParameters {
  action: ChallengeAction;
  destuser: string;
  duration?: number;
  fairplay?: boolean;
  newbag?: boolean;
  manual?: boolean;
  key?: string;
}

// Items in a list of users
interface UserListItem {
  rank: number;
  rank_yesterday: number;
  rank_week_ago: number;
  userid: string;
  nick: string;
  fullname: string;
  newbag: boolean;
  inactive: boolean;
  chall: boolean;
  fairplay: boolean;
  ready: boolean;
  ready_timed: boolean;
  fav: boolean;
  ratio: number;
  avgpts: number;
  games: number;
  games_yesterday: number;
  games_week_ago: number;
  games_month_ago: number;
  elo: number;
  human_elo: number;
  elo_yesterday: number;
  elo_week_ago: number;
  elo_month_ago: number;
}

interface UserErrors {
  nickname?: string;
  full_name?: string;
  email?: string;
}

// User preferences, typically edited in a modal dialog
interface UserPrefs {
  nickname: string;
  full_name: string;
  email: string;
  beginner: boolean;
  fairplay: boolean;
  newbag: boolean;
  audio: boolean;
  fanfare: boolean;
  logout_url: string;
  unfriend_url: string;
  friend: boolean;
}

// Information about a move in a move list
interface MoveInfo {
  key: string;
  leftTotal: number;
  rightTotal: number;
  player: 0 | 1;
  co: string;
  tiles: string;
  score: number;
}

// Global state, for the most part obtained from the server
// when the single page UI is initialized (i.e. from page.html)
interface GlobalState {
  userId: string;
  userNick: string;
  userFullname: string;
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

function getSettings(): Settings {
  // Returns an app-wide settings object, used by Mithril for routing
  const
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

  // A class for the underlying data model, displayed by the current view

  state: GlobalState = null;
  paths: Paths = [];
  // The routeName will be "login", "main", "game"...
  routeName?: string = undefined;
  // Eventual parameters within the route URL, such as the game uuid
  params?: Params = undefined;
  // The current game being displayed, if any
  game: Game = null;
  // The current game list
  gameList: GameListItem[] = null;
  loadingGameList = false;
  // The current challenge list
  challengeList: ChallengeListItem[] = null;
  loadingChallengeList = false;
  // Number of opponents who are ready and waiting for a timed game
  oppReady = 0;
  // Recent games
  recentList: RecentListItem[] = null;
  loadingRecentList = false;
  // The currently displayed user list
  userListCriteria: { query: string; spec: string; } = null;
  userList: UserListItem[] = null;
  loadingUserList = false;
  // The user's own statistics
  ownStats: any = null;
  // The current user information being edited, if any
  user: UserPrefs = null;
  userErrors: UserErrors = null;
  // The (cached) help screen contents
  helpHTML: string = null;
  // Outstanding server requests
  spinners: number = 0;
  // The index of the game move being reviewed, if any
  reviewMove: number = null;
  // The best moves available at this stage, if reviewing game
  bestMoves: Move[] = null;
  // The index of the best move being highlighted, if reviewing game
  highlightedMove: number = null;

  constructor(settings: Settings, state: GlobalState) {
    this.paths = settings.paths.slice();
    this.state = state;
  }

  loadGame(uuid: string, funcComplete: () => void) {
    // Fetch a game state from the server, given the game's UUID
    m.request({
      method: "POST",
      url: "/gamestate",
      body: { game: uuid }
    })
    .then((result: { ok: boolean; game: ServerGame; }) => {
      if (this.game !== null)
        // We have a prior game in memory:
        // clean it up before allocating the new one
        this.game.cleanup();
      this.game = null;
      this.reviewMove = null;
      this.bestMoves = null;
      this.highlightedMove = null;
      if (!result.ok) {
        // console.log("Game " + uuid + " could not be loaded");
      }
      else {
        // Create a new game instance and load the state into it
        this.game = new Game(uuid, result.game);
        // Successfully loaded: call the completion function, if given
        // (this usually attaches the Firebase event listener)
        if (funcComplete !== undefined)
          funcComplete();
        if (!this.state.uiFullscreen)
          // Mobile UI: show board tab
          this.game.setSelectedTab("board");
      }
    });
  }

  loadGameList(includeZombies: boolean = true) {
    // Load the list of currently active games for this user
    if (this.loadingGameList)
      // Already loading
      return;
    this.loadingGameList = true; // Loading in progress
    this.gameList = [];
    this.spinners++;
    m.request({
      method: "POST",
      url: "/gamelist",
      body: { zombie: includeZombies }
    })
    .then((json: { result: number; gamelist: GameListItem[]; }) => {
      if (this.spinners)
        this.spinners--;
      if (!json || json.result !== 0) {
        // An error occurred
        this.gameList = null;
        this.loadingGameList = false;
        return;
      }
      this.gameList = json.gamelist || [];
      this.loadingGameList = false;
    })
    .catch(() => {
      this.loadingGameList = false;
      if (this.spinners)
        this.spinners--;
    });
  }

  loadChallengeList() {
    // Load the list of current challenges (received and issued)
    if (this.loadingChallengeList)
      return;
    this.loadingChallengeList = true;
    this.challengeList = [];
    m.request({
      method: "POST",
      url: "/challengelist"
    })
    .then((json: { result: number; challengelist: ChallengeListItem[]; }) => {
      if (!json || json.result !== 0) {
        // An error occurred
        this.challengeList = null;
        this.loadingChallengeList = false;
        return;
      }
      this.challengeList = json.challengelist || [];
      this.loadingChallengeList = false;
      // Count opponents who are ready and waiting for timed games
      this.oppReady = 0;
      for (let ch of this.challengeList) {
        if (ch.opp_ready)
          this.oppReady++;
      }
    })
    .catch(() => { this.loadingChallengeList = false; });
  }

  loadRecentList() {
    // Load the list of recent games for this user
    if (this.loadingRecentList)
      return;
    this.loadingRecentList = true; // Prevent concurrent loading
    this.recentList = [];
    m.request({
      method: "POST",
      url: "/recentlist",
      body: { versus: null, count: 40 }
    })
    .then((json: { result: number; recentlist: RecentListItem[]; }) => {
      if (!json || json.result !== 0) {
        // An error occurred
        this.recentList = null;
        this.loadingRecentList = false;
        return;
      }
      this.recentList = json.recentlist || [];
      this.loadingRecentList = false;
    })
    .catch(() => { this.loadingRecentList = false; });
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
      if (activateSpinner && this.spinners)
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
    })
    .catch(() => {
      if (activateSpinner && this.spinners)
        // Remove spinner overlay, if present
        this.spinners--;
    });
  }

  loadOwnStats() {
    // Load statistics for the current user
    this.ownStats = {};
    m.request({
      method: "POST",
      url: "/userstats",
      body: {} // Current user is implicit
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

  loadBestMoves(moveIndex: number) {
    // Load the best moves available at a given state in a game
    if (!this.game || !this.game.uuid)
      return;
      if (!moveIndex) {
        // No moves to load, but display summary
        this.reviewMove = 0;
        this.bestMoves = null;
        this.highlightedMove = null;
        this.game.setRack([]);
        this.game.placeTiles(0);
        return;
      }
    // Don't display navigation buttons while fetching best moves
    this.reviewMove = null;
    m.request({
      method: "POST",
      url: "/bestmoves",
      body: { game: this.game.uuid, move: moveIndex }
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
      // laid down up and until the indicated moveIndex
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
    .then((result: { ok: boolean; userprefs: UserPrefs; }) => {
      if (activateSpinner && this.spinners)
        this.spinners--;
      if (!result.ok) {
        this.user = null;
        this.userErrors = null;
      }
      else {
        this.user = result.userprefs;
        this.userErrors = null;
      }
    })
    .catch(() => {
      if (activateSpinner && this.spinners)
        this.spinners--;
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
        const state = this.state;
        const user = this.user;
        state.userNick = user.nickname;
        state.beginner = user.beginner;
        state.fairPlay = user.fairplay;
        state.newBag = user.newbag;
        // Give the game instance a chance to update its state
        if (this.game !== null)
          this.game.notifyUserChange(user.nickname);
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
    ).then(() => { }); // No result required or expected
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

  modifyChallenge(parameters: ChallengeParameters) {
    // Reject or retract a challenge
    m.request({
      method: "POST",
      url: "/challenge",
      body: parameters
    })
    .then((json: { result: number; }) => {
      if (json.result === 0) {
        this.loadChallengeList();
        if (this.userListCriteria)
          // We are showing a user list: reload it
          this.loadUserList(this.userListCriteria, false);
      }
    });
  }

  markFavorite(userId: string, status: boolean) {
    // Mark or de-mark a user as a favorite
    m.request({
      method: "POST",
      url: "/favorite",
      body: { destuser: userId, action: status ? "add" : "delete" }
    })
    .then(() => { });
  }

  addChatMessage(game: string, from_userid: string, msg: string, ts: string): boolean {
    // Add a chat message to the game's chat message list
    if (this.game && this.game.uuid == game) {
      this.game.addChatMessage(from_userid, msg, ts, from_userid == this.state.userId);
      // Returning true triggers a redraw
      return true;
    }
    return false;
  }

  handleUserMessage(json: any) {
    // Handle an incoming Firebase user message
    if (json.challenge) {
      // Reload challenge list
      this.loadChallengeList();
      if (this.userListCriteria)
        // We are showing a user list: reload it
        this.loadUserList(this.userListCriteria, false);
      // Reload game list
      this.loadGameList();
    }
  }

  handleMoveMessage(json: ServerGame) {
    // Handle an incoming Firebase move message
    if (this.game) {
      this.game.update(json);
      m.redraw();
    }
  }

  moreGamesAllowed(): boolean {
    // Return true if the user is allowed to have more games ongoing
    if (this.loadingGameList)
      return false;
    if (!this.gameList)
      return true;
    const numGames = this.gameList.length;
    if (numGames >= MAX_GAMES)
      return false;
    if (this.state.hasPaid)
      return true;
    return this.gameList.length < MAX_FREE_GAMES;
  }

} // class Model

