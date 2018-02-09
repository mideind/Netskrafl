/*

	Page.js

	Single page UI for Netskrafl using the Mithril library

  Copyright (C) 2015-2018 Miðeind ehf.
  Author: Vilhjalmur Thorsteinsson

  The GNU General Public License, version 3, applies to this software.
  For further information, see https://github.com/vthorsteinsson/Netskrafl

  This UI is built on top of Mithril (https://mithril.js.org), a lightweight,
  straightforward JavaScript single-page reactive UI library.

  The page is structured into models, actions and views,
  cf. https://github.com/pakx/the-mithril-diaries/wiki/Basic-App-Structure

*/

var main = (function() {

"use strict";

// Constants

var RACK_SIZE = 7;
var EMPTY_RACK = "       "; // RACK_SIZE spaces
var BAG_TILES_PER_LINE = 19;
var BLANK_TILES_PER_LINE = 6;
var LEGAL_LETTERS = "aábdðeéfghiíjklmnoóprstuúvxyýþæö";
var ROUTE_PREFIX = "/page#!";
var ROUTE_PREFIX_LEN = ROUTE_PREFIX.length;

function main() {
  // The main UI entry point, called from page.html

  var
    settings = getSettings(),
    model = createModel(settings),
    actions = createActions(model),
    view = createView(),
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
      { name: "login", route: "/login" },
      { name: "main", route: "/main" },
      { name: "help", route: "/help" },
      { name: "userprefs", route: "/userprefs" },
      { name: "game", route: "/game/:uuid" }
    ],
    settings = {
      paths: paths,
      defaultRoute: paths[0].route
    };
  return settings;
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
    // The current user information being edited, if any
    user: null,
    userErrors: null,
    // The help screen contents
    helpHTML: null,
    // Model methods
    loadGame: loadGame,
    loadHelp: loadHelp,
    loadUser: loadUser,
    saveUser: saveUser,
    addChatMessage: addChatMessage
  };

  function loadGame(uuid) {
    // Fetch a game state from the server, given a uuid
    console.log("Initiating load of game " + uuid);
    m.request({
      method: "POST",
      url: "/gamestate",
      data: { game: uuid }
    })
    .then(function(result) {
      if (!result.ok) {
        this.game = null;
        console.log("Game " + uuid + " could not be loaded");
      }
      else
        this.game = new Game(uuid, result.game);
    }.bind(this));
  }

  function loadHelp() {
    if (this.helpHTML !== null)
      return; // Already loaded
    m.request({
      method: "GET",
      url: "/rawhelp",
      deserialize: function(str) { return str; }
    })
    .then(function(result) {
      this.helpHTML = result;
    }.bind(this));
  }

  function loadUser() {
    // Fetch the preferences of the currently logged in user, if any
    m.request({
      method: "POST",
      url: "/loaduserprefs"
    })
    .then(function(result) {
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

  function saveUser(from_url) {
    // Update the preferences of the currently logged in user, if any
    m.request({
      method: "POST",
      url: "/saveuserprefs",
      data: this.user
    })
    .then(function(result) {
      if (result.ok) {
        // User preferences modified successfully on the server:
        // update the state variables that we're caching
        $state.userNick = this.user.nickname;
        $state.beginner = this.user.beginner;
        // Reset errors
        this.userErrors = null;
        // Dismiss the user dialog and go back to original route
        m.route.set(from_url);
      }
      else {
        // Error saving user prefs: show details, if available
        this.userErrors = result.err || null;
      }
    }.bind(this));
  }

  function addChatMessage(from_userid, msg, ts) {
    // Add a chat message to the game's chat message list
    if (this.game)
      this.game.addChatMessage(from_userid, msg, ts);
  }

}

function createActions(model) {

  initMediaListener();
  initFirebaseListener();
  return {
    onNavigateTo: onNavigateTo,
    onFullScreen: onFullScreen,
    onMobileScreen: onMobileScreen,
    onMoveMessage: onMoveMessage,
    onChatMessage: onChatMessage
  };

  function onNavigateTo(routeName, params) {
    // We have navigated to a new route
    model.routeName = routeName;
    model.params = params;
    if (routeName == "game") {
      // New game route: load the game into the model
      model.loadGame(params.uuid);
      if (model.game !== null)
        attachListenerToGame(params.uuid);
    }
    else
    if (routeName == "userprefs") {
      // Make sure that the current user's preferences are loaded
      model.loadUser();
    }
    else
    if (routeName == "help") {
      // Make sure that the help HTML is loaded upon first use
      model.loadHelp();
    }
    else {
      // Not a game route: delete the previously loaded game, if any
      model.game = null;
      // !!! TBD: Disconnect Firebase listeners
    }
  }

  function onFullScreen() {
    // Take action when min-width exceeds 768
    $state.uiFullscreen = true;
    // !!! TBD
    m.redraw();
  }

  function onMobileScreen () {
    $state.uiFullscreen = false;
    // !!! TBD
    m.redraw();
  }

  function onMoveMessage(json) {

  }

  function onChatMessage(json) {
    // Handle an incoming chat message
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
    model.addChatMessage(json.from_userid, json.msg, json.ts);
  }

  function mediaMinWidth667(mql) {
     if (mql.matches) {
        // Take action when min-width exceeds 667
        // (usually because of rotation from portrait to landscape)
        // The board tab is not visible, so the movelist is default
        // !!! TBD
     }
     else {
        // min-width is below 667
        // (usually because of rotation from landscape to portrait)
        // Make sure the board tab is selected
        // !!! TBD
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

  function attachListenerToGame(uuid) {
    // Listen to Firebase events on the /game/[gameId]/[userId] path
    var basepath = 'game/' + uuid + "/" + $state.userId + "/";
    // New moves
    attachFirebaseListener(basepath + "move", onMoveMessage);
    // New chat messages
    attachFirebaseListener(basepath + "chat", onChatMessage);
    // Listen to Firebase events on the /user/[userId] path
    // attachFirebaseListener('user/' + userId(), handleUserMessage);
  }

}

function createRouteResolver(model, actions, view) {
  return model.paths.reduce(function(acc, itm) {
    acc[itm.route] = {
      onmatch: function(params, route) {
        actions.onNavigateTo(itm.name, params);
      },
      render: function() {
        return view(model, actions);
      }
    };
    return acc;
  }, {});
}

function createView() {

  // Start a blinker interval function
  window.setInterval(blinker, 500);
  // Return a single view function for the app
  return vwApp;

  function vwApp(model, actions) {
    // Select the view based on the current route
    switch (model.routeName) {
      case "login":
        return vwLogin(model, actions);
      case "main":
        return vwMain(model, actions);
      case "game":
        return vwGame(model, actions);
      case "help":
        // A route parameter of ?q=N goes directly to the FAQ number N
        // A route parameter of ?tab=N goes directly to tab N (0-based)
        return vwHelp(model, actions, m.route.param("tab"), m.route.param("q"));
      case "userprefs":
        return vwUserPrefs(model, actions, m.route.param("f"));
      default:
        console.log("Unknown route name: " + model.routeName);
        return m("div", "Þessi vefslóð er ekki rétt");
    }
  }

  // Globally available controls

  function vwInfo() {
    // Info icon, invoking the help screen
    return m(".info", { title: "Upplýsingar og hjálp" },
      m("a.iconlink", { href: "/help", oncreate: m.route.link }, glyph("info-sign"))
    );
  }

  function vwUserId() {
    // User identifier at top right, opens user preferences
    var from_url = m.route.get();
    return m(".userid",
      {
        title: "Upplýsingar um leikmann",
        onclick: function()
          {
            m.route.set('/userprefs', { f: this });
          }.bind(from_url)
      },
      [ glyph("address-book"), nbsp(), $state.userNick ]
    );
  }

  function vwLogo() {
    // The Netskrafl logo
    return m(".logo",
      m("a.nodecorate",
        { href: '/main', oncreate: m.route.link }, 
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
    // !!! TBD
    return m("a", { href: "/main", oncreate: m.route.link }, "Go to main page!");
  }

  // A control that rigs up a tabbed view of raw HTML

  function vwTabsFromHtml(html, id, createFunc) {

    function updateVisibility(vnode) {
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
      updateVisibility(vnode);
    }

    function makeTabs(vnode) {
      // When the tabs are displayed for the first time, wire'em up
      var tabdiv = document.getElementById(id);
      if (!tabdiv)
        return;
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
        tablist[i].setAttribute("class", "ui-tabs-anchor");
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
      // Wire all hrefs that point to single-page URLs
      var anchors = tabdiv.querySelectorAll("a");
      for (i = 0; i < anchors.length; i++) {
        var a = anchors[i];
        var href = a.getAttribute("href");
        if (href && href.slice(0, ROUTE_PREFIX_LEN) == ROUTE_PREFIX) {
          // Single-page URL: wire it up (as if it had had an m.route.link on it)
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
      }
      // If a createFunc was specified, run it now
      if (createFunc)
        createFunc(vnode);
      // Finally, make the default tab visible and hide the others
      updateVisibility(vnode);
    }

    function updateSelection(vnode) {
      selectTab(vnode, m.route.param("tab"));
    }

    if (!html)
      return "";
    return m("div", { oncreate: makeTabs, onupdate: updateSelection }, m.trust(html));
  }

  // Help screen

  function vwHelp(model, actions, tabNumber, faqNumber) {

    function wireQuestions(vnode) {
      // Clicking on a question brings the corresponding answer into view
      // This is achieved by wiring up all contained a[href="#faq-*"] links
      var anchors = vnode.dom.querySelectorAll("a");
      for (var i = 0; i < anchors.length; i++) {
        var href = anchors[i].getAttribute("href");
        if (href.slice(0, 5) == "#faq-") {
          // This is a direct link to a question: wire it up
          anchors[i].onclick = function(href, ev) {
            vnode.state.selected = 1; // FAQ tab
            vnode.dom.querySelector(href).scrollIntoView();
            ev.preventDefault();
          }.bind(null, href);
        }
      }
      if (faqNumber !== undefined) {
        // Go to the FAQ tab and scroll the requested question into view
        vnode.state.selected = 1; // FAQ tab
        vnode.dom.querySelector("#faq-" +
          faqNumber.toString()).scrollIntoView();
      }
      else
      if (tabNumber !== undefined) {
        // Go to the requested tab
        vnode.state.selected = tabNumber;
      }
    }

    // Output literal HTML obtained from rawhelp.html on the server
    return [
      vwLogo(),
      vwUserId(),
      vwTabsFromHtml(model.helpHTML, "tabs", wireQuestions)
    ];
  }

  // User preferences screen

  function vwUserPrefsDialog(model, from_url) {

    var user = model.user;
    var err = model.userErrors || { };

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
            checked: state,
            id: id,
            name: id,
            type: 'checkbox',
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
      model.saveUser(from_url);
    }

    return m(".modal-dialog", { id: 'user-dialog' },
      m(".ui-widget.ui-widget-content.ui-corner-all", { id: 'user-form' },
        [
          m(".loginhdr", [ glyph("address-book"), " Upplýsingar um leikmann" ]),
          m("div", 
            m("form", { action: '', id: 'frm1', method: 'post', name: 'frm1' },
              [
                m(".dialog-spacer",
                  [
                    m("span.caption", "Einkenni:"),
                    m("input.text.username",
                      {
                        autofocus: '',
                        id: 'nickname',
                        maxlength: '15',
                        name: 'nickname',
                        required: '',
                        tabindex: '1',
                        type: 'text',
                        value: user.nickname || ""
                      }
                    ),
                    nbsp(),
                    m("span", { style: { "color": "red" } }, "*")
                  ]
                ),
                m(".explain", "Verður að vera útfyllt"),
                vwErrMsg("nickname"),
                m(".dialog-spacer",
                  [
                    m("span.caption", "Fullt nafn:"),
                    m("input.text.fullname",
                      {
                        id: 'full_name',
                        maxlength: '32',
                        name: 'full_name',
                        tabindex: '2',
                        type: 'text',
                        value: user.full_name || ""
                      }
                    )
                  ]
                ),
                m(".explain", "Valfrjálst - sýnt í notendalistum Netskrafls"),
                vwErrMsg("full_name"),
                m(".dialog-spacer",
                  [
                    m("span.caption", "Tölvupóstfang:"),
                    m("input.text.email",
                      {
                        id: 'email',
                        maxlength: '32',
                        name: 'email',
                        tabindex: '3',
                        type: 'text',
                        value: user.email || ""
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
                    vwToggler("audio", user.audio, "4",
                      glyph("volume-off"), glyph("volume-up"),
                      function() { playAudio("your-turn"); }),
                    m("span.subcaption", "Lúðraþytur eftir sigur:"),
                    vwToggler("fanfare", user.fanfare, "5",
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
                    vwToggler("newbag",
                      user.newbag, "7",
                      nbsp(), glyph("shopping-bag")),
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
                    vwToggler("fairplay",
                      user.fairplay, "8",
                      nbsp(), glyph("edit")),
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
          m(".modal-close",
            {
              id: 'user-ok',
              onclick: validate,
              onmouseout: buttonOut,
              onmouseover: buttonOver,
              tabindex: '9',
              title: 'Vista'
            },
            glyph("ok")
          ),
          m(".modal-close",
            {
              id: 'user-cancel',
              onclick: function() { m.route.set(from_url || "/main"); },
              onmouseout: buttonOut,
              onmouseover: buttonOver,
              tabindex: '10',
              title: 'Hætta við'
            },
            glyph("remove")
          ),
          m(".modal-close",
            {
              id: 'user-logout',
              onclick: function() { location.href = user.logout_url; },
              onmouseout: buttonOut,
              onmouseover: buttonOver,
              tabindex: '11',
              title: 'Skrá mig út'
            },
            [ glyph("log-out"), nbsp(), "Skrá mig út" ]
          ),
          user.friend ?
            m(".modal-close",
              {
                id: 'user-unfriend',
                onclick: function() { },
                onmouseout: buttonOut,
                onmouseover: buttonOver,
                tabindex: '11',
                title: 'Hætta sem vinur'
              },
              [ glyph("coffee-cup"), nbsp(), nbsp(), "Þú ert vinur Netskrafls!" ]
            ) :
            m(".modal-close",
              {
                id: 'user-friend',
                onclick: function() { },
                onmouseout: buttonOut,
                onmouseover: buttonOver,
                tabindex: '11',
                title: 'Gerast vinur',
              },
              [ glyph("coffee-cup"), nbsp(), nbsp(), "Gerast vinur Netskrafls" ]
            )
        ]
      )
    );
  }

  function vwUserPrefs(model, actions, from_url) {
    if (model.user)
      return vwUserPrefsDialog(model, from_url);
    return m("span", "Sæki upplýsingar um notanda...");
  }

  // Main screen

  function vwMain(model, actions) {
    // Main screen with tabs
    // !!! TBD
    return m("main",
      [
        m("h1", { class: "title" }, "The main screen"),
        m("div", m("a", { href: "/" }, "Old main screen")),
        m("div", m("a", { href: "/game/cb23b9a1-e132-11e7-bbfd-34028601001c", oncreate: m.route.link }, "Open game 1")),
        vwInfo()
      ]
    );
  }

  // Game screen

  function vwGame(model, actions) {
    // A view of a game, in-progress or finished
    var game = model.game;
    if (!game)
      // No associated game
      return m(".game-container", "");
    var bag = game ? game.bag : "";
    var newbag = game ? game.newbag : true;
    return m(".game-container",
      [
        vwBoardArea(game),
        vwRightColumn(game),
        vwBag(bag, newbag),
        game.askingForBlank ? vwBlankDialog(game) : "",
        vwBack(),
        $state.beginner ? vwBeginner(game) : "",
        vwInfo()
      ]
    );
  }

  function vwRightColumn(game) {
    // A container for the right-side header and area components
    return m(".rightcol",
      [
        vwRightHeading(game),
        vwRightArea(game)
      ]
    );
  }

  function vwRightHeading(game) {
    // The right-side heading on the game screen
    var fairplay = game ? game.fairplay : false;
    var player = game ? game.player : 0;
    var sc0 = game ? game.scores[0].toString() : "";
    var sc1 = game ? game.scores[1].toString() : "";
    return m(".heading",
      [
        m("h3.playerleft" + (player == 1 ? ".autoplayercolor" : ".humancolor"),
          vwPlayerName(game, "left")),
        m("h3.playerright" + (player == 1 ? ".humancolor" : ".autoplayercolor"),
          vwPlayerName(game, "right")),
        m("h3.scoreleft", sc0),
        m("h3.scoreright", sc1),
        m("h3.clockleft"),
        m("h3.clockright"),
        m(".clockface", glyph("time")),
        m(".fairplay",
          fairplay ? { style: "display:block" } : { },
          m("span.fairplay-btn.large", { title: "Skraflað án hjálpartækja" } ))
      ]
    );
  }

  function vwPlayerName(game, side) {
    // Displays a player name, handling both human and robot players
    // as well as left and right side, and local and remote colors
    var apl0 = game && game.autoplayer[0];
    var apl1 = game && game.autoplayer[1];
    var nick0 = game ? game.nickname[0] : "";
    var nick1 = game ? game.nickname[1] : "";
    var player = game ? game.player : 0;
    var localturn = game ? game.localturn : false;
    var tomove;

    function lookAtPlayer(player, side, fromUrl) {
      if (player === 0 || player === 1) {
        if (player == side)
          // The player is clicking on himself
          m.route.set('/userprefs', { f: fromUrl });
        else {
          // The player is clicking on the opponent:
          // show the opponent's track record
          // !!! TBD
        }
      }
    }

    var fromUrl = m.route.get();

    if (side == "left") {
      // Left side player
      if (apl0)
        // Player 0 is a robot (autoplayer)
        return m(".robot-btn.left",
          [ glyph("cog"), nbsp(), nick0 ]);
      tomove = (localturn ^ (player === 0)) ? "" : ".tomove";
      return m((player === 0 || player === 1) ? ".player-btn.left" + tomove : ".robot-btn.left",
        { id: "player-0", onclick: lookAtPlayer.bind(null, player, 0, fromUrl) },
        [ m("span.left-to-move"), nick0 ]
      );
    }
    else {
      // Right side player
      if (apl1)
        // Player 1 is a robot (autoplayer)
        return m(".robot-btn.right",
          [ glyph("cog"), nbsp(), nick1 ]);
      tomove = (localturn ^ (player === 1)) ? "" : ".tomove";
      return m((player === 0 || player === 1) ? ".player-btn.right" + tomove : ".robot-btn.right",
        { id: "player-1", onclick: lookAtPlayer.bind(null, player, 1, fromUrl) },
        [ m("span.right-to-move"), nick1 ]
      );
    }
  }

  function vwRightArea(game) {
    // A container for the tabbed right-side area components
    var sel = (game && game.sel) ? game.sel : "movelist";
    // Show the chat tab unless the opponent is an autoplayer
    var component = null;
    if (sel == "movelist")
      component = vwMovelist(game);
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

  function vwTabGroup(game) {
    // A group of clickable tabs for the right-side area content
    var sel = (game && game.sel) ? game.sel : "movelist";
    var showchat = game ? !(game.autoplayer[0] || game.autoplayer[1]) : false;
    var r = [
      vwTab(game, "board", "Borðið", "grid"),
      vwTab(game, "movelist", "Leikir", "show-lines"),
      vwTab(game, "twoletter", "Tveggja stafa orð", "life-preserver"),
      vwTab(game, "games", "Viðureignir", "flag")
    ];
    if (showchat)
      // Add chat tab
      r.push(vwTab(game, "chat", "Spjall", "conversation"));
    return m.fragment({}, r);
  }

  function vwTab(game, tabid, title, icon) {
    // A clickable tab for the right-side area content
    var sel = (game && game.sel) ? game.sel : "movelist";
    return m(".right-tab" + (sel == tabid ? ".selected" : ""),
      {
        title: title,
        onclick: function() { if (game) game.sel = tabid; },
        id: "tab-" + tabid
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
            m.trust(escMsg))
          );
        }
      }
      return r;
    }

    function focus(vnode) {
      // Put the focus on the DOM object associated with the vnode
      vnode.dom.focus();
    }

    if (game && game.messages === null)
      // No messages loaded yet: kick off async message loading
      // for the current game
      game.loadMessages("game:" + game.uuid);

    return m(".chat", { style: "z-index: 6" }, // Appear on top of board on mobile
      [
        m(".chat-area", { id: 'chat-area' }, chatMessages()),
        m(".chat-input",
          [
            m("input.chat-txt[id='msg'][maxlength='254'][name='msg'][type='text']",
              { oncreate: focus, onupdate: focus }),
            m(".modal-close[id='chat-send'][title='Senda']",
              { onclick:
                function() {
                  if (game) {
                    game.sendMessage("game:" + game.uuid, getInput("msg"));
                    setInput("msg", "");
                  }
                }
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
        if (player == 0)
          leftTotal = Math.max(leftTotal + score, 0);
        else
          rightTotal = Math.max(rightTotal + score, 0);
        r.push(
          vwMove(game, mlist[i],
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

    function scrollMovelistToBottom() {
      // If we're displaying a 'fresh' game (just updated),
      // scroll the last move into view
      if (!game || !game.isFresh)
        return;
      game.isFresh = false;
      var movelist = document.querySelectorAll("div.movelist .move");
      if (movelist.length)
        movelist[movelist.length - 1].scrollIntoView();
    }

    var bag = game ? game.bag : "";
    var newbag = game ? game.newbag : true;
    return m(".movelist-container",
      { style: "z-index: 6" }, // Appear on top of board on mobile
      [
        m(".movelist",
          { oninit: scrollMovelistToBottom, onupdate: scrollMovelistToBottom },
          movelist()
        ),
        vwBag(bag, newbag) // Visible on mobile
      ]
    );
  }

  function vwMove(game, move, info) {
    // Displays a single move

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
      return m(".move.gameover",
        [
          m("span.gameovermsg", tiles),
          m("span.statsbutton", { onclick: "navToReview()" }, "Skoða yfirlit")
        ]
      );
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
    if (player == 0) {
      // Move by left side player
      return m(".move.leftmove." + cls, attribs,
        [
          m("span.total", leftTotal),
          m("span.score" + (move.highlighted ? ".highlight" : ""), score),
          m("span." + wrdclass, [ m("i", tiles), co ])
        ]
      );
    }
    else {
      // Move by right side player
      return m(".move.rightmove." + cls, attribs,
        [
          m("span." + wrdclass, [ co, m("i", tiles) ]),
          m("span.score" + (move.highlighted ? ".highlight" : ""), score),
          m("span.total", rightTotal)
        ]
      );
    }
  }

  function vwGames(game) {
    // The game list tab

    function games() {
      var r = [];
      var numMyTurns = 0;
      if (game.gamelist == null)
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
              m("a",
                {
                  href: "/game/" + item.url.slice(-36), // !!! TO BE FIXED
                  oncreate: m.route.link,
                  onupdate: m.route.link
                },
                [
                  m(".at-top-left", m(".tilecount", m(".oc", opp))),
                  m(".at-top-left",
                    m(".tilecount.trans",
                      m(".tc" + winLose, { style: "width:" + item.tile_count.toString() + "%" }, opp)
                    )
                  )
                ]
              )
            )
          );
          numMyTurns++;
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
        style: "visibility: visible"
      },
      m(".ui-widget.ui-widget-content.ui-corner-all", { id: 'blank-form' },
        [
          m("p", "Hvaða staf táknar auða flísin?"),
          m(".rack.blank-rack", m("table.board", { id: 'blank-meaning' }, blankLetters())),
          m(".modal-close",
            {
              id: 'blank-close',
              onclick: function(ev) {
                ev.preventDefault();
                game.cancelBlankDialog();
              },
              onmouseover: buttonOver,
              onmouseout: buttonOut,
              title: 'Hætta við'
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
      m("a.backlink", { href: "/main", oncreate: m.route.link },
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
      ];
      r = r.concat(vwDialogs(game));
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
    if (coord[0] == 'R' || t.draggable)
      classes.push("racktile");
    if (t.freshtile) {
      classes.push("freshtile");
      // Make fresh tiles appear sequentally by animation
      var ANIMATION_STEP = 80; // Milliseconds
      var delay = (t.index * ANIMATION_STEP).toString() + "ms";
      attrs.style = "animation-delay: " + delay + "; " +
        "-webkit-animation-delay: " + delay + ";";
    }
    if (t.highlight !== undefined) {
      // highlight0 is the local player color (yellow/orange)
      // highlight1 is the remote player color (green)
      classes.push("highlight" + t.highlight);
      if (t.player == parseInt(t.highlight))
        // This tile was originally laid down by the other player
        classes.push("dim");
    }
    if (t.draggable && game.showingDialog === null && !game.over) {
      // Make the tile draggable, unless we're showing a dialog
      attrs.draggable = "true";
      attrs.ondragstart = function(ev) {
        ev.dataTransfer.effectAllowed = "copyMove";
        ev.dataTransfer.setData("text", coord);
        ev.redraw = false;
      };
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
      cls = ".blinking";
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
        }.bind(null, coord)
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
      for (var col = 1; col < 16; col++)
        r.push(m("td", col.toString()));
      return m("tr.colid", r);
    }

    function row(rowid) {
      // Each row of the board
      var r = [];
      r.push(m("td.rowid", rowid));
      for (var col = 1; col <= 15; col++) {
        var coord = rowid + col.toString();
        if (game && (coord in game.tiles))
          // There is a tile in this square: render it
          r.push(m("td", { id: coord, key: coord }, vwTile(game, coord)));
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
    return m(sc.join("."), game.currentScore === undefined ? "?" : game.currentScore);
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
      r.push(m(".challenge" +
        (((tilesPlaced && !lastChallenge) || showingDialog) ? ".disabled" : ""),
        {
          onclick: function() { game.submitChallenge(); },
          onmouseout: buttonOut,
          onmouseover: buttonOver,
          title: 'Véfenging (röng kostar 10 stig)'
        }
      ));
    if (showChallengeInfo)
      r.push(m(".chall-info"));
    if (showRecall)
      r.push(m(".recallbtn",
        {
          onclick: function() { game.resetRack(); },
          onmouseout: buttonOut,
          onmouseover: buttonOver,
          title: 'Færa stafi aftur í rekka'
        },
        glyph("down-arrow")
      ));
    if (showScramble)
      r.push(m(".scramblebtn",
        {
          onclick: function() { game.rescrambleRack(); },
          onmouseout: buttonOut,
          onmouseover: buttonOver,
          title: 'Stokka upp rekka'
        },
        glyph("random")
      ));
    if (showMove)
      r.push(m(".submitmove" +
        ((!tilesPlaced || showingDialog) ? ".disabled" : ""),
        {
          onclick: function() { game.submitMove(); },
          onmouseout: buttonOut,
          onmouseover: buttonOver,
          title: 'Leika'
        },
        [ "Leika", glyph("play") ]
      ));
    if (showPass)
      r.push(m(".submitpass" +
        (((tilesPlaced && !lastChallenge) || showingDialog) ? ".disabled" : ""),
        {
          onclick: function() { game.submitPass(); },
          onmouseout: buttonOut,
          onmouseover: buttonOver,
          title: 'Pass'
        },
        glyph("forward")
      ));
    if (showExchange)
      r.push(m(".submitexchange" +
        ((tilesPlaced || showingDialog || !exchangeAllowed) ? ".disabled" : ""),
        {
          onclick: function() { game.submitExchange(); },
          onmouseout: buttonOut,
          onmouseover: buttonOver,
          title: 'Skipta stöfum'
        },
        glyph("refresh")
      ));
    if (showResign)
      r.push(m(".submitresign" +
        (showingDialog ? ".disabled" : ""),
        {
          onclick: function() { game.submitResign(); },
          onmouseout: buttonOut,
          onmouseover: buttonOver,
          title: 'Gefa viðureign'
        },
        glyph("fire")
      ));
    // !!! Add opp-turn and force-resign
    if (tilesPlaced)
      r.push(vwScore(game));
    // Is the server processing a move?
    if (game.moveInProgress)
      r.push(m(".waitmove", { style: "display:block" }));
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
      return m(".error", { style: "visibility: visible" },
        [
          glyph("exclamation-sign"),
          errorMessages[game.currentError]
        ]
      );
    }
    return "";
  }

  function vwDialogs(game) {
    // Show prompt dialogs, if any
    var r = [];
    if (game.showingDialog === null)
      return r;
    if (game.showingDialog == "chall-info")
      r.push(m(".chall-info", { style: "visibility: visible" },
        [
          glyph("info-sign"), nbsp(),
          m("span.pass-explain", "Andstæðingur tæmdi rekkann - þú getur véfengt eða sagt pass")
        ]
      ));
    if (game.showingDialog == "resign")
      r.push(m(".resign", { style: "visibility: visible" },
        [
          glyph("exclamation-sign"), nbsp(), "Viltu gefa leikinn?", nbsp(),
          m("span.mobile-break", m("br")),
          m("span.yesnobutton", { onclick: function() { game.confirmResign(true); } },
            [ glyph("ok"), "Já" ]
          ),
          m("span.mobile-space"),
          m("span.yesnobutton", { onclick: function() { game.confirmResign(false); } },
            [ glyph("remove"), "Nei" ]
          )
        ]
      ));
    if (game.showingDialog == "pass")
      r.push(m(".pass", { style: "visibility: visible" },
        [
          glyph("forward"), nbsp(), "Segja pass?",
          m("span.pass-explain", "2x3 pöss í röð ljúka viðureign"),
          nbsp(), m("span.mobile-break", m("br")),
          m("span.yesnobutton", { onclick: function() { game.confirmPass(true); } },
            [ glyph("ok"), "Já" ]
          ),
          m("span.mobile-space"),
          m("span.yesnobutton", { onclick: function() { game.confirmPass(false); } },
            [ glyph("remove"), "Nei" ]
          )
        ]
      ));
    if (game.showingDialog == "pass-last")
      r.push(m(".pass-last", { style: "visibility: visible" },
        [
          glyph("forward"), nbsp(), "Segja pass?",
          m("span.pass-explain", "Viðureign lýkur þar með"),
          nbsp(),
          m("span.mobile-break", m("br")),
          m("span.yesnobutton", { onclick: function() { game.confirmPass(true); } },
            [ glyph("ok"), "Já" ]
          ),
          m("span.mobile-space"),
          m("span.yesnobutton", { onclick: function() { game.confirmPass(false); } },
            [ glyph("remove"), "Nei" ]
          )
        ]
      ));
    if (game.showingDialog == "exchange")
      r.push(m(".exchange", { style: "visibility: visible" },
        [
          glyph("refresh"), nbsp(),
          "Smelltu á flísarnar sem þú vilt skipta", nbsp(),
          m("span.mobile-break", m("br")),
          m("span.yesnobutton[title='Skipta']", { onclick: function() { game.confirmExchange(true); } },
            glyph("ok")),
          m("span.mobile-space"),
          m("span.yesnobutton[title='Hætta við']", { onclick: function() { game.confirmExchange(false); } },
            glyph("remove"))
        ]
      ));
    if (game.showingDialog == "chall")
      r.push(m(".chall", { style: "visibility: visible" },
        [
          glyph("ban-circle"), nbsp(), "Véfengja lögn?",
          m("span.pass-explain", "Röng véfenging kostar 10 stig"), nbsp(),
          m("span.mobile-break", m("br")),
          m("span.yesnobutton", { onclick: function() { game.confirmChallenge(true); } },
            [ glyph("ok"), "Já" ]
          ),
          m("span.mobile-space"),
          m("span.yesnobutton", { onclick: function() { game.confirmChallenge(false); } },
            [ glyph("remove"), "Nei" ]
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
          this.page == 0 ? page0 : page1
        );
      }
    };
  }

  function vwBeginner(game) {
    // Show the board color guide
    return m(".board-help[title='Hvernig reitirnir margfalda stigin']",
      [
        m(".board-help-close[title='Loka þessari hjálp']",
          {
            onclick: function () {
              // Close the guide and set a preference not to see it again
              $state.beginner = false;
              game.setUserPref({ beginner: false });
            }
          },
          m("span.glyphicon.glyphicon-remove")
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

  function blinker() {
    // Toggle the 'over' class on all elements having the 'blinking' class
    var blinkers = document.getElementsByClassName('blinking');
    for (var i = 0; i < blinkers.length; i++)
      blinkers[i].classList.toggle("over");
  }

}

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
  return String(string).replace(/[&<>"'\/]/g, function (s) {
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
function glyph(icon, attrs) { return m("span.glyphicon.glyphicon-" + icon, attrs); }

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

