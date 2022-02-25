/*

  Wait.ts

  Code for the WaitDialog and AcceptDialog components,
  used in the UI flow for timed games

  Copyright (C) 2021 Miðeind ehf.
  Original author: Vilhjálmur Þorsteinsson

  The Creative Commons Attribution-NonCommercial 4.0
  International Public License (CC-BY-NC 4.0) applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

*/

export { WaitDialog, AcceptDialog };

import { m, ComponentFunc } from "mithril";

import { mt, ts } from "i18n";

import { View, glyph, DialogButton, OnlinePresence } from "page";

import { attachFirebaseListener, detachFirebaseListener } from "channel";

const WaitDialog: ComponentFunc<{
  view: View; oppId: string; oppNick: string; oppName: string; duration: number;
}> = (initialVnode) => {

  // A dialog that is shown while the user waits for the opponent,
  // who issued a timed game challenge, to be ready

  const attrs = initialVnode.attrs;
  const view = attrs.view;
  const model = view.model;
  const duration = attrs.duration;
  const oppId = attrs.oppId;
  let oppNick = attrs.oppNick;
  let oppName = attrs.oppName;
  let oppOnline = false;
  const userId = model.state.userId;
  // Firebase path
  const path = 'user/' + userId + "/wait/" + oppId;
  // Flag set when the new game has been initiated
  let pointOfNoReturn = false;

  async function updateOnline() {
    // Initiate an online check on the opponent
    try {
      const json: { online: boolean; waiting: boolean; } = await m.request({
        method: "POST",
        url: "/initwait",
        body: { opp: oppId }
      });
      // If json.waiting is false, the initiation failed
      // and there is really no point in continuing to wait
      if (json && json.online && json.waiting)
        // The user is online
        oppOnline = true;
    }
    catch(e) {
    }
  }

  async function cancelWait() {
    // Cancel a pending wait for a timed game
    try {
      await m.request({
        method: "POST",
        url: "/cancelwait",
        body: {
          user: userId,
          opp: oppId
        }
      });
    }
    catch(e) {
    }
  }

  return {
    oninit: () => {
      updateOnline();
      // Attach a Firebase listener to the wait path
      attachFirebaseListener(path, (json: true | { game: string }) => {
        if (json !== true && json.game) {
          // A new game has been created and initiated by the server
          pointOfNoReturn = true;
          detachFirebaseListener(path);
          // We don't need to pop the dialog; that is done automatically
          // by the route resolver upon m.route.set()
          // Navigate to the newly initiated game
          m.route.set("/game/" + json.game);
        }
      });
    },
    view: () => {
      return m(".modal-dialog",
        { id: "wait-dialog", style: { visibility: "visible" } },
        m(".ui-widget.ui-widget-content.ui-corner-all", { "id": "wait-form" },
          [
            m(".chall-hdr",
              m("table", 
                m("tbody", 
                  m("tr", [
                    m("td", m("h1.chall-icon", glyph("time"))),
                    m("td.l-border", [
                      m(OnlinePresence, { id: "chall-online", userId: oppId, online: oppOnline }),
                      m("h1", oppNick),
                      m("h2", oppName)
                    ])
                  ])
                )
              )
            ),
            m(".wait-explain", [
              mt("p", [
                "Þú ert reiðubúin(n) að taka áskorun um viðureign með klukku, ",
                m("strong", [ "2 x ", duration.toString(), ts(" mínútur.") ])
              ]),
              mt("p", [
                "Beðið er eftir að áskorandinn ", m("strong", oppNick),
                " sé ", oppOnline ? "" : mt("span#chall-is-online", "álínis og "), "til í tuskið."
              ]),
              mt("p", "Leikur hefst um leið og áskorandinn bregst við. Handahóf ræður hvor byrjar."),
              mt("p", "Ef þér leiðist biðin geturðu hætt við og reynt aftur síðar.")
            ]),
            m(DialogButton,
              {
                id: "wait-cancel",
                title: ts("Hætta við"),
                // onmouseover: buttonOver,
                // onmouseout: buttonOut,
                onclick: (ev: MouseEvent) => {
                  // Cancel the wait status and navigate back to the main page
                  if (pointOfNoReturn) {
                    // Actually, it's too late to cancel
                    ev.preventDefault();
                    return;
                  }
                  detachFirebaseListener(path);
                  cancelWait();
                  view.popDialog();
                  ev.preventDefault();
                }
              },
              glyph("remove")
            )
          ]
        )
      );
    }
  }
};

const AcceptDialog: ComponentFunc<{
  view: View; oppId: string; oppNick: string;
}> = (initialVnode) => {

  // A dialog that is shown (usually briefly) while
  // the user who originated a timed game challenge
  // is linked up with her opponent and a new game is started

  const attrs = initialVnode.attrs;
  const view = attrs.view;
  const model = view.model;
  const oppId = attrs.oppId;
  let oppNick = attrs.oppNick;
  let oppReady = true;

  async function waitCheck() {
    // Initiate a wait status check on the opponent
    try {
      const json: { waiting: boolean; } = await m.request({
        method: "POST",
        url: "/waitcheck",
        body: { user: oppId }
      });
      if (json?.waiting) {
        // Both players are now ready: Start the timed game.
        // The newGame() call switches to a new route (/game),
        // and all open dialogs are thereby closed automatically.
        model.newGame(oppId, true);
      }
      else
        // Something didn't check out: keep the dialog open
        // until the user manually closes it
        oppReady = false;
    }
    catch(e) {
    }
  }

  return {
    oninit: () => waitCheck(),
    view: () => {
      return m(".modal-dialog",
        { id: "accept-dialog", style: { visibility: "visible" } },
        m(".ui-widget.ui-widget-content.ui-corner-all", { id: "accept-form" },
          [
            m(".chall-hdr", 
              m("table", 
                m("tbody", 
                  m("tr",
                    [
                      m("td", m("h1.chall-icon", glyph("time"))),
                      m("td.l-border", m("h1", oppNick))
                    ]
                  )
                )
              )
            ),
            m("div", { "style": { "text-align": "center", "padding-top": "32px" }},
              [
                m("p", mt("strong", "Viðureign með klukku")),
                mt("p",
                  oppReady ? "Athuga hvort andstæðingur er reiðubúinn..."
                  : ["Andstæðingurinn ", m("strong", oppNick), " er ekki reiðubúinn"]
                )
              ]
            ),
            m(DialogButton,
              {
                id: 'accept-cancel',
                title: ts('Reyna síðar'),
                onclick: (ev: MouseEvent) => {
                  // Abort mission
                  view.popDialog();
                  ev.preventDefault();
                }
              },
              glyph("remove")
            )
          ]
        )
      );
    }
  }
};
