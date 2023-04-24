/*

  Model.ts

  Single page UI for Explo using the Mithril library

  Copyright (C) 2023 Miðeind ehf.
  Author: Vilhjálmur Þorsteinsson

  The Creative Commons Attribution-NonCommercial 4.0
  International Public License (CC-BY-NC 4.0) applies to this software.
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

import { Game, ServerGame, Move, RackTile, MAX_OVERTIME, DEBUG_OVERTIME } from "game";

import { m, RequestArgs } from "mithril";
import { logEvent } from "channel";
import { loadMessages } from "i18n";

// Maximum number of concurrent games per user
const MAX_GAMES = 50;
// Maximum number of concurrent games for non-paying users
const MAX_FREE_EXPLO = 3;
const MAX_FREE_NETSKRAFL = 8;

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
  zombie?: string;
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
  audio: boolean;
  fanfare: boolean;
  logout_url: string;
  // The following is currently read-only, i.e. only displayed
  // and not directly modified in the user preferences dialog
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
  locale: string;
  isExplo: boolean;
  loginMethod: string;
  newUser: boolean;
  beginner: boolean;
  fairPlay: boolean;
  plan: string;
  hasPaid: boolean;
  ready: boolean;
  readyTimed: boolean;
  uiFullscreen: boolean;
  uiLandscape: boolean;
  firebaseToken: string;
  emoticons: { icon: string; image: string; }[];
  runningLocal: boolean;
}

function getSettings(): Settings {
  // Returns an app-wide settings object, used by Mithril for routing
  const
    paths: Paths = [
      { name: "main", route: "/main", mustLogin: true },
      { name: "help", route: "/help", mustLogin: false },
      { name: "thanks", route: "/thanks", mustLogin: true },
      { name: "cancel", route: "/cancel", mustLogin: true },
      { name: "confirm", route: "/confirm", mustLogin: true },
      { name: "game", route: "/game/:uuid", mustLogin: true },
      { name: "review", route: "/review/:uuid", mustLogin: true },
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
  // Number of games where it's the player's turn, plus count of zombie games
  numGames = 0;
  loadingGameList = false;
  // The current challenge list
  challengeList: ChallengeListItem[] = null;
  // Sum up received challenges and issued timed challenges where the opponent is ready
  numChallenges = 0;
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
  // The (cached) friend promo screen contents
  friendHTML: string = null;
  // Outstanding server requests
  spinners: number = 0;
  // The index of the game move being reviewed, if any
  reviewMove: number = null;
  // The best moves available at this stage, if reviewing game
  bestMoves: Move[] = null;
  // The index of the best move being highlighted, if reviewing game
  highlightedMove: number = null;
  // Maximum number of free games allowed concurrently
  maxFreeGames = 0;

  constructor(settings: Settings, state: GlobalState) {
    this.paths = settings.paths.slice();
    this.state = state;
    this.maxFreeGames = state.isExplo ? MAX_FREE_EXPLO : MAX_FREE_NETSKRAFL;
    // Load localized text messages from the messages.json file
    loadMessages(state.locale);
  }

  async loadGame(uuid: string, funcComplete: () => void, deleteZombie: boolean = false) {
    // Fetch a game state from the server, given the game's UUID.
    // If deleteZombie is true, we are loading a zombie game for
    // inspection, so we tell the server to remove the zombie marker.
    try {
      const result: { ok: boolean; game: ServerGame; } = await m.request({
        method: "POST",
        url: "/gamestate",
        body: {
          game: uuid,
          delete_zombie: deleteZombie
        }
      });
      if (this.game !== null)
        // We have a prior game in memory:
        // clean it up before allocating the new one
        this.game.cleanup();
      this.game = null;
      this.reviewMove = null;
      this.bestMoves = null;
      this.highlightedMove = null;
      if (!result?.ok) {
        // console.log("Game " + uuid + " could not be loaded");
      }
      else {
        // Create a new game instance and load the state into it
        this.game = new Game(uuid, result.game, this, this.state.runningLocal ? DEBUG_OVERTIME : MAX_OVERTIME);
        // Successfully loaded: call the completion function, if given
        // (this usually attaches the Firebase event listener)
        if (funcComplete !== undefined)
          funcComplete();
        if (!this.state.uiFullscreen)
          // Mobile UI: show board tab
          this.game.setSelectedTab("board");
      }
    } catch(e) {
      // If new game cannot be loaded, keep the old one in place
    }
  }

  async loadGameList(includeZombies: boolean = true) {
    // Load the list of currently active games for this user
    if (this.loadingGameList)
      // Already loading
      return;
    this.loadingGameList = true; // Loading in progress
    this.gameList = [];
    this.numGames = 0;
    this.spinners++;
    try {
      const json: { result: number; gamelist: GameListItem[]; } = await m.request({
        method: "POST",
        url: "/gamelist",
        body: { zombie: includeZombies }
      });
      if (!json || json.result !== 0) {
        // An error occurred
        this.gameList = null;
        return;
      }
      this.gameList = json.gamelist || [];
      if (this.gameList)
        // Sum up games where it's the player's turn, as well as zombie games
        this.numGames = this.gameList.reduce(
          (acc, item) => acc + (item.my_turn || item.zombie ? 1 : 0), 0
        );
    } catch(e) {
      this.gameList = null;
    } finally {
      this.loadingGameList = false;
      if (this.spinners)
        this.spinners--;
    }
  }

  async loadChallengeList() {
    // Load the list of current challenges (received and issued)
    if (this.loadingChallengeList)
      return;
    this.loadingChallengeList = true;
    this.challengeList = [];
    this.numChallenges = 0;
    this.oppReady = 0;
    try {
      const json: { result: number; challengelist: ChallengeListItem[]; } = await m.request({
        method: "POST",
        url: "/challengelist"
      });
      if (!json || json.result !== 0) {
        // An error occurred
        this.challengeList = null;
        return;
      }
      this.challengeList = json.challengelist || [];
      // Count opponents who are ready and waiting for timed games
      for (let ch of this.challengeList) {
        if (ch.opp_ready)
          this.oppReady++;
      }
      this.numChallenges = this.oppReady;
      if (this.challengeList)
        // Sum up received challenges and issued timed challenges where
        // the opponent is ready
        this.numChallenges += this.challengeList.reduce(
          (acc, item) => acc + (item.received ? 1 : 0), 0
        );
    } catch(e) {
      this.challengeList = null;
    } finally {
      this.loadingChallengeList = false;
    }
  }

  async loadRecentList() {
    // Load the list of recent games for this user
    if (this.loadingRecentList)
      return;
    this.loadingRecentList = true; // Prevent concurrent loading
    this.recentList = [];
    try {
      const json: { result: number; recentlist: RecentListItem[]; } = await m.request({
        method: "POST",
        url: "/recentlist",
        body: { versus: null, count: 40 }
      });
      if (!json || json.result !== 0) {
        // An error occurred
        this.recentList = null;
        return;
      }
      this.recentList = json.recentlist || [];
    } catch(e) {
      this.recentList = null;
    } finally {
      this.loadingRecentList = false;
    }
  }

  async loadUserRecentList(userid: string, versus: string, readyFunc: (json: any) => void) {
    // Load the list of recent games for the given user
    const json: any = await m.request({
      method: "POST",
      url: "/recentlist",
      body: { user: userid, versus: versus, count: 40 }
    });
    readyFunc(json);
  }

  async loadUserList(
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
    if (activateSpinner) {
      // This will show a spinner overlay, disabling clicks on
      // all underlying controls
      this.spinners++;
    }
    let url = "/userlist";
    let data: { query?: string; spec?: string; kind?: string; } = criteria;
    if (criteria.query == "elo") {
      // Kludge to make the Elo rating list appear as
      // just another type of user list
      url = "/rating";
      data = { kind: criteria.spec };
    }
    try {
      const json: { result: number; userlist: any; rating: any; } = await m.request({
        method: "POST",
        url: url,
        body: data
      });
      if (!json || json.result !== 0) {
        // An error occurred
        this.userList = null;
        this.userListCriteria = null;
        return;
      }
      this.userList = json.userlist || json.rating;
      this.userListCriteria = criteria;
    } catch(e) {
      this.userList = null;
      this.userListCriteria = null;
    } finally {
      if (activateSpinner && this.spinners)
        // Remove spinner overlay, if present
        this.spinners--;
    }
  }

  async loadOwnStats() {
    // Load statistics for the current user
    this.ownStats = {};
    try {
      const json: { result: number; } = await m.request({
        method: "POST",
        url: "/userstats",
        body: {} // Current user is implicit
      });
      if (!json || json.result !== 0) {
        // An error occurred
        this.ownStats = null;
        return;
      }
      this.ownStats = json;
    } catch(e) {
      this.ownStats = null;
    }
  }

  async loadUserStats(userid: string, readyFunc: (json: any) => void) {
    // Load statistics for the given user
    try {
      const json: any = await m.request({
        method: "POST",
        url: "/userstats",
        body: { user: userid }
      });
      readyFunc(json);
    } catch(e) {
      // No need to do anything
    }
  }

  async loadPromoContent(key: string, readyFunc: (html: string) => void) {
    // Load HTML content for promo dialog
    try {
      const html: string = await m.request({
        method: "POST",
        url: "/promo",
        body: { key: key },
        responseType: "text",
        deserialize: (str: string) => str
      });
      readyFunc(html);
    } catch(e) {
      // No need to do anything
    }
  }

  async loadBestMoves(moveIndex: number) {
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
    // ...but do display a spinner, if this takes too long
    this.spinners++;
    try {
      type BestMoves = {
        result: number;
        move_number: number;
        best_moves: Move[];
        player_rack: RackTile[];
      };
      const json: BestMoves = await m.request({
        method: "POST",
        url: "/bestmoves",
        body: { game: this.game.uuid, move: moveIndex }
      });
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
    } catch(e) {
      this.highlightedMove = null;
      this.reviewMove = null;
      this.bestMoves = null;
    } finally {
      if (this.spinners)
        this.spinners--;
    }
  }

  async loadHelp() {
    // Load the help screen HTML from the server
    // (this is done the first time the help is displayed)
    if (this.helpHTML !== null)
      return; // Already loaded
    try {
      const result: string = await m.request({
        method: "GET",
        url: "/rawhelp?locale=" + this.state.locale,
        responseType: "text",
        deserialize: (str: string) => str
      });
      this.helpHTML = result;
    } catch(e) {
      this.helpHTML = "";
    }
  }

  async loadFriendPromo() {
    // Load the friend promo HTML from the server
    // (this is done the first time the dialog is displayed)
    if (this.friendHTML !== null)
      return; // Already loaded
    try {
      const result: string = await m.request({
        method: "GET",
        url: "/friend?locale=" + this.state.locale,
        responseType: "text",
        deserialize: (str: string) => str
      });
      this.friendHTML = result;
    } catch(e) {
      this.friendHTML = "";
    }
  }

  async loadUser(activateSpinner: boolean) {
    // Fetch the preferences of the currently logged in user, if any
    this.user = undefined;
    if (activateSpinner) {
      // This will show a spinner overlay, disabling clicks on
      // all underlying controls
      this.spinners++;
    }
    try {
      const result: { ok: boolean; userprefs: UserPrefs; } = await m.request({
        method: "POST",
        url: "/loaduserprefs"
      });
      if (!result || !result.ok) {
        this.user = null;
        this.userErrors = null;
      }
      else {
        this.user = result.userprefs;
        this.userErrors = null;
      }
    } catch(e) {
      this.user = null;
      this.userErrors = null;
    } finally {
      if (activateSpinner && this.spinners)
        this.spinners--;
    }
  }

  async saveUser(successFunc: () => void) {
    // Update the preferences of the currently logged in user, if any
    try {
      const result: { ok: boolean; err?: UserErrors; } = await m.request({
        method: "POST",
        url: "/saveuserprefs",
        body: this.user
      });
      if (result?.ok) {
        // User preferences modified successfully on the server:
        // update the state variables that we're caching
        const state = this.state;
        const user = this.user;
        state.userNick = user.nickname;
        state.beginner = user.beginner;
        state.fairPlay = user.fairplay;
        // Note that state.plan is updated via a Firebase notification
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
    } catch(e) {
      this.userErrors = null;
    }
  }

  async setUserPref(pref: object) {
    // Set a user preference
    try {
      await m.request(
        {
          method: "POST",
          url: "/setuserpref",
          body: pref
        }
      ); // No result required or expected
    } catch (e) {
      // A future TODO might be to signal an error in the UI
    }
  }

  async newGame(oppid: string, reverse: boolean) {
    // Ask the server to initiate a new game against the given opponent
    try {
      var rqBody: {
        opp: string;
        rev: boolean;
        board_type?: string
      } = { opp: oppid, rev: reverse };
      if (this.state.isExplo) {
        // On an Explo client, always use the Explo board,
        // regardless of the user's locale setting
        rqBody.board_type = "explo";
      }
      const rq: RequestArgs = {
        method: "POST",
        url: "/initgame",
        body: rqBody
      };
      const json: { ok: boolean; uuid: string; } = await m.request(rq);
      if (json?.ok) {
        // Log the new game event
        logEvent("new_game",
          {
            uuid: json.uuid,
            timed: reverse,
            locale: this.state.locale
          }
        );
        // Go to the newly created game
        m.route.set("/game/" + json.uuid);
      }
    } catch(e) {
      // No need to do anything
    }
  }

  async modifyChallenge(parameters: ChallengeParameters) {
    // Reject or retract a challenge
    try {
      const json: { result: number; } = await m.request({
        method: "POST",
        url: "/challenge",
        body: parameters
      });
      if (json?.result === 0) {
        // Log the change of challenge status (issue/decline/retract/accept)
        var p: any = { locale: this.state.locale };
        if (parameters.duration !== undefined)
          p.duration = parameters.duration;
        if (parameters.fairplay !== undefined)
          p.fairplay = parameters.fairplay;
        if (parameters.manual !== undefined)
          p.manual = parameters.manual;
        logEvent("challenge_" + parameters.action, p);
        // Reload list of challenges from server
        this.loadChallengeList();
        if (this.userListCriteria)
          // We are showing a user list: reload it
          this.loadUserList(this.userListCriteria, false);
      }
    } catch(e) {
      // A future TODO is to indicate an error in the UI
    }
  }

  async markFavorite(userId: string, status: boolean) {
    // Mark or de-mark a user as a favorite
    try {
      await m.request({
        method: "POST",
        url: "/favorite",
        body: { destuser: userId, action: status ? "add" : "delete" }
      });
    } catch(e) {
      // No need to do anything here - a future TODO is to indicate an error in the UI
    }
  }

  async cancelFriendship() {
    // Cancel the current user as a friend
    try {
      const json: { ok: boolean; } = await m.request({
        method: "POST",
        url: "/cancelplan",
        body: { }
      });
      if (json?.ok) {
        // Successfully cancelled: immediately update the friend and hasPaid state
        this.user.friend = false;
        this.state.hasPaid = false;
        this.state.plan = "";
        // Log a friendship cancellation event
        logEvent("cancel_plan",
          {
            userid: this.state.userId,
            locale: this.state.locale,
            // Add plan identifiers here
            plan: "friend"
          }
        );
        return true;
      }
    } catch(e) {
      // No need to do anything here - a future TODO is to indicate an error in the UI
    }
    return false;
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

  handleUserMessage(json: any, firstAttach: boolean) {
    // Handle an incoming Firebase user message, i.e. a message
    // on the /user/[userid] path
    if (firstAttach)
      return;
    let redraw = false;
    if (json.friend !== undefined) {
      // Potential change of user friendship status
      const newFriend = json.friend ? true : false;
      if (this.user && this.user.friend != newFriend) {
        this.user.friend = newFriend;
        redraw = true;
      }
    }
    if (json.plan !== undefined) {
      // Potential change of user subscription plan
      if (this.state.plan != json.plan) {
        this.state.plan = json.plan;
        redraw = true;
      }
      if (this.user && !this.user.friend && this.state.plan == "friend") {
        // plan == "friend" implies that user.friend should be true
        this.user.friend = true;
        redraw = true;
      }
      if (this.state.plan == "" && this.user?.friend) {
        // Conversely, an empty plan string means that the user is not a friend
        this.user.friend = false;
        redraw = true;
      }
    }
    if (json.hasPaid !== undefined) {
      // Potential change of payment status
      const newHasPaid = (this.state.plan != "" && json.hasPaid) ? true : false;
      if (this.state.hasPaid != newHasPaid) {
        this.state.hasPaid = newHasPaid;
        redraw = true;
      }
    }
    let invalidateGameList = false;
    // The following code is a bit iffy since both json.challenge and json.move
    // are included in the same message on the /user/[userid] path.
    // !!! FIXME: Split this into two separate listeners,
    // !!! one for challenges and one for moves
    if (json.challenge) {
      // Reload challenge list
      this.loadChallengeList();
      if (this.userListCriteria)
        // We are showing a user list: reload it
        this.loadUserList(this.userListCriteria, false);
      // Reload game list
      // !!! FIXME: It is strictly speaking not necessary to reload
      // !!! the game list unless this is an acceptance of a challenge
      // !!! (issuance or rejection don't cause the game list to change)
      invalidateGameList = true;
    } else if (json.move) {
      // A move has been made in one of this user's games:
      // invalidate the game list (will be loaded upon next display)
      invalidateGameList = true;
    }
    if (invalidateGameList && !this.loadingGameList) {
      this.gameList = null;
      redraw = true;
    }
    if (redraw)
      m.redraw();
  }

  handleMoveMessage(json: ServerGame, firstAttach: boolean) {
    // Handle an incoming Firebase move message
    if (!firstAttach && this.game) {
      this.game.update(json);
      m.redraw();
    }
  }

  notifyMove() {
    // A move has been made in the game:
    // invalidate the game list, since it may have changed
    if (!this.loadingGameList) {
      this.gameList = null;
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
    return this.gameList.length < this.maxFreeGames;
  }

} // class Model

