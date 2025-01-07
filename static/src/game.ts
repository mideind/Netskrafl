/*

	Game.ts

	The Game class, as used in the single-page UI

  Copyright © 2025 Miðeind ehf.
  Author: Vilhjalmur Thorsteinsson

  The Creative Commons Attribution-NonCommercial 4.0
  International Public License (CC-BY-NC 4.0) applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

*/

export { Game, gameUrl, coord, toVector, RackTile, Move, ServerGame };

import { m } from "mithril";

interface TileData {
  player: 0 | 1;
  tile: string;
  letter: string;
  score: number;
  freshtile: boolean;
  draggable: boolean;
  review?: boolean;
  index: number;
  xchg: boolean;
  highlight?: 0 | 1;
}

type TileDict = { [index: string]: TileData; };

type RackTile = [
  tile: string,
  score: number
];

interface SavedTile {
  sq: string;
  tile: string;
}

type TileScoreDict = { [index: string]: number; };

type Move = [
  player: 0 | 1,
  summary: [coord: string, tiles: string, score: number],
  highlighted?: boolean
];

type MoveDetail = [string, string, string, number];

interface MoveListener {
  notifyMove: () => void;
}

interface Message {
  from_userid: string;
  msg: string;
  ts: string;
}  

interface ServerGame {
  result: number;
  msg: string;
  newmoves: Move[];
  two_letter_words: string[][];
  num_moves: number;
  // Several other properties are also sent from the server,
  // but they are copied using key/value enumeration
}

// Old-style (non-single-page) game URL prefix
const BOARD_PREFIX = "/board?game=";
const BOARD_PREFIX_LEN = BOARD_PREFIX.length;

// Global constants
const ROWIDS = "ABCDEFGHIJKLMNO";
const BOARD_SIZE = ROWIDS.length;
const RACK_SIZE = 7;

// Maximum overtime before a player loses the game, 10 minutes in seconds
export const MAX_OVERTIME = 10 * 60.0;
export const DEBUG_OVERTIME = 1 * 60.0;

const GAME_OVER = 99; // Error code corresponding to the Error class in skraflmechanics.py

const START_SQUARE: Record<string, string> = { explo: "D4", standard: "H8" };
const START_COORD: Record<string, [number, number]> = { explo: [3, 3], standard: [7, 7] };

const BOARD: Record<string, Record<string, string[]>> = {
  standard: {
    WORDSCORE: [
      "3      3      3",
      " 2           2 ",
      "  2         2  ",
      "   2       2   ",
      "    2     2    ",
      "               ",
      "               ",
      "3      2      3",
      "               ",
      "               ",
      "    2     2    ",
      "   2       2   ",
      "  2         2  ",
      " 2           2 ",
      "3      3      3"
    ],
    LETTERSCORE: [
      "   2       2   ",
      "     3   3     ",
      "      2 2      ",
      "2      2      2",
      "               ",
      " 3   3   3   3 ",
      "  2   2 2   2  ",
      "   2       2   ",
      "  2   2 2   2  ",
      " 3   3   3   3 ",
      "               ",
      "2      2      2",
      "      2 2      ",
      "     3   3     ",
      "   2       2   "
    ]
  },
  explo: {
    WORDSCORE: [
      "3      3      3",
      "        2      ",
      "         2     ",
      "   2           ",
      "    2          ",
      "     2      2  ",
      "      2      2 ",
      "3      2      3",
      " 2      2      ",
      "  2      2     ",
      "          2    ",
      "           2   ",
      "     2         ",
      "      2        ",
      "3      3      3"
    ],
    LETTERSCORE: [
      "    2      2   ",
      " 3   2       3 ",
      "  2   3     2  ",
      "       2  3   2",
      "2          3   ",
      " 2       2     ",
      "  3     2      ",
      "   2       2   ",
      "      2     3  ",
      "     2       2 ",
      "   3          2",
      "2   3  2       ",
      "  2     3   2  ",
      " 3       2   3 ",
      "   2      2    "
    ]
  }
};

function coord(row: number, col: number): string | null {
  // Return the co-ordinate string for the given 0-based row and col
  if (row < 0 || row >= BOARD_SIZE || col < 0 || col >= BOARD_SIZE)
    return null;
  return ROWIDS[row] + (col + 1);
}

function toVector(co: string): { col: number, row: number, dx: number, dy: number } {
  // Convert a co-ordinate string to a 0-based row, col and direction vector
  var dx = 0, dy = 0;
  var col = 0;
  var row = ROWIDS.indexOf(co[0]);
  if (row >= 0) {
    /* Horizontal move */
    col = parseInt(co.slice(1)) - 1;
    dx = 1;
  }
  else {
    /* Vertical move */
    row = ROWIDS.indexOf(co.slice(-1));
    col = parseInt(co) - 1;
    dy = 1;
  }
  return { col: col, row: row, dx: dx, dy: dy };
}

function arrayEqual(a: any[], b: any[]): boolean {
  // Return true if arrays a and b are equal
  if (a.length != b.length)
    return false;
  for (let i = 0; i < a.length; i++)
    if (a[i] != b[i])
      return false;
  return true;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function gameUrl(url: string): string {
  // Convert old-style game URL to new-style single-page URL
  // The URL format is "/board?game=ed27b9f0-d429-11eb-8bc7-d43d7ee303b2&zombie=1"
  if (url.slice(0, BOARD_PREFIX_LEN) == BOARD_PREFIX)
    // Cut off "/board?game="
    url = url.slice(BOARD_PREFIX_LEN);
  // Isolate the game UUID
  const uuid = url.slice(0, 36);
  // Isolate the other parameters, if any
  let params = url.slice(36);
  // Start parameter section of URL with a ? sign
  if (params.length > 0 && params.charAt(0) == "&")
    params = "?" + params.slice(1);
  // Return the single-page URL, to be consumed by m.route.Link()
  return "/game/" + uuid + params;
}

// An interface around HTML5 local storage functionality, if available

interface LocalStorage {
  getLocalTile: (ix: number) => string;
  getLocalTileSq: (ix: number) => string;
  setLocalTile: (ix: number, t: string) => void;
  setLocalTileSq: (ix: number, sq: string) => void;
  clearTiles: () => void;
  saveTiles: (tilesPlaced: SavedTile[]) => void;
  loadTiles: () => SavedTile[];
}

let _hasLocal: boolean | null = null; // Is HTML5 local storage supported by the browser?

function hasLocalStorage(): boolean {
  // Return true if HTML5 local storage is supported by the browser
  if (_hasLocal === null)
    try {
      _hasLocal = ('localStorage' in window) &&
        (window.localStorage !== null) &&
        (window.localStorage !== undefined);
    } catch (e) {
      _hasLocal = false;
    }
  return _hasLocal;
}

class LocalStorageImpl {

  _prefix: string;

  constructor(uuid: string) {
    // Constructor for local storage associated with a particular game
    this._prefix = "game." + uuid;
  }

  getLocalTile(ix: number) {
      return window.localStorage[this._prefix + ".tile." + ix + ".t"];
  }

  getLocalTileSq(ix: number) {
    return window.localStorage[this._prefix + ".tile." + ix + ".sq"];
  }

  setLocalTile(ix: number, t: string) {
    window.localStorage[this._prefix + ".tile." + ix + ".t"] = t;
  }

  setLocalTileSq(ix: number, sq: string) {
    window.localStorage[this._prefix + ".tile." + ix + ".sq"] = sq;
  }

  clearTiles() {
    // Clean up local storage when game is over
    try {
      for (let i = 1; i <= RACK_SIZE; i++) {
        window.localStorage.removeItem(this._prefix + ".tile." + i + ".sq");
        window.localStorage.removeItem(this._prefix + ".tile." + i + ".t");
      }
    }
    catch (e) {
    }
  }

  saveTiles(tilesPlaced: SavedTile[]) {
    // Save tile locations in local storage
    let i: number;
    for (i = 0; i < tilesPlaced.length; i++) {
      // Store this placed tile in local storage
      let sq = tilesPlaced[i].sq;
      let tile = tilesPlaced[i].tile;
      // Set the placed tile's square
      this.setLocalTileSq(i + 1, sq);
      // Set the letter (or ?+letter if undefined)
      this.setLocalTile(i + 1, tile);
    }
    // Erase all remaining positions in local storage
    for (; i < RACK_SIZE; i++) {
      this.setLocalTileSq(i + 1, "");
      this.setLocalTile(i + 1, "");
    }
  }

  loadTiles() {
    // Return the saved tile locations
    let sq: string, tile: string;
    let tp: SavedTile[] = [];
    for (let i = 0; i < RACK_SIZE; i++) {
      sq = this.getLocalTileSq(i + 1);
      tile = this.getLocalTile(i + 1);
      if (sq && tile)
        tp.push({sq: sq, tile: tile});
    }
    return tp;
  }

} // class LocalStorageImpl

class NoLocalStorageImpl {

  // This class is used if the browser does not implement local storage

  constructor() { }

  getLocalTile(_: number) { return ""; }

  getLocalTileSq(_: number) { return ""; }

  setLocalTile(_ix: number, _content: string) { }

  setLocalTileSq(_ix: number, _sq: string) { }

  clearTiles() { }

  saveTiles(_tilesPlaced: SavedTile[]) { }

  loadTiles(): SavedTile[] { return []; }

} // class NoLocalStorageImpl

class Game {

  // A class that represents a Game instance on the client

  uuid: string;

  locale = "is_IS";
  alphabet = "";
  tile_scores: TileScoreDict = {};
  // Default to the standard board for the Icelandic locale
  board_type = "standard";
  startSquare = "H8";
  startCoord: [number, number] = [7, 7]; // row, col
  two_letter_words: string[][] = [[], []];

  userid: [string, string] = ["", ""];
  nickname: [string, string] = ["", ""];
  fullname: [string, string] = ["", ""];
  autoplayer: [boolean, boolean] = [false, false];
  maxOvertime: number = MAX_OVERTIME;

  scores: [number, number] = [0, 0];
  moves: Move[] = [];
  newmoves: Move[] | undefined = [];
  lastmove: MoveDetail[] | undefined = undefined;
  tiles: TileDict = {};
  rack: RackTile[] = [];
  bag = "";
  newbag: boolean = true;
  localturn: boolean = false;
  player: number | undefined = undefined;
  stats: Record<string, number> | null | undefined = null; // Game review statistics

  over: boolean = false;
  manual: boolean = false;
  fairplay: boolean = false;
  zombie: boolean = false; // !!! FIXME
  overdue: boolean = false; // > 14 days since last move without reply from opponent
  currentScore: number | undefined = undefined;

  messages: Message[] | null = null; // Chat messages associated with this game
  wordBad: boolean = false;
  wordGood: boolean = false;
  xchg: boolean = false; // Exchange allowed?
  chall: boolean = false; // Challenge allowed?
  last_chall: boolean = false; // True if last move laid down and asking for challenge
  succ_chall: boolean = false;
  showingDialog: string | null = null; // Below-the-board dialog (question)
  moveInProgress: boolean = false; // Is the server processing a move?
  askingForBlank: { from: string; to: string; } | null = null;
  currentError: string | number | null = null;
  currentMessage: string | null = null;
  isFresh: boolean = false;
  numTileMoves: number = 0;
  chatLoading: boolean = false; // True while the chat messages are being loaded
  chatSeen: boolean = true; // False if the user has not seen all chat messages
  congratulate: boolean = false; // Show congratulation message if true
  selectedSq: string | null = null; // Currently selected (blinking) square
  sel: string = "movelist"; // By default, show the movelist tab

  // Timed game clock stuff
  interval: number | null = null; // Game clock interval timer
  time_info: { duration: number; elapsed: [number, number]; } | null = null; // Information about elapsed time
  penalty0 = 0;
  penalty1 = 0;
  timeBase: Date | null = null; // Game time base
  runningOut0 = false;
  runningOut1 = false;
  blinking0 = false;
  blinking1 = false;
  clockText0 = "";
  clockText1 = "";

  // Create a local storage object for this game
  localStorage: LocalStorage | null = null;

  // Plug-in point for parties that want to watch moves being made in the game
  moveListener: MoveListener;

  constructor(uuid: string, srvGame: ServerGame, moveListener: MoveListener, maxOvertime?: number) {
    // Game constructor
    // Add extra data and methods to our game model object
    this.uuid = uuid;
    this.moveListener = moveListener;

    if (maxOvertime !== undefined)
      // Maximum time override, for debugging purposes
      this.maxOvertime = maxOvertime;

    // Choose and return a constructor function depending on
    // whether HTML5 local storage is available
    this.localStorage = hasLocalStorage() ?
      new LocalStorageImpl(uuid) : new NoLocalStorageImpl();

    // Load previously saved tile positions from
    // local storage, if any
    let savedTiles = this.localStorage.loadTiles();
    this.init(srvGame);
    // Put tiles in the same position as they were
    // when the player left the game
    this.restoreTiles(savedTiles);
    if (!this.over && this.isTimed())
      // Ongoing timed game: start the clock
      this.startClock();
    // Kick off loading of chat messages, if this is not a robot game
    if (!this.autoplayer[0] && !this.autoplayer[1])
      this.loadMessages();
  }

  init(srvGame: ServerGame) {
    // Initialize the game state with data from the server
    // Check whether the game is over, or whether there was an error
    this.over = srvGame.result == GAME_OVER;
    if (this.over || srvGame.result === 0) {
      this.currentError = this.currentMessage = null;
    } else {
      // Nonzero srvGame.result: something is wrong
      this.currentError = srvGame.result || "server";
      this.currentMessage = srvGame.msg || "";
      return;
    }
    // Copy srvGame JSON properties over to this object
    Object.assign(this, srvGame);
    if (srvGame.newmoves) {
      // Add the newmoves list, if any, to the list of moves
      this.moves = this.moves.concat(srvGame.newmoves);
    }
    // Don't keep the new moves lying around
    this.newmoves = undefined;
    this.localturn = !this.over && ((this.moves.length % 2) == this.player);
    this.isFresh = true;
    this.startSquare = START_SQUARE[this.board_type];
    this.startCoord = START_COORD[this.board_type];
    // If the game is over and this player has more points than
    // the opponent, congratulations are in order
    this.congratulate = this.over && this.player !== undefined &&
      (this.scores[this.player] > this.scores[1 - this.player]);
    if (this.currentError === null)
      // Generate a dictionary of tiles currently on the board,
      // from the moves already made. Also highlights the most recent
      // opponent move (contained in this.lastmove)
      this.placeTiles();
  };

  update(srvGame: ServerGame) {
    // Update the srvGame state with data from the server,
    // either after submitting a move to the server or
    // after receiving a move notification via the Firebase listener
    // Stop highlighting the previous opponent move, if any
    for (let sq in this.tiles)
      if (this.tiles.hasOwnProperty(sq))
        this.tiles[sq].freshtile = false;
    this.init(srvGame);
    if (this.currentError === null) {
      if (this.succ_chall) {
        // Successful challenge: reset the rack
        // (this updates the score as well)
        this.resetRack();
      }
      else {
        this.updateScore();
      }
    }
    this.saveTiles();
    if (this.isTimed())
      // The call to resetClock() clears any outstanding interval timers
      // if the srvGame is now over
      this.resetClock();
  };

  async refresh() {
    // Force a refresh of the current game state from the server
    // Before calling refresh(), this.moveInProgress is typically
    // set to true, so we reset it here
    try {
      if (!this.uuid)
        return;
      const result: { ok: boolean; game: ServerGame; } = await m.request({
        method: "POST",
        url: "/gamestate",
        body: { game: this.uuid }  // !!! FIXME: Add delete_zombie parameter
      });
      if (!result?.ok) {
        // console.log("Game " + uuid + " could not be loaded");
      }
      else {
        this.update(result.game);
      }
    }
    catch(e) {
    }
    finally {
      this.moveInProgress = false;
    }
  }

  notifyUserChange(newNick: string) {
    // The user information may have been changed:
    // perform any updates that may be necessary
    if (this.player !== undefined)
      // The player nickname may have been changed
      this.nickname[this.player] = newNick;
  };

  setSelectedTab(sel: string): boolean {
    // Set the currently selected tab; return true if it was actually changed
    if (this.sel == sel)
      return false;
    this.sel = sel;
    return true;
  };

  tilescore(tile: string) {
    // Note: The Python naming convention of tile_scores is intentional
    return this.tile_scores[tile];
  };

  twoLetterWords() {
    // Note: The Python naming convention of two_letter_words is intentional
    return this.two_letter_words;
  };

  isTimed(): boolean {
    // Return True if this is a timed game
    return (!!this.time_info) && this.time_info.duration >= 1.0;
  };

  showClock(): boolean {
    // Return true if the clock should be shown in the right-hand column
    if (!this.isTimed())
      // Only show the clock for a timed game, obviously
      return false;
    if (!this.over)
      // If the game is still ongoing, always show the clock
      return true;
    // If the game is over, only show the clock if there is something to
    // show, i.e. at least one clock text
    return !!this.clockText0 || !!this.clockText1;
  }

  updateClock() {
    var txt0 = this.calcTimeToGo(0);
    var txt1 = this.calcTimeToGo(1);
    this.clockText0 = txt0;
    this.clockText1 = txt1;
    // If less than two minutes left, indicate that time is running out
    this.runningOut0 = (txt0[0] == "-" || txt0 <= "02:00");
    this.runningOut1 = (txt1[0] == "-" || txt1 <= "02:00");
    // If less than 30 seconds left, make the clock digits blink
    this.blinking0 = (this.runningOut0 && txt0 >= "00:00" && txt0 <= "00:30" && this.player == 0);
    this.blinking1 = (this.runningOut1 && txt1 >= "00:00" && txt1 <= "00:30" && this.player == 1);
    m.redraw();
  }

  resetClock() {
    // Set a new time base after receiving an update from the server
    this.timeBase = new Date();
    this.updateClock();
    if (this.over) {
      // Game over: reset stuff
      if (this.interval) {
        window.clearInterval(this.interval);
        this.interval = null;
      }
      this.blinking0 = false;
      this.blinking1 = false;
      this.runningOut0 = false;
      this.runningOut1 = false;
    }
  }

  startClock() {
    // Start the clock running, after loading a timed game
    this.resetClock();
    if (!this.interval) {
      this.interval = window.setInterval(
        () => { this.updateClock(); },
        500 // milliseconds, i.e. 0.5 seconds
      );
    }
  }

  cleanup() {
    // Clean up any resources owned by this game object
    if (this.interval) {
      window.clearInterval(this.interval);
      this.interval = null;
    }
  }

  calcTimeToGo(player: 0 | 1) {
    /* Return the time left for a player in a nice MM:SS format */
    const gameTime = this.time_info;
    const timeBase = this.timeBase;
    if (!gameTime || !timeBase) return "";
    let elapsed = gameTime.elapsed[player];
    let gameOver = this.over;
    if (!gameOver && (this.moves.length % 2) == player) {
      // This player's turn: add the local elapsed time
      const now = new Date();
      elapsed += (now.getTime() - timeBase.getTime()) / 1000;
      if (elapsed - gameTime.duration * 60.0 > this.maxOvertime) {
        // 10 minutes overtime has passed: The client now believes
        // that the player has lost. Refresh the game from the server
        // to get its final verdict.
        if (!this.moveInProgress) {
          this.moveInProgress = true;
          // Refresh from the server in half a sec, to be a little
          // more confident that it agrees with us
          window.setTimeout(
            () => { this.refresh(); }, 500
          );
        }
      }
    }
    // The overtime is max 10 minutes - at that point you lose
    let timeToGo = Math.max(gameTime.duration * 60.0 - elapsed, -this.maxOvertime);
    let absTime = Math.abs(timeToGo);
    let min = Math.floor(absTime / 60.0);
    let sec = Math.floor(absTime - min * 60.0);
    if (gameOver) {
      // We already got a correct score from the server
      this.penalty0 = 0;
      this.penalty1 = 0;
    }
    else
    if (timeToGo < 0.0) {
      // We're into overtime: calculate the score penalty
      if (player === 0)
        this.penalty0 = -10 * Math.floor((min * 60 + sec + 59) / 60);
      else
        this.penalty1 = -10 * Math.floor((min * 60 + sec + 59) / 60);
    }
    return (timeToGo < 0.0 ? "-" : "") +
       ("0" + min.toString()).slice(-2) + ":" + ("0" + sec.toString()).slice(-2);
  }

  displayScore(player: 0 | 1): number {
    // Return the score to be displayed, which is the current
    // actual game score minus accrued time penalty, if any, in a timed game
    return Math.max(
      this.scores[player] + (player == 0 ? this.penalty0 : this.penalty1), 0
    )
  }

  async loadMessages() {
    // Load chat messages for this game
    if (this.chatLoading)
      // Already loading
      return;
    this.chatLoading = true;
    this.messages = [];
    try {
      const result = await m.request(
        {
          method: "POST",
          url: "/chatload",
          body: { channel: "game:" + this.uuid }
        }
      );
      if (result.ok)
        this.messages = result.messages || [];
      else
        this.messages = [];
      // Note whether the user has seen all chat messages
      if (result.seen === undefined)
        this.chatSeen = true;
      else
        this.chatSeen = result.seen;
    }
    catch (e) {
      // Just leave this.messages as an empty list
    }
    finally {
      this.chatLoading = false;
    }
  }

  async loadStats() {
    // Load statistics about a game
    this.stats = undefined; // Error/in-progress status
    try {
      const json = await m.request(
        {
          method: "POST",
          url: "/gamestats",
          body: { game: this.uuid }
        }
      );
      // Save the incoming game statistics in the stats property
      if (!json || json.result === undefined)
        return;
      if (json.result !== 0 && json.result !== GAME_OVER)
        return;
      // Success: assign the stats
      this.stats = json;
    }
    catch(e) {
      // Just leave this.stats undefined
    }
  }

  async sendMessage(msg: string) {
    // Send a chat message
    try {
      await m.request(
        {
          method: "POST",
          url: "/chatmsg",
          body: { channel: "game:" + this.uuid, msg: msg }
        }
      );
    }
    catch(e) {
      // No big deal
      // A TODO might be to add some kind of error icon to the UI
    }
  }

  sendChatSeenMarker() {
    // Send a 'chat message seen' marker to the server
    this.sendMessage("");
    // The user has now seen all chat messages
    this.chatSeen = true;
  }

  addChatMessage(from_userid: string, msg: string, ts: string, ownMessage: boolean) {
    // Add a new chat message, received via a Firebase notification,
    // to the message list
    if (this.chatLoading || msg == "")
      // Loading of the message list is underway: assume that this message
      // will be contained in the list, once it has been read
      return;
    if (this.messages === null) this.messages = [];
    this.messages.push({ from_userid: from_userid, msg: msg, ts: ts });
    if (this.sel == "chat") {
      // Chat already open, so the player has seen the message: send a read receipt
      this.sendChatSeenMarker();
    } else if (!ownMessage) {
      // Chat not open, and we have a new chat message from the other player:
      // note that this player hasn't seen it
      this.chatSeen = false;
    }
  }

  markChatShown(): boolean {
    // Note that the user has seen all pending chat messages
    if (!this.chatSeen) {
      this.sendChatSeenMarker();
      return true;
    }
    return false;
  }

  placeMove(player: 0 | 1, co: string, tiles: string, highlight: boolean) {
    // Place an entire move into the tiles dictionary
    const vec = toVector(co);
    let col = vec.col;
    let row = vec.row;
    let nextBlank = false;
    let index = 0;
    for (let i = 0; i < tiles.length; i++) {
      let tile = tiles[i];
      if (tile == '?') {
        nextBlank = true;
        continue;
      }
      const sq = coord(row, col);
      if (sq === null) throw new Error("Invalid coordinate: " + row + ", " + col);
      const letter = tile;
      if (nextBlank)
        tile = '?';
      const tscore = this.tilescore(tile);
      // Place the tile, if it isn't there already
      if (!(sq in this.tiles)) {
        this.tiles[sq] = {
          player: player,
          tile: tile,
          letter: letter,
          score: tscore,
          draggable: false,
          freshtile: false,
          index: index, // Index of this tile within the move, for animation purposes
          xchg: false,
        };
        if (highlight) {
          // Highlight the tile
          if (player == this.player)
            this.tiles[sq].highlight = 0; // Local player color
          else
            this.tiles[sq].highlight = 1; // Remote player color
          index++;
        }
      }
      col += vec.dx;
      row += vec.dy;
      nextBlank = false;
    }
  }

  setRack(rack: RackTile[]) {
    // Set the current rack
    this.rack = rack;
  }

  placeTiles(move?: number, noHighlight?: boolean) {
    // Make a tile dictionary for the game.
    // If move is given, it is an index of the
    // last move in the move list that should be
    // shown on the board.
    this.tiles = {};
    this.numTileMoves = 0;
    let mlist = this.moves;
    // We highlight the last move placed (a) if we're in a game
    // review (move !== undefined) or (b) if this is a normal game
    // view, we don't have an explicit this.lastmove (which is treated
    // separately) and the last move is an opponent move.
    let highlightReview = (move !== undefined);
    let highlightLast = !highlightReview && !this.lastmove && this.localturn;
    let highlight = !noHighlight && (highlightLast || highlightReview);
    let last = highlightReview ? (move ?? 0) : mlist.length;

    function successfullyChallenged(ix: number): boolean {
      // Was the move with index ix successfully challenged?
      if (ix + 2 >= last)
        // The move list is too short for a response move
        return false;
      let [ _, [ co, tiles, score ] ] = mlist[ix + 2];
      if (co != "")
        // The player's next move is a normal tile move
        return false;
      // Return true if this was a challenge response with a negative score
      // (i.e. a successful challenge)
      return (tiles == "RESP") && (score < 0);
    }

    // Loop through the move list, placing each move
    for (let i = 0; i < last; i++) {
      let [ player, [co, tiles] ] = mlist[i];
      if (co != "" && !successfullyChallenged(i)) {
        // Unchallenged tile move: place it on the board
        this.placeMove(player, co, tiles, (i == last - 1) && highlight);
        this.numTileMoves++;
      }
    }
    // If it's our turn, mark the opponent's last move
    // The type of this.lastmove corresponds to DetailTuple on the server side
    let dlist = this.lastmove;
    if (dlist && this.localturn)
      for (let i = 0; i < dlist.length; i++) {
        const sq: string = dlist[i][0];
        if (!(sq in this.tiles))
          throw "Tile from lastmove not in square " + sq;
        this.tiles[sq].freshtile = true;
        this.tiles[sq].index = i; // Index of tile within move, for animation purposes
      }
    // Also put the rack tiles into this.tiles
    for (let i = 0; i < this.rack.length; i++) {
      let sq = 'R' + (i + 1);
      let tile = this.rack[i][0];
      let letter = (tile == '?') ? ' ' : tile;
      let tscore = this.rack[i][1];
      this.tiles[sq] = {
        player: this.player ? 1 : 0,
        tile: tile,
        letter: letter,
        score: tscore,
        draggable: true,
        freshtile: false,
        index: 0,
        xchg: false
      };
    }
  };

  private _moveTile(from: string, to: string) {
    // Low-level function to move a tile between cells/slots
    if (from == to)
      // Nothing to do
      return;
    let fromTile = this.tiles[from];
    if (fromTile === undefined)
      throw "Moving from an empty square";
    delete this.tiles[from];
    if (to in this.tiles) {
      if (to.charAt(0) != "R")
        throw "Dropping to an occupied square";
      // Dropping to an occupied slot in the rack:
      // create space in the rack
      let dest = parseInt(to.slice(1));
      let empty = dest + 1;
      // Try to find an empty slot to the right of the drop destination
      while (('R' + empty) in this.tiles)
        empty++;
      if (empty <= RACK_SIZE) {
        // Found empty slot after the tile:
        // move the intervening tiles to the right
        for (let j = empty; j > dest; j--)
          this.tiles['R' + j] = this.tiles['R' + (j - 1)];
      }
      else {
        // No empty slots after the tile: try to find one to the left
        empty = dest - 1;
        while (('R' + empty) in this.tiles)
          empty--;
        if (empty < 1)
          throw "No place in rack to drop tile";
        for (let j = empty; j < dest; j++)
          this.tiles['R' + j] = this.tiles['R' + (j + 1)];
      }
    }
    if (to[0] == 'R' && fromTile.tile == '?')
    // Putting a blank tile back into the rack: erase its meaning
      fromTile.letter = ' ';
    this.tiles[to] = fromTile;
  };

  moveTile(from: string, to: string) {
    // High-level function to move a tile between cells/slots
    this._moveTile(from, to);
    // Clear error message, if any
    this.currentError = this.currentMessage = null;
    // Update the current word score
    this.updateScore();
    // Update the local storage
    this.saveTiles();
  };

  attemptMove(from: string, to: string) {
    if (to == from)
      // No move
      return;
    if (to in this.tiles && to[0] != 'R')
      throw "Square " + to + " occupied";
    if (!(from in this.tiles))
      throw "No tile at " + from;
    let tile = this.tiles[from];
    if (to[0] != 'R' && tile.tile == '?' && tile.letter == ' ') {
      // Dropping a blank tile on the board:
      // postpone the move and ask for its meaning
      this.askingForBlank = { from: from, to: to };
      return;
    }
    // Complete the move
    this.moveTile(from, to);
  };

  cancelBlankDialog() {
    // Cancel the dialog asking for the meaning of the blank tile
    this.askingForBlank = null;
  };

  placeBlank(letter: string) {
    // Assign a meaning to a blank tile that is being placed on the board
    if (this.askingForBlank === null)
      return;
    let from = this.askingForBlank.from;
    let to = this.askingForBlank.to;
    // We must assign the tile letter before moving it
    // since moveTile() calls updateScore() which in turn does a /wordcheck
    this.tiles[from].letter = letter;
    this.moveTile(from, to);
    this.askingForBlank = null;
  };

  tilesPlaced(): string[] {
    // Return a list of coordinates of tiles that the user has
    // placed on the board by dragging from the rack
    let r: string[] = [];
    for (let sq in this.tiles)
      if (this.tiles.hasOwnProperty(sq) &&
        sq[0] != 'R' && this.tiles[sq].draggable)
        // Found a non-rack tile that is not glued to the board
        r.push(sq);
    return r;
  };

  async sendMove(moves: string[]) {
    // Send a move to the server
    this.moveInProgress = true;
    try {
      const result: ServerGame = await m.request(
        {
          method: "POST",
          url: "/submitmove",
          body: { moves: moves, mcount: this.moves.length, uuid: this.uuid }
        }
      );
      // The update() function also handles error results
      this.update(result);
      // Notify eventual listeners that a (local) move has been made
      if (this.moveListener)
        this.moveListener.notifyMove();
    } catch (e: unknown) {
      this.currentError = "server";
      this.currentMessage = getErrorMessage(e);;
    }
    finally {
      this.moveInProgress = false;
    }
  };

  async forceResign() {
    // Force resignation by a tardy opponent
    this.moveInProgress = true;
    try {
      const result: ServerGame = await m.request(
        {
          method: "POST",
          url: "/forceresign",
          body: { mcount: this.moves.length, game: this.uuid }
        }
      );
      // The update() function also handles error results
      this.update(result);
    } catch (e: unknown) {
      this.currentError = "server";
      this.currentMessage = getErrorMessage(e);
    }
    finally {
      this.moveInProgress = false;
    }
  };

  submitMove() {
    // Send a tile move to the server
    let t = this.tilesPlaced();
    let moves: string[] = [];
    this.selectedSq = null; // Currently selected (blinking) square
    for (let i = 0; i < t.length; i++) {
      let sq = t[i];
      let tile = this.tiles[sq];
      moves.push(sq + "=" + tile.tile + (tile.tile == '?' ? tile.letter : ""));
    }
    if (moves.length > 0)
      this.sendMove(moves);
  };

  submitPass() {
    // Show a pass confirmation prompt
    this.showingDialog = "pass";
    this.selectedSq = null; // Currently selected (blinking) square
  };

  submitChallenge() {
    // Show a challenge confirmation prompt
    this.showingDialog = "chall";
    this.selectedSq = null; // Currently selected (blinking) square
  };

  submitExchange() {
    // Show an exchange prompt
    this.showingDialog = "exchange";
    this.selectedSq = null; // Currently selected (blinking) square
    // Remove the xchg flag from all tiles in the rack
    for (let i = 1; i <= RACK_SIZE; i++) {
      let sq = "R" + i;
      if (sq in this.tiles)
        this.tiles[sq].xchg = false;
    }
  };

  submitResign() {
    // Show a resign prompt
    this.showingDialog = "resign";
    this.selectedSq = null; // Currently selected (blinking) square
  };

  confirmPass(yes: boolean) {
    // Handle reply to pass confirmation prompt
    this.showingDialog = null;
    if (yes)
      this.sendMove([ "pass" ]);
  };

  confirmChallenge(yes: boolean) {
    // Handle reply to challenge confirmation prompt
    this.showingDialog = null;
    if (yes)
      this.sendMove([ "chall" ]);
  };

  confirmExchange(yes: boolean) {
    // Handle reply to exchange confirmation prompt
    let exch = "";
    this.showingDialog = null;
    for (let i = 1; i <= RACK_SIZE; i++) {
      let sq = "R" + i;
      if (sq in this.tiles && this.tiles[sq].xchg) {
        // This tile is marked for exchange
        exch += this.tiles[sq].tile;
        this.tiles[sq].xchg = false;
      }
    }
    if (yes && exch.length > 0)
      // Send the exchange move to the server
      this.sendMove([ "exch=" + exch ]);
  };

  confirmResign(yes: boolean) {
    // Handle reply to resignation confirmation prompt
    this.showingDialog = null;
    if (yes)
      this.sendMove([ "rsgn" ]);
  };

  rescrambleRack() {
    // Reorder the rack randomly. Bound to the Backspace key.
    this.selectedSq = null; // Currently selected (blinking) square
    if (this.showingDialog !== null)
      // Already showing a bottom-of-page dialog
      return;
    this._resetRack();
    const array: (TileData | null)[] = [];
    let rackTileId: string;
    for (let i = 1; i <= RACK_SIZE; i++) {
      rackTileId = "R" + i;
      if (rackTileId in this.tiles)
        array.push(this.tiles[rackTileId]);
      else
        array.push(null);
    }
    let currentIndex = array.length, temporaryValue: TileData | null, randomIndex: number;
    // Fisher-Yates (Knuth) shuffle algorithm
    while (0 !== currentIndex) {
      randomIndex = Math.floor(Math.random() * currentIndex);
      currentIndex -= 1;
      temporaryValue = array[currentIndex];
      array[currentIndex] = array[randomIndex];
      array[randomIndex] = temporaryValue;
    }
    // Fill the resulting rack from left to right
    let empty = 0; // Destination rack cell
    for (let i = 1; i <= RACK_SIZE; i++) {
      const item = array[i-1];
      if (item !== null)
        // Nonempty result cell: copy it
        this.tiles["R" + (i - empty)] = item;
      else {
        // Empty result cell: empty a rack cell from the right-hand side
        delete this.tiles["R" + (RACK_SIZE - empty)];
        empty++;
      }
    }
    this.saveTiles();
  };

  saveTiles() {
    // Save the current unglued tile configuration to local storage
    const ls = this.localStorage;
    if (!ls) return; // No local storage available
    let sq: string, t: TileData, tile: string;
    let tp: { sq: string; tile: string; }[] = [];
    let tilesPlaced = this.tilesPlaced();
    for (let i = 0; i < tilesPlaced.length; i++) {
      sq = tilesPlaced[i];
      t = this.tiles[sq];
      tile = t.tile;
      // For blank tiles, store their meaning as well
      if (tile == "?")
        tile += t.letter;
      tp.push({sq: sq, tile: tile});
    }
    // Also save tiles remaining in the rack
    for (let i = 1; i <= RACK_SIZE; i++) {
      sq = "R" + i;
      if (sq in this.tiles)
        tp.push({sq: sq, tile: this.tiles[sq].tile});
    }
    ls.saveTiles(tp);
  };

  restoreTiles(savedTiles: { sq: string; tile: string}[]) {
    // Restore the tile positions that were previously stored
    // in local storage
    if (!savedTiles.length)
      // Nothing to do
      return;
    let tile: string;
    let savedLetters: string[] = [];
    let rackLetters: string[] = [];
    let rackTiles: TileDict = {};
    // First, check that the saved tiles match the current rack
    for (let i = 0; i < savedTiles.length; i++)
      savedLetters.push(savedTiles[i].tile.charAt(0));
    for (let i = 1; i <= RACK_SIZE; i++)
      if (("R" + i) in this.tiles)
        rackLetters.push(this.tiles["R" + i].tile.charAt(0));
    savedLetters.sort();
    rackLetters.sort();
    if (!arrayEqual(savedLetters, rackLetters))
      // We don't have the same rack as when the state was saved:
      // give up
      return;
    // Save the original rack and delete the rack tiles
    // from the board
    for (let j = 1; j <= RACK_SIZE; j++)
      if (("R" + j) in this.tiles) {
        rackTiles["R" + j] = this.tiles["R" + j];
        delete this.tiles["R" + j];
      }
    // Attempt to move the saved tiles from the saved rack to
    // their saved positions. Note that there are several corner
    // cases, for instance multiple instances of the same letter tile,
    // that make this code less than straightforward.
    for (let i = 0; i < savedTiles.length; i++) {
      let saved_sq = savedTiles[i].sq;
      if (!(saved_sq in this.tiles)) {
        // The saved destination square is empty:
        // find the tile in the saved rack and move it there
        tile = savedTiles[i].tile;
        for (let sq in rackTiles)
          if (rackTiles.hasOwnProperty(sq) &&
            rackTiles[sq].tile == tile.charAt(0)) {
            // Found the tile (or its equivalent) in the rack: move it
            if (tile.charAt(0) == "?")
              if (saved_sq.charAt(0) == "R")
                // Going to the rack: no associated letter
                rackTiles[sq].letter = " ";
              else
                // Going to a board square: associate the originally
                // chosen and saved letter
                rackTiles[sq].letter = tile.charAt(1);
            // ...and assign it
            this.tiles[saved_sq] = rackTiles[sq];
            delete rackTiles[sq];
            break;
          }
      }
    }
    // Allocate any remaining tiles to free slots in the rack
    let j = 1;
    for (let sq in rackTiles)
      if (rackTiles.hasOwnProperty(sq)) {
        // Look for a free slot in the rack
        while(("R" + j) in this.tiles)
          j++;
        if (j <= RACK_SIZE)
          // Should always be true unless something is very wrong
          this.tiles["R" + j] = rackTiles[sq];
      }
    // The local storage may have been cleared before calling
    // restoreTiles() so we must ensure that it is updated
    this.saveTiles();
    // Show an updated word status and score
    this.updateScore();
  };

  _resetRack() {
    // Recall all unglued tiles into the rack
    let t = this.tilesPlaced();
    if (t.length) {
      let i = 1;
      for (let j = 0; j < t.length; j++) {
        // Find a free slot in the rack
        while (("R" + i) in this.tiles)
          i++;
        let sq = "R" + i;
        // Recall the tile
        this.tiles[sq] = this.tiles[t[j]];
        delete this.tiles[t[j]];
        if (this.tiles[sq].tile == '?')
          // Erase the meaning of the blank tile
          this.tiles[sq].letter = ' ';
        i++;
      }
      // Update score
      this.updateScore();
    }
    // Reset current error message, if any
    this.currentError = null;
  };

  resetError() {
    // Reset the current error message, if any
    this.currentError = this.currentMessage = null;
  }

  resetRack() {
    // Recall all unglued tiles into the rack
    this.selectedSq = null; // Currently selected (blinking) square
    this._resetRack();
    this.saveTiles();
  };

  async updateScore() {
    // Re-calculate the current word score
    let scoreResult = this.calcScore();
    this.wordGood = false;
    this.wordBad = false;
    if (scoreResult === undefined)
      this.currentScore = undefined;
    else {
      this.currentScore = scoreResult.score;
      let wordToCheck = scoreResult.word;
      if (!this.manual) {
        // This is not a manual-wordcheck game:
        // Check the word that has been laid down
        try {
          const result: { word: string; ok: boolean; } = await m.request({
            method: "POST",
            url: "/wordcheck",
            body: {
              locale: this.locale,
              word: scoreResult.word,
              words: scoreResult.words
            }
          });
          if (result?.word == wordToCheck) {
            this.wordGood = result.ok;
            this.wordBad = !result.ok;
          }
        }
        catch(e) {
        }
      }
    }
  };

  wordScore(row: number, col: number): number {
    // Return the word score multiplier at the given coordinate
    // on the game's board
    let wsc = BOARD[this.board_type].WORDSCORE;
    return parseInt(wsc[row].charAt(col)) || 1;
  };

  letterScore(row: number, col: number): number {
    // Return the letter score multiplier at the given coordinate
    // on the game's board
    let lsc = BOARD[this.board_type].LETTERSCORE;
    return parseInt(lsc[row].charAt(col)) || 1;
  };

  squareType(row: number, col: number): string {
    // Return the square type, or "" if none
    const wsc = this.wordScore(row, col);
    if (wsc == 2)
      return "dw"; // Double word
    if (wsc == 3)
      return "tw"; // Triple word
    const lsc = this.letterScore(row, col);
    if (lsc == 2)
      return "dl"; // Double letter
    if (lsc == 3)
      return "tl"; // Triple letter
    return ""; // Plain square
  };

  squareClass(coord: string): string | undefined{
    // Given a coordinate in string form, return the square's type/class
    if (!coord || coord[0] == "R")
      return undefined;
    const vec = toVector(coord);
    return this.squareType(vec.row, vec.col) || undefined;
  };

  tileAt(row: number, col: number): TileData | null {
    const c = coord(row, col);
    if (!c) return null;
    return this.tiles[c] ?? null;
  };

  calcScore() {
    // Calculate the score for the tiles that have been laid on the board in the current move
    let score = 0, crossScore = 0;
    let wsc = 1;
    let minrow = BOARD_SIZE, mincol = BOARD_SIZE;
    let maxrow = 0, maxcol = 0;
    let numtiles = 0, numcrosses = 0;
    let word = "";
    let words: string[] = [];
    this.tilesPlaced().forEach((sq) => {
      // Tile on the board
      let row = ROWIDS.indexOf(sq.charAt(0));
      let col = parseInt(sq.slice(1)) - 1;
      let t = this.tiles[sq];
      score += t.score * this.letterScore(row, col);
      numtiles++;
      wsc *= this.wordScore(row, col);
      if (row < minrow)
        minrow = row;
      if (col < mincol)
        mincol = col;
      if (row > maxrow)
        maxrow = row;
      if (col > maxcol)
        maxcol = col;
    });
    if (!numtiles)
      return undefined;
    if (minrow != maxrow && mincol != maxcol)
      // Not a pure horizontal or vertical move
      return undefined;
    let x = mincol, y = minrow;
    let dx: -1 | 0 | 1 = 0, dy: -1 | 0 | 1 = 0;
    if (minrow != maxrow)
      dy = 1; // Vertical
    else
    if (mincol == maxcol &&
      (this.tileAt(minrow - 1, mincol) !== null || this.tileAt(minrow + 1, mincol) !== null))
      // Single tile: if it has tiles above or below, consider this a vertical move
      dy = 1;
    else
      dx = 1; // Horizontal
    // Find the beginning of the word
    while (this.tileAt(y - dy, x - dx) !== null) {
      x -= dx;
      y -= dy;
    }
    let t: TileData | null;
    // Find the end of the word
    while ((t = this.tileAt(y, x)) !== null) {
      if (t.draggable) {
        // Add score for cross words
        let csc = this.calcCrossScore(y, x, 1 - dy, 1 - dx);
        if (csc.score >= 0) {
          // There was a cross word there (it can score 0 if blank)
          crossScore += csc.score;
          numcrosses++;
          words.push(csc.word);
        }
      }
      else {
        // This is a tile that was previously on the board
        score += t.score;
        numcrosses++;
      }
      // Accumulate the word being formed
      word += t.letter;
      x += dx;
      y += dy;
    }
    if (this.numTileMoves === 0) {
      // First move that actually lays down tiles must go through start square
      let c = this.startCoord;
      if (null === this.tileAt(c[0], c[1]))
        // No tile in the start square
        return undefined;
    }
    else
    if (!numcrosses)
      // Not first move, and not linked with any word on the board
      return undefined;
    // Check whether word is consecutive
    // (which it is not if there is an empty square before the last tile)
    if (dx && (x <= maxcol))
      return undefined;
    if (dy && (y <= maxrow))
      return undefined;
    words.push(word);
    return { word: word, words: words,
      score: score * wsc + crossScore + (numtiles == RACK_SIZE ? 50 : 0) };
  };

  calcCrossScore(oy: number, ox: number, dy: number, dx: number) {
    // Calculate the score contribution of a cross word
    let score = 0;
    let hascross = false;
    let x = ox, y = oy;
    let word = "";
    // Find the beginning of the word
    while (this.tileAt(y - dy, x - dx) !== null) {
      x -= dx;
      y -= dy;
    }
    let t: TileData | null;
    // Find the end of the word
    while ((t = this.tileAt(y, x)) !== null) {
      let sc = t.score;
      if (x == ox && y == oy)
        sc *= this.letterScore(y, x);
      else
        hascross = true;
      word += t.letter;
      score += sc;
      x += dx;
      y += dy;
    }
    if (!hascross)
      return { score: -1, word: "" };
    return { score: score * this.wordScore(oy, ox), word: word };
  };

} // class Game

