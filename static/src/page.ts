/*

  Page.ts

  Single page UI for Explo using the Mithril library

  Copyright © 2025 Miðeind ehf.
  Author: Vilhjálmur Þorsteinsson

  The Creative Commons Attribution-NonCommercial 4.0
  International Public License (CC-BY-NC 4.0) applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

  This UI is built on top of Mithril (https://mithril.js.org), a lightweight,
  straightforward JavaScript single-page reactive UI library.

  The page is structured into models, actions and views,
  cf. https://github.com/pakx/the-mithril-diaries/wiki/Basic-App-Structure

*/

export {
  main, View, DialogButton, OnlinePresence, glyph, nbsp,
  buttonOver, buttonOut
};

import {
  m, Vnode, VnodeAttrs, ComponentFunc, EventHandler,
  MithrilEvent, VnodeChildren
} from "mithril";

import {
  Model, GlobalState, getSettings,
  UserListItem, ChallengeListItem, RecentListItem,
  ChallengeAction, MoveInfo, Params
} from "model";

import { Game, gameUrl, coord, toVector, Move } from "game";

import { addPinchZoom } from "util";

import { Actions, createRouteResolver } from "actions";

import { WaitDialog, AcceptDialog } from "wait";

import { ExploLogo, AnimatedExploLogo } from "logo";

import {
  FriendPromoteDialog, FriendThanksDialog,
  FriendCancelDialog, FriendCancelConfirmDialog
} from "friend";

import { logEvent } from "channel";

import { mt, t, ts } from "i18n";

// Types

type EloListSelection = "human" | "all" | "manual";

// Constants

const RACK_SIZE = 7;
const BAG_TILES_PER_LINE = 19;
const BLANK_TILES_PER_LINE = 6;
const ROUTE_PREFIX = "/page#!";
const ROUTE_PREFIX_LEN = ROUTE_PREFIX.length;
// Max number of chat messages per game
const MAX_CHAT_MESSAGES = 250;

const ERROR_MESSAGES: { [key: string]: string } = {
  // Translations are found in /static/assets/messages.json
  1: "Enginn stafur lagður niður",
  2: "Fyrsta orð verður að liggja um byrjunarreitinn",
  3: "Orð verður að vera samfellt á borðinu",
  4: "Orð verður að tengjast orði sem fyrir er",
  5: "Reitur þegar upptekinn",
  6: "Ekki má vera eyða í orði",
  7: "word_not_found",
  8: "word_not_found",
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
  "server": "Netþjónn gat ekki tekið við leiknum - reyndu aftur"
};


function main(state: GlobalState) {
  // The main UI entry point, called from page.html

  const
    settings = getSettings(),
    model = new Model(settings, state),
    view = new View(model),
    actions = new Actions(model, view),
    routeResolver = createRouteResolver(actions),
    defaultRoute = settings.defaultRoute,
    root = document.getElementById("container");

  // Run the Mithril router
  m.route(root, defaultRoute, routeResolver);
}

type DialogFunc = (view: View, args: any) => m.vnode;

interface DialogViews {
  userprefs: DialogFunc;
  userinfo: DialogFunc;
  challenge: DialogFunc;
  promo: DialogFunc;
  friend: DialogFunc;
  thanks: DialogFunc;
  cancel: DialogFunc;
  confirm: DialogFunc;
  wait: DialogFunc;
  accept: DialogFunc;
}

interface Dialog {
  name: string;
  args: any;
}

class View {

  // The View class exposes the vwApp view function.
  // Each instance maintains a current dialog window stack.

  // The model that the view is attached to
  model: Model;

  // The currently displayed dialogs
  private dialogStack: Dialog[] = [];

  // Map of available dialogs
  private static dialogViews: DialogViews = {
    userprefs:
      (view) => view.vwUserPrefs(),
    userinfo:
      (view, args) => view.vwUserInfo(args),
    challenge:
      (view, args) => view.vwChallenge(args),
    promo:
      (view, args) => view.vwPromo(args),
    friend:
      (view, args) => view.vwFriend(args),
    thanks:
      (view, args) => view.vwThanks(args),
    cancel:
      (view, args) => view.vwCancel(args),
    confirm:
      (view, args) => view.vwConfirm(args),
    wait:
      (view, args) => view.vwWait(args),
    accept:
      (view, args) => view.vwAccept(args)
  };

  // The current scaling of the board
  boardScale: number = 1.0;

  constructor(model: Model) {

    this.model = model;

    // Start a blinker interval function
    window.setInterval(this.blinker, 500);

  }

  appView(): m.vnode[] {
    // Returns a view based on the current route.
    // Displays the appropriate content for the route,
    // also considering active dialogs.
    const model = this.model;
    let views: m.vnode[] = [];
    switch (model.routeName) {
      case "main":
        views.push(this.vwMain());
        break;
      case "game":
        views.push(this.vwGame());
        break;
      case "review":
        views.push(this.vwReview());
        break;
      case "thanks":
        // Display a thank-you dialog on top of the normal main screen
        views.push(this.vwMain());
        // Be careful to add the Thanks dialog only once to the stack
        if (!this.dialogStack.length)
          this.showThanks();
        break;
      case "help":
        // A route parameter of ?q=N goes directly to the FAQ number N
        // A route parameter of ?tab=N goes directly to tab N (0-based)
        views.push(
          this.vwHelp(
            parseInt(m.route.param("tab") || ""),
            parseInt(m.route.param("faq") || "")
          )
        );
        break;
      default:
        // console.log("Unknown route name: " + model.routeName);
        return [ m("div", t("Þessi vefslóð er ekki rétt")) ];
    }
    // Push any open dialogs
    for (let dialog of this.dialogStack) {
      let v: DialogFunc = View.dialogViews[dialog.name];
      if (v === undefined)
        console.log("Unknown dialog name: " + dialog.name);
      else
        views.push(v(this, dialog.args));
    }
    // Overlay a spinner, if active
    if (model.spinners)
      views.push(m(this.Spinner));
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
    this.model.spinners++;
  }

  stopSpinner() {
    if (this.model.spinners) {
      this.model.spinners--;
    }
  }

  async cancelFriendship() {
    // Initiate cancellation of the user's friendship
    let spinner = true;
    try {
      this.startSpinner();
      if (await this.model.cancelFriendship()) {
        // Successfully cancelled the friendship
        this.stopSpinner();
        spinner = false;
        // Show a confirmation of the cancellation
        this.pushDialog("confirm", {});
      }
    } catch (e) {
      // Simply display no confirmation in this case
    }
    finally {
      if (spinner)
        this.stopSpinner();
    }
  }

  notifyMediaChange() {
    // The view is changing, between mobile and fullscreen
    // and/or between portrait and landscape: ensure that
    // we don't end up with a selected game tab that is not visible
    const model = this.model;
    if (model.game) {
      if (model.state.uiFullscreen || model.state.uiLandscape) {
        // In this case, there is no board tab:
        // show the movelist
        if (model.game.setSelectedTab("movelist"))
          setTimeout(this.scrollMovelistToBottom);
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
    // and has been added to the chat message list
    m.redraw();
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

  updateScale(game: Game) {

    const model = this.model;

    // Update the board scale (zoom)

    function scrollIntoView(sq: string) {
      // Scroll a square above and to the left of the placed tile into view
      const offset = 3;
      let vec = toVector(sq);
      let row = Math.max(0, vec.row - offset);
      let col = Math.max(0, vec.col - offset);
      let c = coord(row, col);
      let el = document.getElementById("sq_" + c);
      let boardParent = document.getElementById("board-parent");
      let board = boardParent.children[0];
      // The following seems to be needed to ensure that
      // the transform and hence the size of the board has been 
      // updated in the browser, before calculating the client rects
      if (board)
        board.setAttribute("style", "transform: scale(1.5)");
      let elRect = el.getBoundingClientRect();
      let boardRect = boardParent.getBoundingClientRect();
      boardParent.scrollTo(
        {
          left: elRect.left - boardRect.left,
          top: elRect.top - boardRect.top,
          behavior: "smooth"
        }
      );
    }

    if (!game || model.state.uiFullscreen || game.moveInProgress) {
      // No game or we're in full screen mode: always 100% scale
      // Also, as soon as a move is being processed by the server, we zoom out
      this.boardScale = 1.0; // Needs to be done before setTimeout() call
      setTimeout(this.resetScale);
      return;
    }
    let tp = game.tilesPlaced();
    let numTiles = tp.length;
    if (numTiles == 1 && this.boardScale == 1.0) {
      // Laying down first tile: zoom in & position
      this.boardScale = 1.5;
      setTimeout(() => scrollIntoView(tp[0]));
    }
    else if (numTiles == 0 && this.boardScale > 1.0) {
      // Removing only remaining tile: zoom out
      this.boardScale = 1.0; // Needs to be done before setTimeout() call
      setTimeout(this.resetScale);
    }
  }

  showUserInfo(userid: string, nick: string, fullname: string) {
    // Show a user info dialog
    this.pushDialog("userinfo", { userid: userid, nick: nick, fullname: fullname });
  }

  showFriendPromo() {
    // Show a friendship promotion
    this.pushDialog("friend", { });
  }

  showThanks() {
    // Show thanks for becoming a friend
    this.pushDialog("thanks", { });
  }

  showFriendCancel() {
    // Show a friendship cancellation dialog
    this.pushDialog("cancel", { });
  }

  showAcceptDialog(oppId: string, oppNick: string, challengeKey: string) {
    this.pushDialog("accept", { oppId, oppNick, challengeKey });
  }

  // Globally available view functions

  vwUserId(): m.vnode | string {
    // User identifier at top right, opens user preferences
    const model = this.model;
    if (model.state.userId == "")
      // Don't show the button if there is no logged-in user
      return "";
    return m(".userid",
      {
        title: ts("player_info"), // "Player information"
        onclick: (ev) => {
          // Overlay the userprefs dialog
          this.pushDialog("userprefs");
          ev.preventDefault();
        }
      },
      [glyph("address-book"), nbsp(), model.state.userNick]
    );
  }

  TogglerReady: ComponentFunc<{}> = (initialVnode) => {
    // Toggle on left-hand side of main screen:
    // User ready and willing to accept challenges

    const model = this.model;

    function toggleFunc(state: boolean) {
      model.state.ready = state;
      model.setUserPref({ ready: state });
    }

    return {
      view: () => {
        return vwToggler(
          "ready", model.state.ready, 2, nbsp(), glyph("thumbs-up"), toggleFunc, true,
          ts("Tek við áskorunum!")
        );
      }
    };
  };

  TogglerReadyTimed: ComponentFunc<{}> = (initialVnode) => {
    // Toggle on left-hand side of main screen:
    // User ready and willing to accept timed challenges

    const model = this.model;

    function toggleFunc(state: boolean) {
      model.state.readyTimed = state;
      model.setUserPref({ ready_timed: state });
    }

    return {
      view: (vnode) => {
        return vwToggler(
          "timed", model.state.readyTimed, 3, nbsp(), glyph("time"), toggleFunc, true,
          ts("Til í viðureign með klukku!")
        );
      }
    };
  };

  vwDialogButton(
    id: string, title: string, func: EventHandler,
    content: VnodeChildren, tabindex: number
  ): m.vnode {
    // Create a .modal-close dialog button
    let attrs: VnodeAttrs = {
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
    let blinkers = document.getElementsByClassName('blinking');
    for (let b of blinkers)
      b.classList.toggle("over");
  }

  Spinner: ComponentFunc<{}> = (initialVnode) => {
    // Show a spinner wait box, after an initial delay
    const INITIAL_DELAY = 800; // milliseconds
    return {
      ival: 0,
      show: false,
      oninit: function (vnode) {
        this.ival = setTimeout(() => {
          this.show = true; this.ival = 0; m.redraw();
        }, INITIAL_DELAY);
      },
      onremove: function (vnode) {
        if (this.ival)
          clearTimeout(this.ival);
        this.ival = 0;
      },
      view: function (vnode) {
        if (!this.show)
          return undefined;
        return m(
          ".modal-dialog",
          { id: 'spinner-dialog', style: { visibility: 'visible' } },
          m("div.animated-spinner",
            m(AnimatedExploLogo, { msStepTime: 200, width: 120, withCircle: true })
          )
        );
      }
    };
  };

  // A control that rigs up a tabbed view of raw HTML

  vwTabsFromHtml(
    html: string, id: string, tabNumber: number, createFunc: (vnode: Vnode) => void
  ): m.vnode | string {
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

  vwHelp(tabNumber: number, faqNumber: number): m.vnode {

    const model = this.model;

    function wireQuestions(vnode: Vnode) {
      // Clicking on a question brings the corresponding answer into view
      // This is achieved by wiring up all contained a[href="#faq-*"] links

      function showAnswer(ev: Event, href: string) {
        // this points to the vnode
        vnode.state.selected = 1; // FAQ tab
        vnode.dom.querySelector(href).scrollIntoView();
        ev.preventDefault();
      }

      const anchors = vnode.dom.querySelectorAll("a");
      for (let anchor of anchors) {
        let href = anchor.getAttribute("href");
        if (href.slice(0, 5) == "#faq-")
          // This is a direct link to a question: wire it up
          anchor.onclick = (ev) => { showAnswer(ev, href); };
      }
      if (faqNumber !== undefined && !isNaN(faqNumber)) {
        // Go to the FAQ tab and scroll the requested question into view
        selectTab(vnode, 1);
        vnode.state.selected = 1; // FAQ tab
        vnode.dom.querySelector("#faq-" + faqNumber.toString()).scrollIntoView();
      }
    }

    // Output literal HTML obtained from rawhelp.html on the server
    return m.fragment({}, [
      m(LeftLogo),
      this.vwUserId(),
      m("main",
        this.vwTabsFromHtml(model.helpHTML, "tabs", tabNumber, wireQuestions)
      )
    ]);
  }

  // User preferences screen

  vwUserPrefsDialog() {

    const model = this.model;
    let user = model.user;
    let err = model.userErrors || {};
    let view = this;

    function vwErrMsg(propname: string) {
      // Show a validation error message returned from the server
      return err.hasOwnProperty(propname) ?
        m(".errinput", [glyph("arrow-up"), nbsp(), err[propname]]) : "";
    }

    function playAudio(elemId: string) {
      // Play an audio file
      const sound = document.getElementById(elemId) as HTMLMediaElement;
      if (sound)
        sound.play();
    }

    function getToggle(elemId: string) {
      let cls2 = document.querySelector("#" + elemId + "-toggler #opt2").classList;
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
          m(".loginhdr", [glyph("address-book"), " " + ts("player_info")]), // "Player information"
          m("div",
            m("form", { action: '', id: 'frm1', method: 'post', name: 'frm1' },
              [
                m(".dialog-spacer",
                  [
                    m("span.caption", t("Einkenni:")),
                    m(TextInput,
                      {
                        initialValue: user.nickname || "",
                        class: "username",
                        maxlength: 15,
                        id: "nickname",
                        // autocomplete: "nickname", // Chrome doesn't like this
                      }
                    ),
                    nbsp(), m("span.asterisk", "*")
                  ]
                ),
                m(".explain", t("Verður að vera útfyllt")),
                vwErrMsg("nickname"),
                m(".dialog-spacer",
                  [
                    m("span.caption", t("Fullt nafn:")),
                    m(TextInput,
                      {
                        initialValue: user.full_name || "",
                        class: "fullname",
                        maxlength: 32,
                        id: "full_name",
                        autocomplete: "name",
                      }
                    )
                  ]
                ),
                m(".explain", t("Valfrjálst - sýnt í notendalistum Netskrafls")),
                vwErrMsg("full_name"),
                m(".dialog-spacer",
                  [
                    m("span.caption", t("Tölvupóstfang:")),
                    m(TextInput,
                      {
                        initialValue: user.email || "",
                        class: "email",
                        maxlength: 32,
                        id: "email",
                        autocomplete: "email",
                      }
                    )
                  ]
                ),
                m(".explain", t("explain_email")),
                vwErrMsg("email"),
                m(".dialog-spacer",
                  [
                    m("span.caption.sub", t("Hljóðmerki:")),
                    vwToggler("audio", user.audio, 4,
                      glyph("volume-off"), glyph("volume-up"),
                      function (state) { if (state) playAudio("your-turn"); }),
                    m("span.subcaption", t("Lúðraþytur eftir sigur:")),
                    vwToggler("fanfare", user.fanfare, 5,
                      glyph("volume-off"), glyph("volume-up"),
                      function (state) { if (state) playAudio("you-win"); })
                  ]
                ),
                m(".explain", t("explain_sound")),
                m(".dialog-spacer",
                  [
                    m("span.caption.sub", t("Sýna reitagildi:")),
                    vwToggler("beginner", user.beginner, 6,
                      nbsp(), glyph("ok")),
                    mt(".subexplain",
                      [
                        "Stillir hvort ",
                        mt("strong", "minnismiði"),
                        " um margföldunargildi reita er sýndur við borðið"
                      ]
                    )
                  ]
                ),
                m(".dialog-spacer",
                  [
                    m("span.caption.sub", t("Án hjálpartækja:")),
                    vwToggler("fairplay", user.fairplay, 8, nbsp(), glyph("edit")),
                    mt(".subexplain",
                      [
                        "no_helpers",
                        mt("strong", "án stafrænna hjálpartækja"),
                        " af nokkru tagi"
                      ]
                    )
                  ]
                )
              ]
            )
          ),
          this.vwDialogButton("user-ok", ts("Vista"), validate, glyph("ok"), 9),
          this.vwDialogButton("user-cancel", ts("Hætta við"),
            (ev) => { this.popDialog(); ev.preventDefault(); },
            glyph("remove"), 10),
          this.vwDialogButton("user-logout", ts("Skrá mig út"),
            (ev) => {
              window.location.href = user.logout_url;
              ev.preventDefault();
            },
            [glyph("log-out"), nbsp(), t("Skrá mig út")], 11),
          user.friend ?
            this.vwDialogButton("user-unfriend", ts("Hætta sem vinur"),
              (ev) => {
                ev.preventDefault();
                view.showFriendCancel()
              },
              [glyph("coffee-cup"), nbsp(), nbsp(), ts("Þú ert vinur Netskrafls!")], 12
            )
            :
            this.vwDialogButton("user-friend", ts("Gerast vinur"),
              (ev) => {
                // Invoke the friend promo dialog
                ev.preventDefault();
                logEvent("click_friend",
                  {
                    userid: model.state.userId, locale: model.state.locale
                  }
                );
                view.showFriendPromo();
              },
              [glyph("coffee-cup"), nbsp(), nbsp(), ts("Gerast vinur Netskrafls")], 12
            )
        ]
      )
    );
  }

  vwUserPrefs(): m.vnode {
    const model = this.model;
    if (model.user === null)
      model.loadUser(true); // Activate spinner while loading
    if (!model.user)
      // Nothing to edit (the spinner should be showing in this case)
      return m.fragment({}, []);
    return this.vwUserPrefsDialog();
  }

  vwUserInfo(args: { userid: string; nick: string; fullname: string; }): m.vnode {
    return m(UserInfoDialog,
      {
        view: this,
        userid: args.userid,
        nick: args.nick,
        fullname: args.fullname
      }
    );
  }

  vwPromo(args: { kind: string; initFunc: () => void; }): m.vnode {
    return m(PromoDialog,
      {
        view: this,
        kind: args.kind,
        initFunc: args.initFunc
      }
    );
  }

  vwFriend(args: {}): m.vnode {
    return m(FriendPromoteDialog,
      {
        view: this,
      }
    );
  }

  vwThanks(args: {}): m.vnode {
    return m(FriendThanksDialog,
      {
        view: this,
      }
    );
  }

  vwCancel(args: {}): m.vnode {
    return m(FriendCancelDialog,
      {
        view: this,
      }
    );
  }

  vwConfirm(args: {}): m.vnode {
    return m(FriendCancelConfirmDialog,
      {
        view: this,
      }
    );
  }

  vwWait(args: {
    oppId: string;
    oppNick: string;
    oppName: string;
    duration: number;
    challengeKey: string;
  }): m.vnode {
    return m(WaitDialog, {
      view: this,
      oppId: args.oppId,
      oppNick: args.oppNick,
      oppName: args.oppName,
      duration: args.duration,
      challengeKey: args.challengeKey,
    });
  }

  vwAccept(args: { oppId: string; oppNick: string; challengeKey: string; }): m.vnode {
    return m(AcceptDialog, {
      view: this,
      oppId: args.oppId,
      oppNick: args.oppNick,
      challengeKey: args.challengeKey,
    });
  }

  ChallengeDialog: ComponentFunc<{ item: UserListItem; }> = (initialVnode) => {
    // Show a dialog box for a new challenge being issued
    const item = initialVnode.attrs.item;
    const model = this.model;
    const state = model.state;
    // TODO
    // const manual = state.hasPaid; // If paying user, allow manual challenges
    const manual = state.plan !== ""; // If subscriber/friend, allow manual challenges
    const fairPlay = item.fairplay && state.fairPlay; // Both users are fair-play
    let manualChallenge = false;
    return {
      view: (vnode) => {
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
                            m(OnlinePresence, { id: "chall-online", userId: item.userid }),
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
                      mt("p", [mt("strong", "Ný áskorun"), " - veldu lengd viðureignar:"]),
                      m(MultiSelection,
                        { initialSelection: 0, defaultClass: 'chall-time' },
                        [
                          m("div", { id: 'chall-none', tabindex: 1 },
                            t("Viðureign án klukku")
                          ),
                          m("div", { id: 'chall-10', tabindex: 2 },
                            [glyph("time"), t("2 x 10 mínútur")]
                          ),
                          m("div", { id: 'chall-15', tabindex: 3 },
                            [glyph("time"), t("2 x 15 mínútur")]
                          ),
                          m("div", { id: 'chall-20', tabindex: 4 },
                            [glyph("time"), t("2 x 20 mínútur")]
                          ),
                          m("div", { id: 'chall-25', tabindex: 5 },
                            [glyph("time"), t("2 x 25 mínútur")]
                          ),
                          state.runningLocal ? // !!! TODO Debugging aid
                            m("div", { id: 'chall-3', tabindex: 6 },
                              [glyph("time"), t("2 x 3 mínútur")]
                            )
                          :
                            m("div", { id: 'chall-30', tabindex: 6 },
                              [glyph("time"), t("2 x 30 mínútur")]
                            )
                        ]
                      )
                    ]
                  ),
                  m(".promo-mobile",
                    [
                      m("p", mt("strong", "Ný áskorun")),
                      m(".chall-time.selected",
                        { id: 'extra-none', tabindex: 1 },
                        t("Viðureign án klukku")
                      )
                    ]
                  )
                ]
              ),
              manual ? m("div", { id: "chall-manual" },
                [
                  mt("span.caption.wide",
                    [
                      "Nota ", mt("strong", "handvirka véfengingu"),
                      m("br"), "(\"keppnishamur\")"
                    ]
                  ),
                  m(".toggler[id='manual-toggler'][tabindex='7']",
                    [
                      m(".option",
                        {
                          className: manualChallenge ? "" : "selected",
                          onclick: () => { manualChallenge = false; }
                        },
                        m("span", nbsp())
                      ),
                      m(".option",
                        {
                          className: manualChallenge ? "selected" : "",
                          onclick: () => { manualChallenge = true; }
                        },
                        glyph("lightbulb")
                      )
                    ]
                  )
                ]
              ) : "",
              fairPlay ? m("div", { id: "chall-fairplay" },
                [
                  t("Báðir leikmenn lýsa því yfir að þeir skrafla "),
                  m("br"),
                  mt("strong", "án stafrænna hjálpartækja"),
                  t(" af nokkru tagi"), "."
                ]
              ) : "",
              m(DialogButton,
                {
                  id: "chall-cancel",
                  title: ts("Hætta við"),
                  tabindex: 8,
                  onclick: (ev: Event) => {
                    this.popDialog();
                    ev.preventDefault();
                  }
                },
                glyph("remove")
              ),
              m(DialogButton,
                {
                  id: "chall-ok",
                  title: ts("Skora á"),
                  tabindex: 9,
                  onclick: (ev: Event) => {
                    // Issue a new challenge
                    let duration: string | number =
                      document.querySelector("div.chall-time.selected").id.slice(6);
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
                        manual: manualChallenge
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
    }
  };

  vwChallenge(item: UserListItem) : m.vnode {
    return m(this.ChallengeDialog, { item: item });
  }

  // Main screen

  vwMain(): m.vnode {
    // Main screen with tabs

    const view = this;
    const model = this.model;

    function vwMainTabs() {

      function vwMainTabHeader(): m.vnode[] {
        const numGames = model.numGames;
        const numChallenges = model.numChallenges;
        return [
          m(".header-logo",
            m(m.route.Link,
              {
                href: "/page",
                class: "backlink"
              },
              m(ExploLogo, { legend: false, scale: 1.0 })
            )
          ),
          m("ul", [
            m("li",
              m("a[href='#tabs-1']", [
                glyph("th"), m("span.tab-legend", t("Viðureignir")),
                m("span",
                  {
                    id: 'numgames',
                    style: numGames ? 'display: inline-block' : ''
                  },
                  numGames
                )
              ])
            ),
            m("li",
              m("a[href='#tabs-2']", [
                glyph("hand-right"), m("span.tab-legend", t("Áskoranir")),
                // Blink if we have timed games where the opponent is ready
                m("span" + (model.oppReady ? ".opp-ready" : ""),
                  {
                    id: "numchallenges",
                    style: numChallenges ? 'display: inline-block' : ''
                  },
                  numChallenges
                )
              ])
            ),
            m("li",
              m("a[href='#tabs-3']",
                [glyph("user"), m("span.tab-legend", t("Andstæðingar"))]
              )
            ),
            m("li.no-mobile-list",
              m("a[href='#tabs-4']",
                [glyph("bookmark"), m("span.tab-legend", t("Ferill"))]
              )
            )
          ])
        ];
      }

      function showUserInfo(userid: string, nick: string, fullname: string) {
        view.pushDialog("userinfo", { userid: userid, nick: nick, fullname: fullname });
      }

      function vwGamelist(): m.vnode[] {

        function vwList(): m.vnode {

          function viewGameList(): m.vnode[] | string {

            if (!model.gameList)
              return "";
            return model.gameList.map((item, i: number) => {

              // Show a list item about a game in progress (or recently finished)

              function vwOpp(): m.vnode {
                let arg = item.oppid === null ? [glyph("cog"), nbsp(), item.opp] : item.opp;
                return m("span.list-opp", { title: item.fullname }, arg);
              }

              function vwTurn(): m.vnode {
                let turnText = "";
                let flagClass = "";
                if (item.my_turn) {
                  turnText = ts("Þú átt leik");
                }
                else
                  if (item.zombie) {
                    turnText = ts("Viðureign lokið");
                    flagClass = ".zombie";
                  }
                  else {
                    // {opponent}'s move
                    turnText = ts("opp_move", { opponent: item.opp });
                    flagClass = ".grayed";
                  }
                return m("span.list-myturn",
                  m("span.glyphicon.glyphicon-flag" + flagClass, { title: turnText })
                );
              }

              function vwOverdue(): m.vnode {
                if (item.overdue)
                  return glyph("hourglass",
                    { title: item.my_turn ? "Er að renna út á tíma" : "Getur þvingað fram uppgjöf" }
                  );
                return glyphGrayed("hourglass");
              }

              function vwTileCount(): m.vnode {
                const winLose = item.sc0 < item.sc1 ? ".losing" : "";
                return m(".tilecount",
                  m(".tc" + winLose, { style: { width: item.tile_count.toString() + "%" } })
                );
              }

              return m(".listitem" + (i % 2 === 0 ? ".oddlist" : ".evenlist"),
                [
                  m(m.route.Link,
                    { href: gameUrl(item.url) },
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
                          title: ts("Skoða feril"),
                          onclick: (ev) => {
                            // Show opponent track record
                            ev.preventDefault();
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
                    item.manual
                    ? glyph("lightbulb", { title: ts("Keppnishamur") })
                    : glyphGrayed("lightbulb")
                  )
                ]
              );
            });
          }

          if (model.gameList === null)
            model.loadGameList();
          return m("div", { id: 'gamelist' }, viewGameList());
        }

        function vwHint(): m.vnode {
          // Show some help if the user has no games in progress
          if (model.loadingGameList || model.gameList === undefined ||
            (model.gameList !== null && model.gameList.length > 0))
            // Either we have games in progress or the game list is being loaded
            return undefined;
          return m(".hint", { style: { display: "block" } },
            [
              m("p",
                [
                  "Ef þig vantar einhvern til að skrafla við, veldu flipann ",
                  m(m.route.Link,
                    { href: "/main?tab=2" },
                    [glyph("user"), nbsp(), "Andstæðingar"]
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
              m("span.list-myturn", glyphGrayed("flag", { title: ts('Átt þú leik?') })),
              m("span.list-overdue",
                glyphGrayed("hourglass", { title: ts('Langt frá síðasta leik?') })
              ),
              mt("span.list-ts-short", "Síðasti leikur"),
              mt("span.list-opp", "Andstæðingur"),
              mt("span.list-info-hdr", "Ferill"),
              mt("span.list-scorehdr", "Staða"),
              mt("span.list-tc", "Framvinda"),
              m("span.list-manual", glyphGrayed("lightbulb", { title: ts('Keppnishamur') }))
            ]
          ),
          vwList(),
          vwHint()
        ];
      }

      function vwChallenges(showReceived: boolean): m.vnode[] {

        function vwList() {

          function itemize(item: ChallengeListItem, i: number) {

            // Generate a list item about a pending challenge (issued or received)

            function challengeDescription(json: { duration?: number; }) {
              /* Return a human-readable string describing a challenge
                 according to the enclosed preferences */
              if (!json || json.duration === undefined || json.duration === 0)
                /* Normal unbounded (untimed) game */
                return t("Venjuleg ótímabundin viðureign");
              return t("with_clock", { duration: json.duration.toString() });
            }

            function markChallenge(ev: Event) {
              // Clicked the icon at the beginning of the line,
              // to decline a received challenge or retract an issued challenge
              const action: ChallengeAction = item.received ? "decline" : "retract";
              const param = { destuser: item.userid, action: action, key: item.key };
              model.modifyChallenge(param);
              ev.preventDefault();
            }

            function clickChallenge(ev: Event) {
              // Clicked the hotspot area to accept a received challenge
              ev.preventDefault();
              if (!model.moreGamesAllowed()) {
                // User must be a friend to be able to accept more challenges
                logEvent("hit_game_limit",
                  {
                    userid: model.state.userId,
                    locale: model.state.locale,
                    limit: model.maxFreeGames
                  }
                );
                // Promote a subscription to Netskrafl/Explo
                view.showFriendPromo();
                return;
              }
              if (item.received) {
                if (item.prefs && item.prefs.duration !== undefined && item.prefs.duration > 0)
                  // Timed game: display a modal wait dialog
                  view.pushDialog("wait", {
                    oppId: item.userid,
                    oppNick: item.opp,
                    oppName: item.fullname,
                    duration: item.prefs.duration,
                    challengeKey: item.key,
                  });
                else
                  // Ask the server to create a new game and route to it
                  model.newGame(item.userid, false);
              }
              else {
                // Clicking on a sent challenge, i.e. a timed game
                // where the opponent is waiting and ready to start
                view.showAcceptDialog(item.userid, item.opp, item.key);
              }
            }

            const oppReady = !item.received && item.opp_ready &&
              item.prefs && item.prefs.duration !== undefined &&
              item.prefs.duration > 0;
            const clickable = item.received || oppReady;
            const descr = challengeDescription(item.prefs);

            return m(".listitem" + (i % 2 === 0 ? ".oddlist" : ".evenlist"),
              [
                m("span.list-icon",
                  { onclick: markChallenge },
                  item.received ?
                    glyph("thumbs-down", { title: ts("Hafna") })
                    :
                    glyph("hand-right", { title: ts("Afturkalla") })
                ),
                m(clickable ? "a" : "span",
                  clickable ? {
                    href: "#",
                    onclick: clickChallenge,
                    class: oppReady ? "opp-ready" : ""
                  } : {},
                  [
                    m("span.list-ts", item.ts),
                    m("span.list-nick", { title: item.fullname }, item.opp),
                    m("span.list-chall",
                      [
                        item.prefs.fairplay ? m("span.fairplay-btn", { title: ts("Án hjálpartækja") }) : "",
                        item.prefs.manual ? m("span.manual-btn", { title: ts("Keppnishamur") }) : "",
                        descr
                      ]
                    )
                  ]
                ),
                m("span.list-info",
                  {
                    title: ts("Skoða feril"),
                    // Show opponent track record
                    onclick: (ev) => {
                      ev.preventDefault();
                      showUserInfo(item.userid, item.opp, item.fullname);
                    }
                  },
                  m("span.usr-info", "")
                ),
              ]
            );
          }

          let cList: ChallengeListItem[] = [];
          if (model.challengeList)
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
                m("span.list-icon", glyphGrayed("thumbs-down", { title: ts('Hafna') })),
                mt("span.list-ts", "Hvenær"),
                mt("span.list-nick", "Áskorandi"),
                mt("span.list-chall", "Hvernig"),
                mt("span.list-info-hdr", "Ferill"),
              ]
            ),
            vwList()
          ];
        else
          // Challenges sent
          return [
            m(".listitem.listheader",
              [
                m("span.list-icon", glyphGrayed("hand-right", { title: ts('Afturkalla') })),
                mt("span.list-ts", "Hvenær"),
                mt("span.list-nick", "Andstæðingur"),
                mt("span.list-chall", "Hvernig"),
                mt("span.list-info-hdr", "Ferill"),
              ]
            ),
            vwList()
          ];
      }

      function vwRecentList(): m.vnode[] {

        function vwList(): m.vnode {
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
              m("span.list-win", glyphGrayed("bookmark", { title: ts('Sigur') })),
              mt("span.list-ts-short", "Viðureign lauk"),
              mt("span.list-nick", "Andstæðingur"),
              mt("span.list-scorehdr", "Úrslit"),
              m("span.list-elo-hdr",
                [
                  m("span.glyphicon.glyphicon-user.elo-hdr-left", { title: ts('Mennskir andstæðingar') }),
                  t("Elo"),
                  m("span.glyphicon.glyphicon-cog.elo-hdr-right", { title: ts('Allir andstæðingar') })
                ]
              ),
              mt("span.list-duration", "Lengd"),
              m("span.list-manual", glyphGrayed("lightbulb", { title: ts('Keppnishamur') }))
            ]
          ),
          vwList()
        ];
      }

      function vwUserButton(id: string, icon: string, text: string): m.vnode {
        // Select the type of user list (robots, fav, alike, elo)
        const sel = model.userListCriteria ? model.userListCriteria.query : "robots";
        const spec = (id == "elo") ? "human" : "";
        return m("span",
          {
            className: (id == sel ? "shown" : ""),
            id: id,
            onclick: (ev) => {
              model.loadUserList({ query: id, spec: spec }, true);
              ev.preventDefault();
            }
          },
          [glyph(icon, { style: { padding: 0 } }), nbsp(), text]
        );
      }

      function vwUserList(): m.vnode[] {

        function vwList(list: UserListItem[]) {

          function itemize(item: UserListItem, i: number) {

            // Generate a list item about a user

            const isRobot = item.userid.indexOf("robot-") === 0;
            let fullname: VnodeChildren = [];

            // Online and accepting challenges
            if (item.ready && !isRobot) {
              fullname.push(m("span.ready-btn", { title: ts("Álínis og tekur við áskorunum") }));
              fullname.push(nbsp());
            }
            // Willing to accept challenges for timed games
            if (item.ready_timed) {
              fullname.push(m("span.timed-btn", { title: ts("Til í viðureign með klukku") }));
              fullname.push(nbsp());
            }
            // Fair play commitment
            if (item.fairplay) {
              fullname.push(m("span.fairplay-btn", { title: ts("Skraflar án hjálpartækja") }));
              fullname.push(nbsp());
            }
            fullname.push(item.fullname);

            function fav(): m.vnode {
              if (isRobot)
                return m("span.list-fav", { style: { cursor: "default" } }, glyph("star-empty"));
              return m("span.list-fav",
                {
                  title: ts("Uppáhald"),
                  onclick: (ev) => {
                    item.fav = !item.fav;
                    model.markFavorite(item.userid, item.fav);
                    ev.preventDefault();
                  }
                },
                glyph(item.fav ? "star" : "star-empty")
              );
            }

            function modifyChallenge() {
              if (item.chall) {
                // Retracting challenge
                item.chall = false;
                // Note: the effect of this is to retract all challenges
                // that this user has issued to the destination user
                model.modifyChallenge({ destuser: item.userid, action: "retract" });
              }
              else if (isRobot) {
                  // Challenging a robot: game starts immediately
                  model.newGame(item.userid, false);
              } else {
                  // Challenging a user: show a challenge dialog
                  view.pushDialog("challenge", item);
              }
            }

            function userLink(): m.vnode {
              if (isRobot)
                return m("a",
                  {
                    href: "",
                    onclick: (ev) => {
                      // Start a new game against the robot
                      model.newGame(item.userid, false);
                      ev.preventDefault();
                    }
                  },
                  [
                    m("span.list-nick", [glyph("cog"), nbsp(), item.nick]),
                    m("span.list-fullname-robot", fullname)
                  ]
                );
              else
                return m.fragment({}, [
                  m("span.list-nick", item.nick),
                  m("span.list-fullname", fullname),
                  m("span.list-human-elo", item.human_elo)
                ]);
            }

            return m(".listitem" + (i % 2 === 0 ? ".oddlist" : ".evenlist"),
              [
                m("span.list-ch",
                  {
                    title: ts("Skora á"),
                    onclick: (ev) => {
                      modifyChallenge();
                      ev.preventDefault();
                    }
                  },
                  glyph("hand-right", undefined, !item.chall)
                ),
                fav(),
                userLink(),
                m("span.list-info",
                  {
                    title: ts("Skoða feril"),
                    onclick: (ev) => {
                      ev.preventDefault();
                      showUserInfo(item.userid, item.nick, item.fullname);
                    }
                  },
                  isRobot ? "" : m("span.usr-info")
                )
              ]
            );
          }

          return m("div", { id: "userlist" }, list.map(itemize));
        }

        // The type of list to show; by default it's 'robots'
        const listType = model.userListCriteria ? model.userListCriteria.query : "robots";
        if (listType == "elo")
          // Show Elo list
          return [ m(EloPage, { id: "elolist", view: view }) ];
        // Show normal user list
        let list: UserListItem[] = [];
        if (model.userList === undefined) {
          // We are loading a fresh user list
          /* pass */
        }
        else
        if (model.userList === null || model.userListCriteria.query != listType)
          model.loadUserList({ query: listType, spec: "" }, true);
        else
          list = model.userList;
        const nothingFound = list.length === 0 && model.userListCriteria !== undefined &&
          listType == "search" && model.userListCriteria.spec !== "";
        const robotList = listType == "robots";
        return [
          m(".listitem.listheader",
            [
              m("span.list-ch", glyphGrayed("hand-right", { title: ts('Skora á') })),
              m("span.list-fav", glyph("star-empty", { title: ts('Uppáhald') })),
              mt("span.list-nick", "Einkenni"),
              mt("span.list-fullname", "Nafn og merki"),
              robotList ? "" : mt("span.list-human-elo[id='usr-list-elo']", "Elo"),
              robotList ? "" : mt("span.list-info-hdr[id='usr-list-info']", "Ferill"),
            ]
          ),
          vwList(list),
          // Show indicator if search didn't find any users matching the criteria
          nothingFound ?
            m("div",
              { id: "user-no-match", style: { display: "block" } },
              [
                glyph("search"),
                " ",
                m("span", { id: "search-prefix" }, model.userListCriteria.spec),
                t(" finnst ekki")
              ]
            )
            : undefined
        ];
      }

      function vwStats(): m.vnode {
        // View the user's own statistics summary
        const ownStats = model.ownStats;
        if (model.ownStats === null)
          model.loadOwnStats();
        return m(StatsDisplay, { id: 'own-stats', ownStats: ownStats });
      }

      function vwBest(): m.vnode {
        // View the user's own best game and word scores
        const ownStats = model.ownStats;
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
                mt("p.no-mobile-block",
                  [
                    mt("strong", "Viðureignir sem standa yfir"),
                    "click_on_game", // "Click on a game to view it and make a move if"
                    glyph("flag"),
                    " þú átt leik"
                  ]
                ),
                vwGamelist()
              ]
            ),
            m("div", { id: 'tabs-2' },
              [
                mt("p.no-mobile-block",
                  [
                    mt("strong", "Skorað á þig"),
                    "click_on_challenge", // "Click on a challenge to accept it and start a game, or on"
                    glyph("thumbs-down", { style: { "margin-left": "6px", "margin-right": "6px" } }),
                    " til að hafna henni"
                  ]
                ),
                vwChallenges(true),
                mt("p.no-mobile-block",
                  [
                    mt("strong", "Þú skorar á aðra"),
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
                mt("p.no-mobile-block",
                  [
                    mt("strong", "Nýlegar viðureignir þínar"),
                    "click_to_review" // "Click on a game to review it"
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
                        vwUserButton("robots", "cog", ts("Þjarkar")),
                        " ",
                        vwUserButton("fav", "star", ts("Uppáhalds")),
                        " ",
                        vwUserButton("live", "flash", ts("Álínis")),
                        " ",
                        vwUserButton("alike", "resize-small", ts("Svipaðir")),
                        " ",
                        vwUserButton("elo", "crown", ts("Topp 100"))
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

    return m.fragment({}, [
      m(LeftLogo), // No legend, scale up by 50%
      this.vwUserId(),
      m(Info),
      m(this.TogglerReady),
      m(this.TogglerReadyTimed),
      m("main",
        m("div",
          {
            oncreate: (vnode) => {
              this.makeTabs("main-tabs", undefined, false, vnode);
            },
            onupdate: updateSelection
          },
          vwMainTabs()
        )
      )
    ]);
  }

  vwPlayerName(side: string) {
    // Displays a player name, handling both human and robot players
    // as well as left and right side, and local and remote colors
    const view = this;
    const state = this.model.state;
    const game = this.model.game;
    let apl0 = game && game.autoplayer[0];
    let apl1 = game && game.autoplayer[1];
    let nick0 = game ? game.nickname[0] : "";
    let nick1 = game ? game.nickname[1] : "";
    let player: number = game ? game.player : 0;
    let localturn: boolean = game ? game.localturn : false;
    let tomove: string;
    let gameover = game ? game.over : true;

    function lookAtPlayer(ev: Event, player: number, side: number) {
      if (!state.uiFullscreen)
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
        return m(".robot-btn.left", [glyph("cog"), nbsp(), nick0]);
      tomove = gameover || (localturn !== (player === 0)) ? "" : ".tomove";
      return m((player === 0 || player === 1) ? ".player-btn.left" + tomove : ".robot-btn.left",
        { id: "player-0", onclick: (ev) => lookAtPlayer(ev, player, 0) },
        [m("span.left-to-move"), nick0]
      );
    }
    else {
      // Right side player
      if (apl1)
        // Player 1 is a robot (autoplayer)
        return m(".robot-btn.right", [glyph("cog"), nbsp(), nick1]);
      tomove = gameover || (localturn !== (player === 1)) ? "" : ".tomove";
      return m((player === 0 || player === 1) ? ".player-btn.right" + tomove : ".robot-btn.right",
        { id: "player-1", onclick: (ev) => lookAtPlayer(ev, player, 1) },
        [m("span.right-to-move"), nick1]
      );
    }
  }

  vwTwoLetter: ComponentFunc<{}> = (initialVnode) => {

    // The two-letter-word list tab
    const model = this.model;
    let page = 0;

    function renderWord(bold: boolean, w: string): m.vnode {
      // For the first two-letter word in each group,
      // render the former letter in bold
      if (!bold)
        return m(".twoletter-word", w);
      if (page == 0)
        return m(".twoletter-word", [m("b", w[0]), w[1]]);
      else
        return m(".twoletter-word", [w[0], m("b", w[1])]);
    }

    return {
      view: (vnode) => {
        const game = model.game;
        const twoLetters = game.twoLetterWords();
        const twoLetterWords = twoLetters[page];
        let twoLetterList = [];
        for (let tw of twoLetterWords) {
          let twl = tw[1];
          let sublist: m.vnode[] = [];
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
          m(".twoletter-area" + (game.showClock() ? ".with-clock" : ""),
            {
              title: page == 0 ?
                ts("Smelltu til að raða eftir seinni staf") :
                ts("Smelltu til að raða eftir fyrri staf")
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
    s.showMoveMobile = false; // Versatile move button for mobile UI
    s.showForceResignMobile = false; // Force resignation button for mobile UI
    s.showChallenge = false;
    s.showChallengeInfo = false;
    if (game.moveInProgress)
      // While a move is in progress (en route to the server)
      // no buttons are shown
      return s;
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
      if (s.tilesPlaced) {
        s.showRecall = true;
        s.showMoveMobile = true;
      } else {
        s.showScramble = true;
        if (s.tardyOpponent)
          // Not showing the move button: show the Force resignation button
          s.showForceResignMobile = true;
      }
    return s;
  }

  // Game screen

  vwGame() {
    // A view of a game, in-progress or finished

    const view = this;
    const model = this.model;
    const game = model.game;
    const state = model.state;

    function vwBeginner() {
      // Show the board color guide
      return m(".board-help",
        { title: ts("Hvernig reitirnir margfalda stigin") },
        [
          m(".board-help-close",
            {
              title: ts("Loka þessari hjálp"),
              onclick: (ev) => {
                // Close the guide and set a preference not to see it again
                state.beginner = false;
                model.setUserPref({ beginner: false });
                ev.preventDefault();
              }
            },
            glyph("remove")
          ),
          m(".board-colors",
            [
              m(".board-color[id='triple-word']", ["3 x", m("br"), t("orð")]),
              m(".board-color[id='double-word']", ["2 x", m("br"), t("orð")]),
              m(".board-color[id='triple-letter']", ["3 x", m("br"), t("stafur")]),
              m(".board-color[id='double-letter']", ["2 x", m("br"), t("stafur")]),
              m(".board-color[id='single-letter']", ["1 x", m("br"), t("stafur")])
            ]
          )
        ]
      );
    }

    function vwRightColumn() {
      // A container for the right-side header and area components

      function vwClock() {
        // Show clock data if this is a timed game
        if (!game.showClock())
          // Not a timed game, or a game that is completed
          return m.fragment({}, []);

        function vwClockFace(cls: string, txt: string, runningOut: boolean, blinking: boolean): m.vnode {
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

        const fairplay = game ? game.fairplay : false;
        const player = game ? game.player : 0;
        const sc0 = game ? game.displayScore(0).toString() : "";
        const sc1 = game ? game.displayScore(1).toString() : "";
        return m(".heading",
          [
            // The header-logo is not displayed in fullscreen
            m(".logowrapper",
              m(".header-logo",
                m(m.route.Link,
                  {
                    href: "/page",
                    class: "backlink"
                  },
                  m(ExploLogo, { legend: false, scale: 1.0 })
                )
              )
            ),
            m(".playerwrapper", [
              m(".leftplayer" + (player == 1 ? ".autoplayercolor" : ".humancolor"), [
                m(".player", view.vwPlayerName("left")),
                m(".scorewrapper", m(".scoreleft", sc0)),
              ]),
              m(".rightplayer" + (player == 1 ? ".humancolor" : ".autoplayercolor"), [
                m(".player", view.vwPlayerName("right")),
                m(".scorewrapper", m(".scoreright", sc1)),
              ]),
              m(".fairplay",
                { style: { visibility: fairplay ? "visible" : "hidden" } },
                m("span.fairplay-btn.large", { title: ts("Skraflað án hjálpartækja") })
              )
            ]),
            vwClock(),
          ]
        );
      }

      function vwRightArea(): m.vnode {
        // A container for the tabbed right-side area components
        const sel = game?.sel || "movelist";
        // Show the chat tab unless the opponent is an autoplayer
        let component: m.vnode = null;
        switch (sel) {
          case "movelist":
            component = view.vwMovelist();
            break;
          case "twoletter":
            component = m(view.vwTwoLetter, { game: game });
            break;
          case "chat":
            component = view.vwChat();
            break;
          case "games":
            component = view.vwGames();
            break;
          default:
            break;
        }
        const tabgrp = view.vwTabGroup();
        return m(".right-area" + (game.showClock() ? ".with-clock" : ""),
          component ? [tabgrp, component] : [tabgrp]
        );
      }

      function vwRightMessage(): m.vnode {
        // Display a status message in the mobile UI
        let s = view.buttonState(game);
        let msg: string | any[] = "";
        let player = game.player;
        let opp = game.nickname[1 - player];
        let move = game.moves.length ? game.moves[game.moves.length - 1] : undefined;
        let mtype = move ? move[1][1] : undefined;
        if (s.congratulate) {
          // This player won
          if (mtype == "RSGN")
            msg = [m("strong", [opp, " resigned!"]), " Congratulations."];
          else
            msg = [m("strong", ["You beat ", opp, "!"]), " Congratulations."];
        } else if (s.gameOver) {
          // This player lost
          msg = "Game over!";
        } else if (!s.localTurn) {
          // It's the opponent's turn
          msg = ["It's ", opp, "'s turn. Plan your next move!"];
        } else if (s.tilesPlaced > 0) {
          if (game.currentScore === undefined) {
            if (move === undefined)
              msg = ["Your first move must cover the ", glyph("target"), " start square."];
            else
              msg = "Tiles must be consecutive.";
          } else if (game.wordGood === false) {
            msg = ["Move is not valid, but would score ", m("strong", game.currentScore.toString()), " points."];
          } else {
            msg = ["Valid move, score ", m("strong", game.currentScore.toString()), " points."];
          }
        } else if (move === undefined) {
          // Initial move
          msg = [m("strong", "You start!"), " Cover the ", glyph("star"), " asterisk with your move."];
        }
        else {
          let co = move[1][0];
          let tiles = mtype;
          let score = move[1][2];
          if (co == "") {
            // Not a regular tile move
            if (tiles == "PASS")
              msg = [opp, " passed."];
            else if (tiles.indexOf("EXCH") === 0) {
              const numtiles = tiles.slice(5).length;
              msg = [
                opp, " exchanged ",
                numtiles.toString(),
                (numtiles == 1 ? " tile" : " tiles"),
                "."
              ];
            } else if (tiles == "CHALL") {
              msg = [opp, " challenged your move."];
            } else if (tiles == "RESP") {
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

      return m(".rightcol", [
        vwRightHeading(),
        vwRightArea(),
        /* vwRightMessage(), */
      ]);
    }

    if (game === undefined || game === null)
      // No associated game
      return m("div", [m("main", m(".game-container")), m(LeftLogo)]);

    const bag = game.bag;
    const newbag = game.newbag;
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
          const from = ev.dataTransfer.getData("text");
          // Move to the first available slot in the rack
          game.attemptMove(from, "R1");
          this.updateScale(game);
          return false;
        }
      },
      [
        // The main game area
        m("main",
          m(".game-container",
            [
              vwRightColumn(),
              m(this.BoardArea),
              // The bag is visible in fullscreen
              state.uiFullscreen ? m(this.Bag, { bag: bag, newbag: newbag }) : "",
              game.askingForBlank ? m(this.BlankDialog) : ""
            ]
          )
        ),
        // The left margin stuff: back button, square color help, info/help button
        m(LeftLogo),
        state.beginner ? vwBeginner() : "",
        m(Info)
      ]
    );
  }

  // Review screen

  vwReview(): m.vnode {
    // A review of a finished game

    const view = this;
    const model = this.model;
    const game = model.game;
    const state = model.state;
    let moveIndex = model.reviewMove;
    let bestMoves = model.bestMoves || [];

    function vwRightColumn(): m.vnode {
      // A container for the right-side header and area components

      function vwRightHeading(): m.vnode {
        // The right-side heading on the game screen

        const fairplay = game.fairplay;
        const player = game.player;
        let sc0 = "";
        let sc1 = "";
        if (moveIndex) {
          let s0 = 0;
          let s1 = 0;
          for (let i = 0; i < moveIndex; i++) {
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
          [
            m(".playerwrapper", [
              m(".leftplayer" + (player == 1 ? ".autoplayercolor" : ".humancolor"), [
                m(".player", view.vwPlayerName("left")),
                m(".scorewrapper", m(".scoreleft", sc0)),
              ]),
              m(".rightplayer" + (player == 1 ? ".humancolor" : ".autoplayercolor"), [
                m(".player", view.vwPlayerName("right")),
                m(".scorewrapper", m(".scoreright", sc1)),
              ]),
              m(".fairplay",
                { style: { visibility: fairplay ? "visible" : "hidden" } },
                m("span.fairplay-btn.large", { title: ts("Skraflað án hjálpartækja") }))
            ])
          ]
        );
      }

      function vwRightArea(): m.vnode {
        // A container for the list of best possible moves
        return m(".right-area", view.vwBestMoves(moveIndex, bestMoves));
      }

      return m(".rightcol", [vwRightHeading(), vwRightArea()]);
    }

    if (game === undefined || game === null)
      // No associated game
      return m("div", [m("main", m(".game-container")), m(LeftLogo)]);

    // Create a list of major elements that we're showing
    let r: m.vnode[] = [];
    r.push(vwRightColumn());
    r.push(m(this.BoardReview, { moveIndex: moveIndex }));
    if (moveIndex === 0)
      // Only show the stats overlay if moveIndex is 0
      r.push(this.vwStatsReview());
    return m("div", // Removing this div messes up Mithril
      [
        m("main", m(".game-container", r)),
        m(LeftLogo), // Button to go back to main screen
        m(Info) // Help button
      ]
    );
  }

  vwTabGroup(): m.vnode {
    // A group of clickable tabs for the right-side area content
    const game = this.model.game;
    let showchat = game ? !(game.autoplayer[0] || game.autoplayer[1]) : false;
    let r: m.vnode[] = [
      this.vwTab("board", ts("Borðið"), "grid"),
      this.vwTab("movelist", ts("Leikir"), "show-lines"),
      this.vwTab("twoletter", ts("Tveggja stafa orð"), "life-preserver"),
      this.vwTab("games", ts("Viðureignir"), "flag")
    ];
    if (showchat) {
      // Add chat tab
      r.push(this.vwTab("chat", ts("Spjall"), "conversation",
        () => {
          // The tab has been clicked
          if (game.markChatShown())
            // ...and now the user has seen all chat messages up until now
            m.redraw();
        },
        // Show chat icon in red if any chat messages have not been seen
        // and the chat tab is not already selected
        !game.chatSeen && game.sel != "chat")
      );
    }
    return m.fragment({}, r);
  }

  vwTab(tabid: string, title: string, icon: string, funcSel?: () => void, alert?: boolean) {
    // A clickable tab for the right-side area content
    const game = this.model.game;
    const sel = game?.sel || "movelist";
    return m(".right-tab" + (sel == tabid ? ".selected" : ""),
      {
        id: "tab-" + tabid,
        className: alert ? "alert" : "",
        title: title,
        onclick: (ev) => {
          // Select this tab
          if (game && game.showingDialog === null) {
            if (game.setSelectedTab(tabid)) {
              // A new tab was actually selected
              if (funcSel !== undefined) {
                funcSel();
              }
              if (tabid == "movelist")
                setTimeout(this.scrollMovelistToBottom);
            }
          }
          ev.preventDefault();
        }
      },
      glyph(icon)
    );
  }

  vwChat(): m.vnode {
    // The chat tab

    const view = this;
    const model = this.model;
    const game = model.game;

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

    function makeTimestamp(ts: string, key: number): m.vnode {
      // Decode the ISO format timestamp we got from the server
      let dtTs = dateFromTimestamp(ts);
      let result: m.vnode = null;
      if (dtLastMsg === null || timeDiff(dtLastMsg, dtTs) >= 5 * 60) {
        // If 5 minutes or longer interval between messages,
        // insert a time
        const ONE_DAY = 24 * 60 * 60 * 1000; // 24 hours expressed in milliseconds
        const dtNow = new Date().getTime();
        let dtToday = dtNow - dtNow % ONE_DAY; // Start of today (00:00 UTC)
        let dtYesterday = dtToday - ONE_DAY; // Start of yesterday
        let strTs: string;
        if (dtTs < dtYesterday) {
          // Older than today or yesterday: Show full timestamp YYYY-MM-DD HH:MM
          strTs = ts.slice(0, -3);
        } else if (dtTs < dtToday) {
          // Yesterday
          strTs = "Í gær " + ts.substr(11, 5);
        } else {
          // Today
          strTs = ts.substr(11, 5);
        }
        result = m(".chat-ts", { key: key }, strTs);
      }
      dtLastMsg = dtTs;
      return result;
    }

    const player = game ? game.player : 0;

    function replaceEmoticons(str: string): string {
      // Replace all emoticon shortcuts in the string str with a corresponding image URL
      const emoticons = model.state.emoticons;
      for (const emoticon of emoticons)
        if (str.indexOf(emoticon.icon) >= 0) {
          // The string contains the emoticon: prepare to replace all occurrences
          let img = "<img src='" + emoticon.image + "' height='32' width='32'>";
          // Re the following trick, see https://stackoverflow.com/questions/1144783/
          // replacing-all-occurrences-of-a-string-in-javascript
          str = str.split(emoticon.icon).join(img);
        }
      return str;
    }

    function chatMessages(): m.vnode[] {
      let r: m.vnode[] = [];
      if (game?.chatLoading || !game.messages)
        return r;
      var key = 0;
      for (const msg of game.messages) {
        let p = player;
        if (msg.from_userid != model.state.userId)
          p = 1 - p;
        const mTs = makeTimestamp(msg.ts, key);
        if (mTs !== null) {
          r.push(mTs);
          key++;
        }
        let escMsg = escapeHtml(msg.msg);
        escMsg = replaceEmoticons(escMsg);
        r.push(m(".chat-msg" +
          (p === 0 ? ".left" : ".right") +
          (p === player ? ".local" : ".remote"),
          { key: key++ },
          m.trust(escMsg))
        );
      }
      return r;
    }

    function scrollChatToBottom() {
      // Scroll the last chat message into view
      const chatlist = document.querySelectorAll("#chat-area .chat-msg");
      if (!chatlist.length)
        return;
      const target: HTMLElement = chatlist[chatlist.length - 1] as HTMLElement;
      (target.parentNode as HTMLElement).scrollTop = target.offsetTop;
    }

    function focus(vnode: Vnode) {
      // Put the focus on the DOM object associated with the vnode
      if (!view.isDialogShown())
        // Don't hijack the focus from a dialog overlay
        vnode.dom.focus();
    }

    function sendMessage() {
      let msg = getInput("msg").trim();
      if (game && msg.length > 0) {
        game.sendMessage(msg);
        setInput("msg", "");
      }
    }

    const numMessages = game?.messages ? game.messages.length : 0;

    return m(".chat",
      {
        style: "z-index: 6" // Appear on top of board on mobile
        // key: uuid
      },
      [
        m(".chat-area" + (game.showClock() ? ".with-clock" : ""),
          {
            id: 'chat-area',
            // Make sure that we see the bottom-most chat message
            oncreate: scrollChatToBottom,
            onupdate: scrollChatToBottom
          },
          chatMessages()
        ),
        m(".chat-input",
          [
            m("input.chat-txt",
              {
                type: "text",
                id: "msg",
                name: "msg",
                maxlength: 254,
                disabled: (numMessages >= MAX_CHAT_MESSAGES),
                oncreate: (vnode) => { focus(vnode); },
                onupdate: (vnode) => { focus(vnode); },
                onkeypress: (ev: KeyboardEvent) => {
                  if (ev.key == "Enter") { sendMessage(); ev.preventDefault(); }
                }
              }
            ),
            m(DialogButton,
              {
                id: "chat-send",
                title: ts("Senda"),
                onclick: (ev: Event) => { sendMessage(); ev.preventDefault(); }
              },
              glyph("chat")
            )
          ]
        )
      ]
    );
  }

  vwMovelist(): m.vnode {
    // The move list tab

    const view = this;
    const model = this.model;
    const game = model.game;
    const state = model.state;

    function movelist(): m.vnode[] {
      let mlist = game ? game.moves : []; // All moves made so far in the game
      let r: m.vnode[] = [];
      let leftTotal = 0;
      let rightTotal = 0;
      for (let i = 0; i < mlist.length; i++) {
        let move = mlist[i];
        let [player, [co, tiles, score]] = move;
        if (player === 0)
          leftTotal = Math.max(leftTotal + score, 0);
        else
          rightTotal = Math.max(rightTotal + score, 0);
        r.push(
          view.vwMove(move,
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

    let bag = game ? game.bag : "";
    let newbag = game ? game.newbag : true;
    return m(".movelist-container",
      [
        m(".movelist",
          {
            onupdate: () => { setTimeout(this.scrollMovelistToBottom); }
          },
          movelist()
        ),
        // Show the bag here on mobile
        state.uiFullscreen ? "" : m(this.Bag, { bag: bag, newbag: newbag })
      ]
    );
  }

  vwBestMoves(moveIndex: number, bestMoves: Move[]) {
    // List of best moves, in a game review

    const view = this;
    const model = this.model;
    const game = model.game;

    function bestHeader(co: string, tiles: string, score: number): m.vnode {
      // Generate the header of the best move list
      let wrdclass = "wordmove";
      let dispText: string | any[];
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
          dispText = ts("Pass");
        else
        if (tiles.indexOf("EXCH") === 0) {
          /* Exchange move - we don't show the actual tiles exchanged, only their count */
          let numtiles = tiles.slice(5).length
          const letters = ts(numtiles == 1 ? "letter" : "letters");
          dispText = ts("exchanged", { numtiles: numtiles.toString(), letters: letters });
        }
        else
        if (tiles == "RSGN")
          /* Resigned from game */
          dispText = ts("Gaf viðureign");
        else
        if (tiles == "CHALL")
          /* Challenge issued */
          dispText = ts("Véfengdi lögn");
        else
        if (tiles == "RESP") {
          /* Challenge response */
          if (score < 0)
            dispText = ts("Óleyfileg lögn");
          else
            dispText = ts("Röng véfenging");
        }
        else
        if (tiles == "TIME") {
          /* Score adjustment for time */
          dispText = ts("Umframtími");
        }
        else
        if (tiles == "OVER") {
          /* Game over */
          dispText = ts("Viðureign lokið");
          wrdclass = "gameover";
        }
        else {
          // The rack leave at the end of the game (which is always in lowercase
          // and thus cannot be confused with the above abbreviations)
          wrdclass = "othermove";
          if (tiles == "--")
            dispText = ts("Stafaleif: (engin)");
          else
            dispText = [ts("Stafaleif: "), m("i", tiles)];
        }
      }
      return m(".reviewhdr",
        [
          m("span.movenumber", "#" + moveIndex),
          m("span", { class: wrdclass }, dispText)
        ]
      );
    }

    function bestMoveList(): m.vnode[] {
      let r: m.vnode[] = [];
      // Use a 1-based index into the move list
      // (We show the review summary if move==0)
      if (!moveIndex || moveIndex > game.moves.length)
        return r;
      // Prepend a header that describes the move being reviewed
      let m = game.moves[moveIndex - 1];
      let co = m[1][0];
      let tiles = m[1][1];
      let score = m[1][2];
      r.push(bestHeader(co, tiles, score));
      let mlist = bestMoves;
      for (let i = 0; i < mlist.length; i++) {
        let [player, [co, tiles, score]] = mlist[i];
        r.push(
          view.vwBestMove(moveIndex, i, mlist[i],
            {
              key: i.toString(),
              player: player, co: co, tiles: tiles,
              score: score, leftTotal: 0, rightTotal: 0
            }
          )
        );
      }
      return r;
    }

    return m(".movelist-container", [m(".movelist.bestmoves", bestMoveList())]);
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

  vwMove(move: Move, info: MoveInfo) {
    // Displays a single move

    const view = this;
    const model = this.model;
    const game = model.game;
    const state = model.state;

    function highlightMove(co: string, tiles: string, playerColor: 0 | 1, show: boolean) {
      /* Highlight a move's tiles when hovering over it in the move list */
      const vec = toVector(co);
      let col = vec.col;
      let row = vec.row;
      for (const tile of tiles) {
        if (tile == '?')
          continue;
        const sq = coord(row, col);
        if (game.tiles.hasOwnProperty(sq))
          game.tiles[sq].highlight = show ? playerColor : undefined;
        col += vec.dx;
        row += vec.dy;
      }
    }

    let player = info.player;
    let co: string = info.co;
    let tiles: string = info.tiles;
    let score: string | number = info.score;
    let leftTotal = info.leftTotal;
    let rightTotal = info.rightTotal;

    function gameOverMove(tiles: string): m.vnode {
      // Add a 'game over' div at the bottom of the move list
      // of a completed game. The div includes a button to
      // open a review of the game, if the user is a subscriber.
      return m(".move.gameover",
        [
          m("span.gameovermsg", tiles),
          m("span.statsbutton",
            {
              onclick: (ev) => {
                ev.preventDefault();
                if (state.hasPaid) {
                  // Show the game review
                  m.route.set("/review/" + game.uuid);
                  if (game !== null && game !== undefined) {
                    // Log an event for this action
                    logEvent("game_review",
                      {
                        locale: game.locale,
                        uuid: game.uuid
                      }
                    );
                  }
                }
                else {
                  // Show a friend promotion dialog
                  logEvent("click_review",
                    {
                      userid: model.state.userId, locale: model.state.locale
                    }
                  );
                  view.showFriendPromo();
                }
              }
            },
            t("Skoða yfirlit")
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
        tiles = " " + ts("Pass") + " ";
        score = "";
      }
      else
      if (tiles.indexOf("EXCH") === 0) {
        /* Exchange move - we don't show the actual tiles exchanged, only their count */
        let numtiles = tiles.slice(5).length;
        const letters = ts(numtiles == 1 ? "letter" : "letters");
        // Exchanged {numtiles} {letters}
        tiles = " " + ts("exchanged", { numtiles: numtiles.toString(), letters: letters }) + " ";
        score = "";
      }
      else
      if (tiles == "RSGN")
        /* Resigned from game */
        tiles = " " + ts("Gaf viðureign") + " ";
      else
      if (tiles == "CHALL") {
        /* Challenge issued */
        tiles = " " + ts("Véfengdi lögn") + " ";
        score = "";
      }
      else
      if (tiles == "RESP") {
        /* Challenge response */
        if (score < 0) {
          // Invalid move
          tiles = " " + ts("Óleyfileg lögn") + " ";
          tileMoveIncrement = -1; // Subtract one from the actual tile moves on the board
        }
        else
          // Unsuccessful challenge
          tiles = " " + ts("Röng véfenging") + " ";
      }
      else
      if (tiles == "TIME") {
        /* Overtime adjustment, 'Extra time' */
        tiles = " " + ts("Umframtími") + " ";
      }
      else
      if (tiles == "OVER") {
        /* Game over */
        tiles = ts("Viðureign lokið");
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
    let title = (tileMoveIncrement > 0 && !game.manual) ? ts("Smelltu til að fletta upp") : "";
    let playerColor: 0 | 1 = 0;
    let lcp = game.player;
    let cls: string;
    if (player === lcp || (lcp == -1 && player === 0)) // !!! FIXME: Check -1 case
      cls = "humangrad" + (player === 0 ? "_left" : "_right"); /* Local player */
    else {
      cls = "autoplayergrad" + (player === 0 ? "_left" : "_right"); /* Remote player */
      playerColor = 1;
    }
    let attribs: VnodeAttrs = { };
    if (state.uiFullscreen && tileMoveIncrement > 0) {
      if (!game.manual) {
        if (game.locale == "is_IS") {
          // Tile move and not a manual game: allow word lookup for Icelandic
          attribs.onclick = () => { window.open('https://malid.is/leit/' + tiles, 'malid'); };
          attribs.title = title;
        }
      }
      // Highlight the move on the board while hovering over it
      attribs.onmouseout = () => {
        move["highlighted"] = false;
        highlightMove(rawCoord, tiles, playerColor, false);
      };
      attribs.onmouseover = () => {
        move["highlighted"] = true;
        highlightMove(rawCoord, tiles, playerColor, true);
      };
    }
    if (player === 0) {
      // Move by left side player
      return m(".move.leftmove." + cls, attribs,
        [
          m("span.total" + (player == lcp ? ".human" : ".autoplayer"), leftTotal),
          m("span.score" + (move["highlighted"] ? ".highlight" : ""), score),
          m("span." + wrdclass, [m("i", tiles), nbsp(), co])
        ]
      );
    }
    else {
      // Move by right side player
      return m(".move.rightmove." + cls, attribs,
        [
          m("span." + wrdclass, [co, nbsp(), m("i", tiles)]),
          m("span.score" + (move["highlighted"] ? ".highlight" : ""), score),
          m("span.total" + (player == lcp ? ".human" : ".autoplayer"), rightTotal)
        ]
      );
    }
  }

  vwBestMove(moveIndex: number, bestMoveIndex: number, move: Move, info: MoveInfo) {
    // Displays a move in a list of best available moves

    const model = this.model;
    const game = model.game;
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
      for (let tile of tiles) {
        if (tile == "?") {
          nextBlank = true;
          continue;
        }
        let sq = coord(row, col);
        let letter = tile;
        if (nextBlank)
          tile = '?';
        const tscore = game.tilescore(tile);
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
    // Word lookup, if Icelandic game
    if (game.locale == "is_IS")
      attribs.onclick = () => { window.open('https://malid.is/leit/' + word, 'malid'); };
    // Highlight the move on the board while hovering over it
    attribs.onmouseover = () => {
      move["highlighted"] = true;
      highlightMove(rawCoord, tiles, playerColor, true);
    };
    attribs.onmouseout = () => {
      move["highlighted"] = false;
      highlightMove(rawCoord, tiles, playerColor, false);
    };
    if (player === 0) {
      // Move by left side player
      return m(".move.leftmove." + cls, attribs,
        [
          m("span.score" + (move["highlighted"] ? ".highlight" : ""), score),
          m("span.wordmove", [m("i", word), nbsp(), co])
        ]
      );
    }
    else {
      // Move by right side player
      return m(".move.rightmove." + cls, attribs,
        [
          m("span.wordmove", [co, nbsp(), m("i", word)]),
          m("span.score" + (move["highlighted"] ? ".highlight" : ""), score)
        ]
      );
    }
  }

  vwGames(): m.vnode {
    // The game list tab

    const model = this.model;

    function games(): m.vnode[] {
      let r: m.vnode[] = [];
      if (model.loadingGameList)
        return r;
      let gameList = model.gameList;
      if (gameList === undefined)
        // Game list is being loaded
        return r;
      if (gameList === null) {
        // No games to show now, but we'll load them
        // and they will be automatically refreshed when ready
        model.loadGameList();
        return r;
      }
      let game = model.game;
      let gameId = game ? game.uuid : "";
      for (let item of gameList) {
        if (item.uuid == gameId)
          continue; // Don't show this game
        if (!item.my_turn && !item.zombie)
          continue; // Only show pending games
        let opp: VnodeChildren;
        if (item.oppid === null)
          // Mark robots with a cog icon
          opp = [glyph("cog"), nbsp(), item.opp];
        else
          opp = [item.opp];
        let winLose = item.sc0 < item.sc1 ? ".losing" : "";
        let title = "Staðan er " + item.sc0 + ":" + item.sc1;
        // Add the game-timed class if the game is a timed game.
        // These will not be displayed in the mobile UI.
        r.push(
          m(".games-item" + (item.timed ? ".game-timed" : ""),
            { key: item.uuid, title: title },
            m(m.route.Link,
              { href: gameUrl(item.url) },
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
      }
      return r;
    }

    return m(".games", { style: "z-index: 6" }, games());
  }

  Bag: ComponentFunc<{ bag: string; newbag: boolean; }> = (initialVnode) => {
    // The bag of tiles

    function tiles(bag: string): m.vnode[] {
      let r: m.vnode[] = [];
      let ix = 0;
      let count = bag.length;
      while (count > 0) {
        // Rows
        let cols: m.vnode[] = [];
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
        else if (newbag)
          cls += ".new";
        return m(".bag",
          { title: ts("Flísar sem eftir eru") },
          m("table.bag-content" + cls, tiles(bag))
        );
      }
    };
  };

  BlankDialog: ComponentFunc<{}> = (initialVnode) => {
    // A dialog for choosing the meaning of a blank tile

    const model = this.model;

    function blankLetters(game: Game): m.vnode[] {
      let legalLetters = game.alphabet;
      let len = legalLetters.length;
      let ix = 0;
      let r: m.vnode[] = [];

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
        const game = model.game;
        return m(".modal-dialog",
          {
            id: 'blank-dialog',
            style: { visibility: "visible" }
          },
          m(".ui-widget.ui-widget-content.ui-corner-all", { id: 'blank-form' },
            [
              mt("p", "Hvaða staf táknar auða flísin?"),
              m(".rack.blank-rack",
                m("table.board", { id: 'blank-meaning' }, blankLetters(game))
              ),
              m(DialogButton,
                {
                  id: 'blank-close',
                  title: ts("Hætta við"),
                  onclick: (ev: Event) => {
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
  };

  BoardArea: ComponentFunc<{}> = (initialVnode) => {
    // Collection of components in the board (left-side) area
    const model = this.model;
    return {
      view: (vnode) => {
        const game = model.game;
        let r: VnodeChildren = [];
        if (game) {
          r = [
            m(this.Board, { review: false }),
            m(this.Rack, { review: false }),
            m(this.Buttons),
            this.vwErrors(game),
            this.vwGameOver()
          ];
          r = r.concat(this.vwDialogs(game));
        }
        return m(".board-area", r);
      }
    };
  };

  BoardReview: ComponentFunc<{ moveIndex: number; }> = (initialVnode) => {
    // The board area within a game review screen
    const model = this.model;
    return {
      view: (vnode) => {
        const game = model.game;
        let r: m.vnode[] = [];
        if (game) {
          r = [
            m(this.Board, { review: true }),
            m(this.Rack, { review: true }),
          ];
          let moveIndex = vnode.attrs.moveIndex;
          if (moveIndex !== null)
            // Don't show navigation buttons if currently at overview (move==null)
            r = r.concat(this.vwButtonsReview(moveIndex));
        }
        return m(".board-area", r);
      }
    };
  }

  Tile: ComponentFunc<{ coord: string; opponent: boolean; }> = (initialVnode) => {
    // Display a tile on the board or in the rack
    const model = this.model;
    return {
      view: (vnode) => {
        const game = model.game;
        const coord = vnode.attrs.coord;
        const isRackTile = coord[0] == 'R';
        // Tile laid down by the opponent
        const opponent = vnode.attrs.opponent;
        // A single tile, on the board or in the rack
        const t = game.tiles[coord];
        let classes = [".tile"];
        let attrs: VnodeAttrs = {};
        if (t.tile == '?')
          classes.push("blanktile");
        if (t.letter == 'q')
          // Extra wide letter: handle specially
          classes.push("extra-wide");
        else if (t.letter == 'z' || t.letter == 'x' || t.letter == 'm' || t.letter == 'æ')
          // Wide letter: handle specially
          classes.push("wide");
        if (isRackTile || t.draggable) {
          // Rack tile, or at least a draggable one
          classes.push(opponent ? "freshtile" : "racktile");
          if (isRackTile && game.showingDialog == "exchange") {
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
          // A fresh tile on the board that has
          // just been played by the opponent
          classes.push("freshtile");
        }
        if (t.index) {
          // Make fresh or highlighted tiles appear sequentally by animation
          const ANIMATION_STEP = 150; // Milliseconds
          const delay = (t.index * ANIMATION_STEP).toString() + "ms";
          attrs.style = `animation-delay: ${delay}; -webkit-animation-delay: ${delay};`;
        }
        if (coord == game.selectedSq)
          // Currently selected square
          classes.push("sel"); // Blinks red
        if (t.highlight !== undefined) {
          // highlight0 is the local player color
          // highlight1 is the remote player color
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
              // ev.preventDefault();
              game.selectedSq = null;
              // (ev.target as HTMLElement).classList.toggle("ui-draggable-dragging", true);
              ev.dataTransfer.effectAllowed = "move"; // "copyMove"
              ev.dataTransfer.setData("text", coord);
              ev.redraw = false;
              // return false;
            };
            attrs.ondragend = (ev) => {
              // (ev.target as HTMLElement).classList.toggle("ui-draggable-dragging", false);
              ev.preventDefault();
              ev.redraw = false;
              return false;
            };
            attrs.onclick = (ev) => {
              // When clicking a tile, make it selected (blinking)
              if (coord == game.selectedSq)
                // Clicking again: deselect
                game.selectedSq = null;
              else
                game.selectedSq = coord;
              ev.stopPropagation();
              return false;
            };
          }
        }
        return m(classes.join("."), attrs,
          [t.letter == ' ' ? nbsp() : t.letter, m(".letterscore", t.score)]
        );
      }
    };
  }

  TileSquare: ComponentFunc<{ coord: string; opponent: boolean; }> = (initialVnode) => {
    // Return a td element that wraps a tile on the board.
    // If the opponent flag is true, we put an '.opp' class on the td
    const view = this;
    const model = this.model;
    return {
      view: (vnode) => {
        const coord = vnode.attrs.coord;
        const game = model.game;
        return m("td",
          {
            id: "sq_" + coord,
            class: game.squareClass(coord),
            // The square contains a tile, so we don't allow dropping a tile on it;
            // indicate this by curtailing feedback on dragover and on drop
            ondragover: (ev) => ev.stopPropagation(),
            ondrop: (ev) => ev.stopPropagation()
          },
          m(view.Tile, { coord: coord, opponent: false })
        );
      }
    };
  };

  ReviewTileSquare: ComponentFunc<{ coord: string; opponent: boolean; }> = (initialVnode) => {
    // Return a td element that wraps an 'inert' tile in a review screen.
    // If the opponent flag is true, we put an '.opp' class on the td
    const model = this.model;
    return {
      view: (vnode) => {
        const coord = vnode.attrs.coord;
        let cls = model.game.squareClass(coord) || "";
        if (cls)
          cls = "." + cls;
        if (vnode.attrs.opponent)
          cls += ".opp";
        return m("td" + cls, { id: "sq_" + coord }, vnode.children);
      }
    };
  };

  DropTargetSquare: ComponentFunc<{ coord: string; }> = (initialVnode) => {
    // Return a td element that is a target for dropping tiles
    const model = this.model;
    return {
      view: (vnode) => {
        const coord = vnode.attrs.coord;
        const game = model.game;
        let cls = game.squareClass(coord) || "";
        if (cls)
          cls = "." + cls;
        // Mark the cell with the 'blinking' class if it is the drop
        // target of a pending blank tile dialog
        if (game.askingForBlank !== null && game.askingForBlank.to == coord)
          cls += ".blinking";
        if (coord == game.startSquare && model.game.localturn)
          // Unoccupied start square, first move
          cls += ".center";
        return m("td" + cls,
          {
            id: "sq_" + coord,
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
              const from = ev.dataTransfer.getData("text");
              game.attemptMove(from, coord);
              this.updateScale(game);
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
                this.updateScale(game);
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

  Board: ComponentFunc<{ review: boolean; }> = (initialVnode) => {
    // The game board, a 15x15 table plus row (A-O) and column (1-15) identifiers

    const view = this;
    const model = this.model;
    const review = initialVnode.attrs.review;

    function colid(): m.vnode {
      // The column identifier row
      let r: m.vnode[] = [];
      r.push(m("td"));
      for (let col = 1; col <= 15; col++)
        r.push(m("td", col.toString()));
      return m("tr.colid", r);
    }

    function row(rowid: string): m.vnode {
      // Each row of the board
      let r: m.vnode[] = [];
      const game = model.game;
      r.push(m("td.rowid", { key: "R" + rowid }, rowid));
      for (let col = 1; col <= 15; col++) {
        const coord = rowid + col.toString();
        if (game && (coord in game.tiles))
          // There is a tile in this square: render it
          r.push(m(view.TileSquare, { key: coord, coord: coord, opponent: false }));
        else if (review)
          // Empty, inert square
          r.push(m(view.ReviewTileSquare, { key: coord, coord: coord, opponent: false }));
        else
          // Empty square which is a drop target
          r.push(m(view.DropTargetSquare, { key: coord, coord: coord }));
      }
      return m("tr", r);
    }

    function allrows(): m.vnode[] {
      // Return a list of all rows on the board
      let r: m.vnode[] = [];
      r.push(colid());
      const rows = "ABCDEFGHIJKLMNO";
      for (const rw of rows)
        r.push(row(rw));
      return r;
    }

    function zoomIn() {
      view.boardScale = 1.5;
    }

    function zoomOut() {
      if (view.boardScale != 1.0) {
        view.boardScale = 1.0;
        setTimeout(view.resetScale);
      }
    }

    return {
      view: (vnode) => {
        const scale = view.boardScale || 1.0;
        let attrs: VnodeAttrs = {};
        // Add handlers for pinch zoom functionality
        addPinchZoom(attrs, zoomIn, zoomOut);
        if (scale != 1.0)
          attrs.style = `transform: scale(${scale})`;
        return m(".board",
          { id: "board-parent" },
          m("table.board", attrs, m("tbody", allrows()))
        );
      }
    };
  }

  Rack: ComponentFunc<{ review: boolean; }> = (initialVnode) => {
    // A rack of 7 tiles
    const view = this;
    const model = this.model;
    const review = initialVnode.attrs.review;
    return {
      view: (vnode) => {
        const game = model.game;
        let r: m.vnode[] = [];
        // If review==true, this is a review rack
        // that is not a drop target and whose color reflects the
        // currently shown move.
        // If opponent==true, we're showing the opponent's rack
        const opponent = review && (model.reviewMove > 0) && (model.reviewMove % 2 == game.player);
        for (let i = 1; i <= RACK_SIZE; i++) {
          const coord = 'R' + i.toString();
          if (game && (coord in game.tiles)) {
            // We have a tile in this rack slot, but it is a drop target anyway
            if (review) {
              r.push(
                m(view.ReviewTileSquare, { coord: coord, opponent: opponent },
                  m(view.Tile, { coord: coord, opponent: opponent })
                )
              );
            }
            else {
              r.push(
                m(view.DropTargetSquare, { coord: coord },
                  m(view.Tile, { coord: coord, opponent: false })
                )
              );
            }
          }
          else if (review) {
            r.push(m(view.ReviewTileSquare, { coord: coord, opponent: false }));
          }
          else {
            r.push(m(view.DropTargetSquare, { coord: coord }));
          }
        }
        return m(".rack-row", [
          m(".rack-left", view.vwButtonsLeftOfRack()),
          m(".rack", m("table.board", m("tbody", m("tr", r))))
        ]);
      }
    };
  };

  vwRecallButton(): m.vnode {
    // Create a tile recall button
    const model = this.model;
    const game = model.game;
    return this.makeButton(
      "recallbtn", false,
      () => { game.resetRack(); this.updateScale(game); },
      ts("Færa stafi aftur í rekka"), glyph("down-arrow")
    );
  }

  vwScrambleButton(disabled: boolean): m.vnode {
    // Show a 'Scramble rack' button
    const model = this.model;
    const game = model.game;
    return this.makeButton(
      "scramblebtn", disabled,
      () => { game.rescrambleRack(); },
      ts("Stokka upp rekka"), glyph("random")
    );
  }

  vwButtonsLeftOfRack(): m.vnode {
    // The button to the left of the rack in the mobile UI
    const model = this.model;
    const game = model.game;
    const s = this.buttonState(game);
    if (s.showRecall && !s.showingDialog)
      // Show a 'Recall tiles' button
      return this.vwRecallButton();
    if (s.showScramble && !s.showingDialog)
      return this.vwScrambleButton(false);
    return undefined;
  }

  vwScore(): m.vnode {
    // Shows the score of the current word
    const game = this.model.game;
    let sc = [".score"];
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

  vwScoreReview(moveIndex: number): m.vnode {
    // Shows the score of the current move within a game review screen
    const game = this.model.game;
    let mv = moveIndex ? game.moves[moveIndex - 1] : undefined;
    if (mv === undefined)
      return undefined;
    let [_, [coord, tiles, score]] = mv;
    if (score === undefined || (coord == "" && tiles == "OVER"))
      // No score available, or this is a "game over" sentinel move: don't display
      return undefined;
    let sc = [".score"];
    if (moveIndex > 0) {
      if (moveIndex % 2 == game.player)
        // Opponent move: show in green
        sc.push("green");
      else
        // Player's move: show in yellow
        sc.push("yellow");
    }
    return m(sc.join("."), score.toString());
  }

  vwScoreDiff(moveIndex: number): m.vnode {
    // Shows the score of the current move within a game review screen
    const model = this.model;
    const game = model.game;
    let sc = [".scorediff"];
    let mv = moveIndex ? game.moves[moveIndex - 1] : undefined;
    let score = mv ? mv[1][2] : undefined;
    let bestScore = model.bestMoves[model.highlightedMove][1][2];
    let diff = (score - bestScore).toString();
    if (diff[0] != "-" && diff[0] != "0")
      diff = "+" + diff;
    if (score >= bestScore)
      sc.push("posdiff");
    return m(sc.join("."), { style: { visibility: "visible" } }, diff);
  }

  vwStatsReview(): m.vnode {
    // Shows the game statistics overlay
    const game = this.model.game;
    if (game.stats === null)
      // No stats yet loaded: do it now
      game.loadStats();

    function fmt(p: string, digits?: number, value?: string | number): string {
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
                  [glyph("cog"), nbsp(), game.nickname[0]]
                  :
                  game.nickname[0]
              )
            ),
            m(".player", { class: rightPlayerColor, style: { width: "50%", "text-align": "right" } },
              m(".robot-btn.right",
                game.autoplayer[1] ?
                  [glyph("cog"), nbsp(), game.nickname[1]]
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
            game.manual ? m("p", "Leikið var í keppnisham") : ""
          ]
        ),
        m(".statscol", { style: { clear: "left" } },
          [
            m("p",
              ["Fjöldi leikja: ", m("span", fmt("moves0"))]
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
              ["Fjöldi leikja: ", m("span", fmt("moves1"))]
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
              setTimeout(() => {
                m.route.set("/review/" + game.uuid, { move: 1 });
              });
              ev.preventDefault();
            },
            onmouseover: buttonOver,
            onmouseout: buttonOut
          },
          [glyph("play"), " Rekja"]
        )
      ]
    );
  }

  makeButton(
    cls: string, disabled: boolean, func: () => void,
    title?: string, children?: VnodeChildren, id?: string
  ): m.vnode {
    // Create a button element, wrapping the disabling logic
    // and other boilerplate
    let attr: VnodeAttrs = {
      onmouseout: buttonOut,
      onmouseover: buttonOver,
    };
    if (title)
      attr.title = title;
    if (id)
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

  Buttons: ComponentFunc<{}> = (initialVnode) => {

    const model = this.model;

    return {
      view: (vnode) => {
        // The set of buttons below the game board, alongside the rack (fullscreen view)
        // or below the rack (mobile view)
        const game = model.game;
        const s = this.buttonState(game);
        let r: m.vnode[] = [];
        r.push(m(".word-check" +
          (s.wordGood ? ".word-good" : "") +
          (s.wordBad ? ".word-bad" : "")));
        if (s.showChallenge) {
          // Show a button that allows the player to challenge the opponent's
          // last move
          const disabled = (s.tilesPlaced || s.showingDialog) && !s.lastChallenge;
          r.push(
            this.makeButton(
              "challenge", disabled,
              () => game.submitChallenge(),
              'Véfenging (röng kostar 10 stig)', glyph("ban-circle")
            )
          );
        }
        if (s.showRecall)
          // Show button to recall tiles from the board into the rack
          r.push(this.vwRecallButton());
        if (s.showScramble)
          // Show button to scramble (randomly reorder) the rack tiles
          r.push(this.vwScrambleButton(s.showingDialog));
        if (s.showMove) {
          // "Plain" move button for fullscreen
          const submit_move = ts("submit_move"); // 'Move' or 'Leika'
          r.push(
            this.makeButton(
              "submitmove", !s.tilesPlaced || s.showingDialog,
              () => { game.submitMove(); this.updateScale(game); },
              submit_move, [submit_move, glyph("play")]
            )
          );
        }
        if (s.showMoveMobile) {
          // Submit-Move button on mobile, which also shows the score
          // and whether the move is good or bad
          let classes: string[] = ["submitmove"];
          let wordIsPlayable = game.currentScore !== undefined;
          if (game.manual) {
            classes.push("manual")
          } else if (s.wordGood) {
            classes.push("word-good");
            if (game.currentScore >= 50)
              classes.push("word-great");
          } else if (s.wordBad) {
            classes.push("word-bad");
            wordIsPlayable = false;
          }
          const text = (game.currentScore === undefined) ? "?" : game.currentScore.toString();
          let legend: VnodeChildren[] = [m("span.score-mobile", text)];
          if (s.canPlay && wordIsPlayable)
            legend.push(glyph("play"));
          else
            legend.push(glyph("remove"));
          let action: () => void;
          if (s.canPlay) {
            if (wordIsPlayable)
              action = () => { game.submitMove(); this.updateScale(game); };
            else
              action = () => { /* TODO: Add some kind of feedback? */ };
          }
          else {
            action = () => {
              // Make the 'opp-turn' flash, to remind the user that it's not her turn
              const el = document.querySelector("div.opp-turn") as HTMLElement;
              if (el) {
                el.classList.toggle("flashing", true);
                setTimeout(() => el.classList.toggle("flashing", false), 1200);
              }
            };
          }
          r.push(
            this.makeButton(
              classes.join("."), s.showingDialog, action, text, legend, "move-mobile"
            )
          );
        }
        if (s.showForceResignMobile) {
          // Force resignation button (only shown on mobile,
          // and only if submit move button is not shown)
          const txt = ts("Þvinga til uppgjafar");
          r.push(
            this.makeButton(
              "force-resign",
              s.showingDialog,
              () => { game.forceResign(); },
              txt,
              txt
            )
          );
        }
        if (s.showPass) {
          // Pass move: shown if no tiles have been placed
          // and we're not showing a dialog, or if this is
          // the last move by the opponent in a manual game
          r.push(
            this.makeButton(
              "submitpass",
              (s.tilesPlaced || s.showingDialog) && !s.lastChallenge,
              () => game.submitPass(),
              ts("Pass"), glyph("forward")
            )
          );
        }
        if (s.showExchange) {
          // Exchange tiles from the rack
          r.push(
            this.makeButton(
              "submitexchange",
              s.tilesPlaced || s.showingDialog || !s.exchangeAllowed,
              () => game.submitExchange(),
              ts("Skipta stöfum"), glyph("refresh")
            )
          );
        }
        if (s.showResign) {
          // Resign the game
          r.push(
            this.makeButton(
              "submitresign", s.showingDialog,
              () => game.submitResign(),
              ts("Gefa viðureign"), glyph("fire")
            )
          );
        }
        if (!s.gameOver && !s.localTurn && !game.moveInProgress) {
          // Indicate that it is the opponent's turn; offer to force a resignation
          // if the opponent hasn't moved for 14 days
          r.push(
            m(".opp-turn",
              { style: { visibility: "visible" } },
              [
                m("span.move-indicator"),
                nbsp(),
                m("strong", game.nickname[1 - game.player]),
                ts(" á leik"),
                nbsp(),
                // The following inline button is only
                // displayed in the fullscreen UI
                s.tardyOpponent ? m("span.yesnobutton",
                  {
                    id: "force-resign",
                    onclick: (ev) => {
                      ev.preventDefault();
                      game.forceResign();
                    },
                    onmouseout: buttonOut,
                    onmouseover: buttonOver,
                    title: ts("14 dagar liðnir án leiks")
                  },
                  ts("Þvinga til uppgjafar")
                ) : ""
              ]
            )
          );
        }
        if (s.tilesPlaced)
          // Show the score of the current move (not visible on mobile)
          r.push(this.vwScore());
        // Is the server processing a move?
        if (game.moveInProgress) {
          r.push(
            m(".waitmove",
              m(".animated-waitmove",
                m(AnimatedExploLogo, { msStepTime: 100, width: 38, withCircle: false })
              )
            )
          );
        }
        return m(".buttons", r);
      }
    };
  };

  vwButtonsReview(moveIndex: number) {
    // The navigation buttons below the board on the review screen
    const model = this.model;
    const game = model.game;
    const numMoves = game.moves.length;
    let r: m.vnode[] = [];
    r.push(
      this.makeButton(
        "navbtn", !moveIndex, // Disabled if at moveIndex 0 (initial review dialog)
        () => {
          // Navigate to previous moveIndex
          m.route.set(
            "/review/" + game.uuid,
            { move: moveIndex ? moveIndex - 1 : 0 }
          );
        },
        "Sjá fyrri leik",
        m("span",
          { id: "nav-prev-visible" },
          [glyph("chevron-left"), " Fyrri"]
        ),
        "navprev"
      )
    );
    r.push(
      this.makeButton(
        "navbtn", (!moveIndex) || (moveIndex >= numMoves),
        () => {
          // Navigate to next moveIndex
          m.route.set(
            "/review/" + game.uuid,
            { move: (moveIndex || 0) + 1 }
          );
        },
        "Sjá næsta leik",
        m("span",
          { id: "nav-next-visible" },
          ["Næsti ", glyph("chevron-right")]
        ),
        "navnext"
      )
    );
    // Show the score difference between an actual moveIndex and
    // a particular moveIndex on the best moveIndex list
    if (model.highlightedMove !== null)
      r.push(this.vwScoreDiff(moveIndex));
    r.push(this.vwScoreReview(moveIndex));
    return r;
  }

  vwErrors(game: Game): m.vnode {
    // Error messages, selectively displayed
    let msg: string = game.currentMessage || "";
    if (game.currentError in ERROR_MESSAGES) {
      const txt: string = ts(ERROR_MESSAGES[game.currentError]);
      const wix = txt.indexOf("{word}");
      let children: VnodeChildren[];
      if (wix >= 0) {
        // Found {word} macro: create three child nodes
        children = [ txt.slice(0, wix), m("span.errword", msg), txt.slice(wix + 6) ];
      }
      else {
        // No {word} macro: just return the message as-is
        children = [ txt ];
      }
      return m(".error",
        {
          style: { visibility: "visible" },
          onclick: (ev) => { game.resetError(); ev.preventDefault(); }
        },
        [ glyph("exclamation-sign"), ...children ]
      );
    }
    return undefined;
  }

  vwGameOver(): m.vnode {
    // Show message at end of game, either congratulating a win or
    // solemnly informing the player that the game is over
    const game = this.model.game;
    if (game.congratulate)
      return m("div", { id: "congrats" },
        [
          glyph("bookmark"),
          " ",
          mt("strong", "Til hamingju með sigurinn!")
        ]
      );
    else if (game.over) {
      return m("div", { id: "gameover" },
        [
          glyph("info-sign"),
          " ",
          mt("strong", "Viðureigninni er lokið")
        ]
      );
    }
    else
      return undefined;
  }

  vwDialogs(game: Game) {
    // Show prompt dialogs below game board, if any
    let r: m.vnode[] = [];
    if (game.showingDialog === null && !game.last_chall)
      return r;
    // The dialogs below, specifically the challenge and pass
    // dialogs, have priority over the last_chall dialog - since
    // they can be invoked while the last_chall dialog is being
    // displayed. We therefore allow them to cover the last_chall
    // dialog. On mobile, both dialogs are displayed simultaneously.
    if (game.last_chall)
      r.push(m(".chall-info", { style: { visibility: "visible" } },
        [
          glyph("info-sign"), nbsp(),
          // "Your opponent emptied the rack - you can challenge or pass"
          mt("span.pass-explain", "opponent_emptied_rack")
        ]
      ));
    if (game.showingDialog == "resign")
      r.push(m(".resign", { style: { visibility: "visible" } },
        [
          glyph("exclamation-sign"), nbsp(), ts("Viltu gefa leikinn?"), nbsp(),
          m("span.mobile-break", m("br")),
          m("span.yesnobutton", { onclick: () => game.confirmResign(true) },
            [glyph("ok"), ts(" Já")]
          ),
          m("span.mobile-space"),
          m("span.yesnobutton", { onclick: () => game.confirmResign(false) },
            [glyph("remove"), ts(" Nei")]
          )
        ]
      ));
    if (game.showingDialog == "pass") {
      if (game.last_chall)
        r.push(m(".pass-last", { style: { visibility: "visible" } },
          [
            glyph("forward"), nbsp(), ts("Segja pass?"),
            mt("span.pass-explain", "Viðureign lýkur þar með"),
            nbsp(),
            m("span.mobile-break", m("br")),
            m("span.yesnobutton", { onclick: () => game.confirmPass(true) },
              [glyph("ok"), ts(" Já")]
            ),
            m("span.mobile-space"),
            m("span.yesnobutton", { onclick: () => game.confirmPass(false) },
              [glyph("remove"), ts(" Nei")]
            )
          ]
        ));
      else
        r.push(m(".pass", { style: { visibility: "visible" } },
          [
            glyph("forward"), nbsp(), ts("Segja pass?"),
            mt("span.pass-explain", "2x3 pöss í röð ljúka viðureign"),
            nbsp(), m("span.mobile-break", m("br")),
            m("span.yesnobutton", { onclick: () => game.confirmPass(true) },
              [glyph("ok"), ts(" Já")]
            ),
            m("span.mobile-space"),
            m("span.yesnobutton", { onclick: () => game.confirmPass(false) },
              [glyph("remove"), ts(" Nei")]
            )
          ]
        ));
    }
    if (game.showingDialog == "exchange")
      r.push(m(".exchange", { style: { visibility: "visible" } },
        [
          glyph("refresh"), nbsp(),
          ts("Smelltu á flísarnar sem þú vilt skipta"), nbsp(),
          m("span.mobile-break", m("br")),
          m("span.yesnobutton",
            { title: ts('Skipta'), onclick: () => game.confirmExchange(true) },
            glyph("ok")
          ),
          m("span.mobile-space"),
          m("span.yesnobutton",
            { title: ts('Hætta við'), onclick: () => game.confirmExchange(false) },
            glyph("remove"))
        ]
      ));
    if (game.showingDialog == "chall")
      r.push(m(".chall", { style: { visibility: "visible" } },
        [
          glyph("ban-circle"), nbsp(), ts("Véfengja lögn?"),
          mt("span.pass-explain", "Röng véfenging kostar 10 stig"), nbsp(),
          m("span.mobile-break", m("br")),
          m("span.yesnobutton",
            { onclick: () => game.confirmChallenge(true) },
            [glyph("ok"), ts(" Já")]
          ),
          m("span.mobile-space"),
          m("span.yesnobutton",
            { onclick: () => game.confirmChallenge(false) },
            [glyph("remove"), ts(" Nei")]
          )
        ]
      ));
    return r;
  }

  makeTabs(id: string, createFunc: (vnode: Vnode) => void, wireHrefs: boolean, vnode: Vnode) {
    // When the tabs are displayed for the first time, wire'em up
    let tabdiv = document.getElementById(id);
    if (!tabdiv)
      return;
    // Add bunch of jQueryUI compatible classes
    tabdiv.setAttribute("class", "ui-tabs ui-widget ui-widget-content ui-corner-all");
    let tabul = document.querySelector("#" + id + " > ul");
    tabul.setAttribute("class", "ui-tabs-nav ui-helper-reset ui-helper-clearfix ui-widget-header ui-corner-all");
    tabul.setAttribute("role", "tablist");
    let tablist = document.querySelectorAll("#" + id + " > ul > li > a") as NodeListOf<HTMLElement>;
    let tabitems = document.querySelectorAll("#" + id + " > ul > li") as NodeListOf<HTMLElement>;
    let ids: string[] = [];
    let lis: HTMLElement[] = []; // The <li> elements
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
      const model = this.model;
      const clickURL = (ev: Event, href: string) => {
        let uri = href.slice(ROUTE_PREFIX_LEN); // Cut the /page#!/ prefix off the route
        let qix = uri.indexOf("?");
        let route = (qix >= 0) ? uri.slice(0, qix) : uri;
        let qparams = uri.slice(route.length + 1);
        let params = qparams.length ? getUrlVars(qparams) : {};
        m.route.set(route, params);
        if (window.history)
          window.history.pushState({}, "", href); // Enable the back button
        ev.preventDefault();
      };
      const clickUserPrefs = (ev: Event) => {
        if (model.state.userId != "")
          // Don't show the userprefs if no user logged in
          this.pushDialog("userprefs");
        ev.preventDefault();
      };
      const clickTwoLetter = (ev: Event) => {
        selectTab(vnode, 2); // Select tab number 2
        ev.preventDefault();
      };
      const clickNewBag = (ev: Event) => {
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

// General-purpose Mithril components

const LeftLogo: ComponentFunc<{}> = () => {
  return {
    view: () => {
      return m(".logo",
        m(m.route.Link,
          { href: '/main', class: "nodecorate" },
          m(ExploLogo, { legend: false, scale: 1.6 })
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
  autocomplete?: string;
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
          autocomplete: vnode.attrs.autocomplete,
          value: text,
          oninput: (ev) => { text = (ev.target as HTMLInputElement).value + ""; }
        }
      );
    }
  };

}

// A nice graphical toggler control

function vwToggler(id: string, state: boolean, tabindex: number,
  opt1: VnodeChildren, opt2: VnodeChildren, funcToggle?: (state: boolean) => void,
  small?: boolean, title?: string): m.vnode {

  const togglerId = id + "-toggler";
  const optionClass = ".option" + (small ? ".small" : "");

  function doToggle() {
    // Perform the toggling, on a mouse click or keyboard input (space bar)
    const cls1 = document.querySelector("#" + togglerId + " #opt1").classList;
    const cls2 = document.querySelector("#" + togglerId + " #opt2").classList;
    cls1.toggle("selected");
    cls2.toggle("selected");
    if (funcToggle !== undefined)
      // Toggling the switch and we have an associated function:
      // call it with the boolean state of the switch
      funcToggle(cls2.contains("selected"));
  }

  return m.fragment({}, [
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
        onclick: (ev) => { doToggle(); ev.preventDefault(); },
        onkeypress: (ev) => { if (ev.key == " ") { doToggle(); ev.preventDefault(); } }
      },
      [
        m(optionClass + (state ? "" : ".selected"), { id: "opt1" }, opt1),
        m(optionClass + (state ? ".selected" : ""), { id: "opt2" }, opt2)
      ]
    )
  ]);
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
  const defaultClass = initialVnode.attrs.defaultClass || "";
  const selectedClass = initialVnode.attrs.selectedClass || "selected";

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

const OnlinePresence: ComponentFunc<{ id: string; userId: string; online?: boolean; }> = (initialVnode) => {

  // Shows an icon in grey or green depending on whether a given user
  // is online or not. If attrs.online is given (i.e. not undefined),
  // that value is used and displayed; otherwise the server is asked.

  const attrs = initialVnode.attrs;
  const askServer = attrs.online === undefined;
  let online = attrs.online ? true : false;
  const id = attrs.id;
  const userId = attrs.userId;

  async function _update() {
    if (askServer) {
      const json: { online: boolean; } = await m.request({
        method: "POST",
        url: "/onlinecheck",
        body: { user: userId }
      });
      online = json && json.online;
    }
  }

  return {
    oninit: _update,

    view: (vnode) => {
      if (!askServer)
        // Display the state of the online attribute as-is
        online = vnode.attrs.online;
      return m("span",
        {
          id: id,
          title: online ? ts("Er álínis") : ts("Álínis?"),
          class: online ? "online" : ""
        }
      );
    }
  };

};

const EloPage: ComponentFunc<{ view: View; id: string; key: string; }> = (initialVnode) => {

  // Show the header of an Elo ranking list and then the list itself

  let sel: EloListSelection = "human"; // Default: show ranking for human games only

  return {
    view: (vnode) => {
      return m.fragment({}, [
        m(".listitem.listheader", { key: vnode.attrs.key },
          [
            m("span.list-ch", glyphGrayed("hand-right", { title: ts('Skora á') })),
            mt("span.list-rank", "Röð"),
            m("span.list-rank-no-mobile", { title: ts('Röð í gær') }, ts("1d")),
            m("span.list-rank-no-mobile", { title: ts('Röð fyrir viku') }, ts("7d")),
            mt("span.list-nick-elo", "Einkenni"),
            m("span.list-elo", { title: ts('Elo-stig') }, ts("Elo")),
            m("span.list-elo-no-mobile", { title: ts('Elo-stig í gær') }, ts("1d")),
            m("span.list-elo-no-mobile", { title: ts('Elo-stig fyrir viku') }, ts("7d")),
            m("span.list-elo-no-mobile", { title: ts('Elo-stig fyrir mánuði') }, ts("30d")),
            m("span.list-games", { title: ts('Fjöldi viðureigna') }, glyph("th")),
            m("span.list-ratio", { title: ts('Vinningshlutfall') }, glyph("bookmark")),
            m("span.list-avgpts", { title: ts('Meðalstigafjöldi') }, glyph("dashboard")),
            mt("span.list-info-hdr", "Ferill"),
            // m("span.list-newbag", glyphGrayed("shopping-bag", { title: ts('Gamli pokinn') })),
            m(".toggler[id='elo-toggler']", { title: ts("elo_list_choice") },
              [
                m(".option.x-small",
                  {
                    // Show ranking for human games only
                    className: (sel == "human" ? "selected" : ""),
                    onclick: (ev) => { sel = "human"; ev.preventDefault(); },
                  },
                  glyph("user")
                ),
                m(".option.x-small",
                  {
                    // Show ranking for all games, including robots
                    className: (sel == "all" ? "selected" : ""),
                    onclick: (ev) => { sel = "all"; ev.preventDefault(); },
                  },
                  glyph("cog")
                ),
                m(".option.x-small",
                  {
                    // Show ranking for manual games only
                    className: (sel == "manual" ? "selected" : ""),
                    onclick: (ev) => { sel = "manual"; ev.preventDefault(); },
                  },
                  glyph("lightbulb")
                )
              ]
            )
          ]
        ),
        m(EloList,
          {
            id: vnode.attrs.id,
            sel: sel,
            view: vnode.attrs.view
          }
        )
      ]);
    }
  };

};

const EloList: ComponentFunc<{
  view: View;
  id: string;
  sel: EloListSelection;
}> = (initialVnode) => {

  const model = initialVnode.attrs.view.model;
  const state = model.state;

  return {

    view: (vnode) => {

      function itemize(item: UserListItem, i: number) {

        // Generate a list item about a user in an Elo ranking table

        function rankStr(rank: number, ref?: number): string {
          // Return a rank string or dash if no rank or not meaningful
          // (i.e. if the reference, such as the number of games, is zero)
          if (rank === 0 || (ref !== undefined && ref === 0))
            return "--";
          return rank.toString();
        }

        const isRobot = item.userid.indexOf("robot-") === 0;
        let nick: VnodeChildren = item.nick;
        let ch = nbsp();
        let info = nbsp();
        if (item.userid != state.userId && !item.inactive)
          ch = glyph("hand-right", { title: "Skora á" }, !item.chall);
        if (isRobot) {
          nick = m("span", [glyph("cog"), nbsp(), nick]);
        }
        else
          if (item.userid != state.userId)
            info = m("span.usr-info",
              {
                onclick: (ev) => {
                  ev.preventDefault();
                  vnode.attrs.view.showUserInfo(item.userid, item.nick, item.fullname);
                }
              }
            );
        if (item.fairplay && !isRobot)
          nick = m("span",
            [m("span.fairplay-btn", { title: ts("Skraflar án hjálpartækja") }), nick]);

        return m(".listitem",
          {
            key: vnode.attrs.sel + i,
            className: (i % 2 === 0 ? "oddlist" : "evenlist")
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
          ]
        );
      }

      let list: UserListItem[] = [];
      if (model.userList === undefined) {
        // Loading in progress
        // pass
      }
      else
        if (model.userList === null || model.userListCriteria.query != "elo" ||
          model.userListCriteria.spec != vnode.attrs.sel.toString()) {
          // We're not showing the correct list: request a new one
          model.loadUserList({ query: "elo", spec: vnode.attrs.sel }, true);
        }
        else {
          list = model.userList;
        }
      return m("div", { id: vnode.attrs.id }, list.map(itemize));
    }

  };
};

const RecentList: ComponentFunc<{ recentList: RecentListItem[]; id: string; }> = (initialVnode) => {
  // Shows a list of recent games, stored in vnode.attrs.recentList

  function itemize(item: RecentListItem, i: number) {

    // Generate a list item about a recently completed game

    function durationDescription() {
      // Format the game duration
      let duration: string | any[] = "";
      if (!item.duration) {
        // Regular (non-timed) game
        if (item.days || item.hours || item.minutes) {
          if (item.days > 1)
            duration = item.days.toString() + ts(" dagar");
          else
            if (item.days == 1)
              duration = ts("1 dagur");
          if (item.hours > 0) {
            if (duration.length)
              duration += ts(" og ");
            if (item.hours == 1)
              duration += ts("1 klst");
            else
              duration += item.hours.toString() + ts(" klst");
          }
          if (item.days === 0) {
            if (duration.length)
              duration += ts(" og ");
            if (item.minutes == 1)
              duration += ts("1 mínúta");
            else
              duration += item.minutes.toString() + ts(" mínútur");
          }
        }
      }
      else {
        // This was a timed game
        duration = [
          m("span.timed-btn", { title: ts('Viðureign með klukku') }),
          " 2 x " + item.duration + ts(" mínútur")
        ];
      }
      return duration;
    }

    // Show the Elo point adjustments resulting from the game
    let eloAdj: m.vnode | string = item.elo_adj ? item.elo_adj.toString() : "";
    let eloAdjHuman: m.vnode | string = item.human_elo_adj ? item.human_elo_adj.toString() : "";
    let eloAdjClass: string, eloAdjHumanClass: string;
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
        { href: gameUrl(item.url) },
        [
          m("span.list-win",
            item.sc0 >= item.sc1 ?
              glyph("bookmark", { title: item.sc0 == item.sc1 ? ts("Jafntefli") : ts("Sigur") }) :
              glyphGrayed("bookmark", { title: ts("Tap") })
          ),
          m("span.list-ts-short", item.ts_last_move),
          m("span.list-nick",
            item.opp_is_robot ? [glyph("cog"), nbsp(), item.opp] : item.opp
          ),
          m("span.list-s0", item.sc0),
          m("span.list-colon", ":"),
          m("span.list-s1", item.sc1),
          m("span.list-elo-adj", eloAdjHuman),
          m("span.list-elo-adj", eloAdj),
          m("span.list-duration", durationDescription()),
          m("span.list-manual",
            item.manual ? { title: ts("Keppnishamur") } : {},
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
  view: View;
  userid: string;
  nick: string;
  fullname: string;
}> = (initialVnode) => {

  // A dialog showing the track record of a given user, including
  // recent games and total statistics

  const model = initialVnode.attrs.view.model;
  let stats: { favorite?: boolean; friend?: boolean } = {};
  let recentList: RecentListItem[] = [];
  let versusAll = true; // Show games against all opponents or just the current user?

  function _updateStats(vnode: typeof initialVnode) {
    // Fetch the statistics of the given user
    model.loadUserStats(vnode.attrs.userid,
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
    model.loadUserRecentList(vnode.attrs.userid,
      versusAll ? null : model.state.userId,
      (json: { result: number; recentlist: RecentListItem[]; }) => {
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
                  [
                    stats.friend ?
                      glyph("coffee-cup", { title: ts('Vinur Netskrafls') }) :
                      glyph("user"), nbsp()
                  ]
                ),
                m("h1[id='usr-info-nick']", vnode.attrs.nick),
                m("span.vbar", "|"),
                m("h2[id='usr-info-fullname']", vnode.attrs.fullname),
                m(".usr-info-fav",
                  {
                    title: ts('Uppáhald'),
                    onclick: (ev) => {
                      // Toggle the favorite setting
                      ev.preventDefault();
                      stats.favorite = !stats.favorite;
                      model.markFavorite(vnode.attrs.userid, stats.favorite);
                    }
                  },
                  stats.favorite ? glyph("star") : glyph("star-empty")
                )
              ]
            ),
            m("p",
              [
                m("strong", t("Nýjustu viðureignir")),
                nbsp(),
                m("span.versus-cat",
                  [
                    m("span",
                      {
                        class: versusAll ? "shown" : "",
                        onclick: () => { _setVersus(vnode, true); } // Set this.versusAll to true
                      },
                      t(" gegn öllum ")
                    ),
                    m("span",
                      {
                        class: versusAll ? "" : "shown",
                        onclick: () => { _setVersus(vnode, false); } // Set this.versusAll to false
                      },
                      t(" gegn þér ")
                    )
                  ]
                )
              ]
            ),
            m(".listitem.listheader",
              [
                m("span.list-win", glyphGrayed("bookmark", { title: ts('Sigur') })),
                mt("span.list-ts-short", "Viðureign lauk"),
                mt("span.list-nick", "Andstæðingur"),
                mt("span.list-scorehdr", "Úrslit"),
                m("span.list-elo-hdr",
                  [
                    m("span.glyphicon.glyphicon-user.elo-hdr-left", { title: ts('Mennskir andstæðingar') }),
                    "Elo",
                    m("span.glyphicon.glyphicon-cog.elo-hdr-right", { title: ts('Allir andstæðingar') })
                  ]
                ),
                mt("span.list-duration", "Lengd"),
                m("span.list-manual", glyphGrayed("lightbulb", { title: ts('Keppnishamur') }))
              ]
            ),
            m(RecentList, { id: 'usr-recent', recentList: recentList }), // Recent game list
            m(StatsDisplay, { id: 'usr-stats', ownStats: stats }),
            m(BestDisplay, { id: 'usr-best', ownStats: stats, myself: false }), // Highest word and game scores
            m(DialogButton,
              {
                id: 'usr-info-close',
                title: ts('Loka'),
                onclick: (ev: Event) => { vnode.attrs.view.popDialog(); ev.preventDefault(); }
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
      let json = vnode.attrs.ownStats || {};
      let best = [];
      if (json.highest_score) {
        best.push(ts("Hæsta skor "));
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
            s.push(m("span.blanktile", bw[i + 1]));
            i += 1;
          }
          else
            s.push(bw[i]);
        best.push(ts("Besta orð "));
        best.push(m("span.best-word", s));
        best.push(", ");
        best.push(m("b",
          m(m.route.Link,
            { href: "/game/" + json.best_word_game },
            json.best_word_score
          )
        ));
        best.push(ts(" stig"));
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

      function vwStat(val?: number, icon?: string, suffix?: string): string | any[] {
        // Display a user statistics figure, eventually with an icon
        var txt = (val === undefined) ? "" : val.toString();
        if (suffix !== undefined)
          txt += suffix;
        return icon ? [glyph(icon), nbsp(), txt] : txt;
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
          m(".toggler", { id: 'own-toggler', title: ts("stats_choice") }, // "With or without robot games"
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
            { id: 'own-stats-human', className: 'stats-box', style: { display: "inline-block" } },
            [
              m(".stats-fig", { title: ts('Elo-stig') },
                s ? vwStat(s.locale_elo?.human_elo, "crown") : ""),
              m(".stats-fig.stats-games", { title: ts('Fjöldi viðureigna') },
                s ? vwStat(s.human_games, "th") : ""),
              m(".stats-fig.stats-win-ratio", { title: ts('Vinningshlutfall') },
                vwStat(winRatioHuman, "bookmark", "%")),
              m(".stats-fig.stats-avg-score", { title: ts('Meðalstigafjöldi') },
                vwStat(avgScoreHuman, "dashboard"))
            ]
          ) : "",
          sel == 2 ? m("div",
            { id: 'own-stats-all', className: 'stats-box', style: { display: "inline-block" } },
            [
              m(".stats-fig", { title: ts("Elo-stig") },
                s ? vwStat(s.locale_elo?.elo, "crown") : ""),
              m(".stats-fig.stats-games", { title: ts('Fjöldi viðureigna') },
                s ? vwStat(s.games, "th") : ""),
              m(".stats-fig.stats-win-ratio", { title: ts('Vinningshlutfall') },
                vwStat(winRatio, "bookmark", "%")),
              m(".stats-fig.stats-avg-score", { title: ts('Meðalstigafjöldi') },
                vwStat(avgScore, "dashboard"))
            ]
          ) : ""
        ]
      );
    }

  };
};

const PromoDialog: ComponentFunc<{
  view: View;
  kind: string;
  initFunc: () => void;
}> = (initialVnode) => {

  // A dialog showing promotional content fetched from the server

  const view = initialVnode.attrs.view;
  const model = view.model;
  let html = "";

  function _fetchContent(vnode: typeof initialVnode) {
    // Fetch the content
    model.loadPromoContent(
      vnode.attrs.kind, (contentHtml) => { html = contentHtml; }
    );
  }

  function _onUpdate(vnode: Vnode, initFunc: () => void) {
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
      let initFunc = vnode.attrs.initFunc;
      return m(".modal-dialog",
        { id: "promo-dialog", style: { visibility: "visible" } },
        m(".ui-widget.ui-widget-content.ui-corner-all",
          { id: "promo-form", className: "promo-" + vnode.attrs.kind },
          m("div",
            {
              id: "promo-content",
              onupdate: (vnode) => _onUpdate(vnode, initFunc)
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
  const model = initialVnode.attrs.model;
  let promise: { result: boolean; p: Promise<boolean>; } = undefined;

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
      p: new Promise<boolean>((resolve) => {
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
              placeholder: ts('Einkenni eða nafn'),
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

const DialogButton: ComponentFunc<{
  id: string; title: string; tabindex: number; onclick: EventHandler;
}> = (initialVnode) => {
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

const Info: ComponentFunc<{}> = (initialVnode) => {
  // Info icon, invoking the help screen
  return {
    view: (vnode) => {
      return m(".info",
        { title: ts("Upplýsingar og hjálp") },
        m(m.route.Link,
          { href: "/help", class: "iconlink" },
          glyph("info-sign")
        )
      );
    }
  };
}

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
  const selected: number = vnode.state.selected;
  const lis = vnode.state.lis;
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
  let vars: Params = {};
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

// Glyphicon utility function: inserts a glyphicon span
function glyph(icon: string, attrs?: object, grayed?: boolean): m.vnode {
  return m("span.glyphicon.glyphicon-" + icon + (grayed ? ".grayed" : ""), attrs);
}

function glyphGrayed(icon: string, attrs?: object): m.vnode {
  return m("span.glyphicon.glyphicon-" + icon + ".grayed", attrs);
}

// Utility function: inserts non-breaking space
function nbsp(n?: number): m.vnode {
  if (!n || n == 1)
    return m.trust("&nbsp;");
  let r: m.vnode[] = [];
  for (let i = 0; i < n; i++)
    r.push(m.trust("&nbsp;"));
  return m.fragment({}, r);
}
