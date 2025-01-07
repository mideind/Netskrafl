/*

  Friend.ts

  Code for dialog components used in management of friends

  Copyright © 2025 Miðeind ehf.
  Original author: Vilhjálmur Þorsteinsson

  The Creative Commons Attribution-NonCommercial 4.0
  International Public License (CC-BY-NC 4.0) applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

*/

export {
  FriendPromoteDialog, FriendThanksDialog,
  FriendCancelDialog, FriendCancelConfirmDialog
};

import { m, ComponentFunc, Vnode } from "mithril";

import { View, glyph, nbsp, DialogButton, buttonOver, buttonOut } from "page";

function doRegisterSalesCloud(i,s,o,g,r,a,m): void {
  i['SalesCloudObject']=r;
  i[r]=i[r]||function(){(i[r].q=i[r].q||[]).push(arguments)},
  i[r].l=+new Date();
  a=s.createElement(o),
  m=s.getElementsByTagName(o)[0];
  a.src=g;
  m.parentNode.insertBefore(a,m)
}

function registerSalesCloud(): void {
  doRegisterSalesCloud(
     window, // i
     document, // s
     'script', // o
     'https://cdn.salescloud.is/js/salescloud.min.js', // g
     'salescloud', // r
     undefined, // a
     undefined // m
  );
}

const FriendPromoteDialog: ComponentFunc<{
  view: View;
}> = (initialVnode) => {

  // A dialog that offers friendship to the user

  const attrs = initialVnode.attrs;
  const view = attrs.view;
  const model = view.model;

  // Load the friendHTML if not already loaded
  model.loadFriendPromo();

  function onUpdate(vnode: Vnode) {
    if (!vnode || !vnode.dom)
      return;
    const noButtons = vnode.dom.getElementsByClassName("btn-promo-no") as HTMLCollectionOf<HTMLElement>;
    if (noButtons) {
      // Override onclick, onmouseover and onmouseout for No buttons
      for (let btn of noButtons) {
        btn.onclick = (ev: MouseEvent) => { view.popDialog(); ev.preventDefault(); };
        btn.onmouseover = buttonOver;
        btn.onmouseout = buttonOut;
      }
    }
    // Override onmouseover and onmouseout for Yes buttons
    const yesButtons = vnode.dom.getElementsByClassName("btn-promo-yes") as HTMLCollectionOf<HTMLElement>;
    if (yesButtons) {
      for (let btn of yesButtons) {
        btn.onmouseover = buttonOver;
        btn.onmouseout = buttonOut;
      }
      // We have a 'yes' button: register SalesCloud to handle it
      registerSalesCloud();
    }
  }

  return {
    view: () => {
      return m(".modal-dialog",
        { id: "promo-dialog", style: { visibility: "visible" } },
        m(".ui-widget.ui-widget-content.ui-corner-all", { id: "promo-form" },
          m(".promo-content",
            {
              oncreate: (vnode) => onUpdate(vnode),
              onupdate: (vnode) => onUpdate(vnode)
            },
            m.trust(model.friendHTML || "<p>Sæki texta...</p>")
          )
        )
      );
    }
  }
};

const FriendThanksDialog: ComponentFunc<{
  view: View;
}> = (initialVnode) => {

  // A dialog that offers friendship to the user

  const attrs = initialVnode.attrs;
  const view = attrs.view;
  const model = view.model;

  return {
    view: () => {
      return m(".modal-dialog",
        { id: "thanks-dialog", style: { visibility: "visible" } },
        m(".ui-widget.ui-widget-content.ui-corner-all", { id: "thanks-form" },
          [
            m(".thanks-content", [
              m("h3", "Frábært!"),
              m("p", [
                "Bestu þakkir fyrir að gerast ", glyph("coffee-cup"), nbsp(), m("b", "Vinur Netskrafls"), "."
              ]),
              m("p", [
                "Fríðindi þín virkjast um leið og greiðsla hefur verið staðfest. ",
                m("b", "Það getur tekið nokkrar mínútur."),
                " Þú færð staðfestingu og kvittun í tölvupósti."
              ]),
            ]),
            m(DialogButton,
              {
                id: "btn-thanks",
                title: "Áfram",
                onmouseover: buttonOver,
                onmouseout: buttonOut,
                onclick: (ev: MouseEvent) => {
                  // Go back to the main page
                  // The dialog is popped automatically upon the route change
                  m.route.set("/main");
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

const FriendCancelDialog: ComponentFunc<{
  view: View;
}> = (initialVnode) => {

  // A dialog that offers friendship to the user

  const attrs = initialVnode.attrs;
  const view = attrs.view;

  return {
    view: () => {
      return m(".modal-dialog",
        { id: "cancel-dialog", style: { visibility: "visible" } },
        m(".ui-widget.ui-widget-content.ui-corner-all", { id: "cancel-form" }, [
          m("div", { id: "cancel-content" }, [
            m("h3", "Hætta sem vinur Netskrafls?"),
            m("p", [
              "Viltu hætta sem ", glyph("coffee-cup"), nbsp(), m("b", "vinur Netskrafls"),
              " og missa þar með þau fríðindi sem því tengjast?"
            ]),
            m("p", "Fríðindin eru:"),
            m("ul", [
              m("li", [
                m("b", "Ótakmarkaður fjöldi viðureigna"), "í gangi samtímis", m("br"),
                "(í stað 8 að hámarki)"
              ]),
              m("li", [
                "Aðgangur að ", m("b", "yfirliti"), " í lok viðureignar"
              ]),
              m("li", [
                m("b", "Keppnishamur"), " án \"græna þumalsins\""
              ]),
            ]),
            m(DialogButton,
              {
                id: "btn-cancel-no",
                title: "Nei",
                onmouseover: buttonOver,
                onmouseout: buttonOut,
                onclick: (ev: MouseEvent) => {
                  ev.preventDefault();
                  view.popDialog();
                }
              },
              [ glyph("remove"), " Nei" ]
            ),
            m(DialogButton,
              {
                id: "btn-cancel-yes",
                title: "Já",
                onmouseover: buttonOver,
                onmouseout: buttonOut,
                onclick: (ev: MouseEvent) => {
                  ev.preventDefault();
                  view.popDialog();
                  // Initiate cancellation of the friendship
                  view.cancelFriendship();
                }
              },
              [ glyph("ok"), " Já, vil hætta" ]
            )
          ]),
        ])
      );
    }
  }
};

const FriendCancelConfirmDialog: ComponentFunc<{
  view: View;
}> = (initialVnode) => {

  // A dialog that confirms cancellation of friendship

  const attrs = initialVnode.attrs;
  const view = attrs.view;

  return {
    view: () => {
      return m(".modal-dialog",
        { id: "confirm-dialog", style: { visibility: "visible" } },
        m(".ui-widget.ui-widget-content.ui-corner-all", { id: "confirm-form" },
          [
            m(".confirm-content", [
              m("h3", "Staðfesting"),
              m("p", [
                "Þú ert ekki lengur skráð(ur) sem ",
                glyph("coffee-cup"), nbsp(), m("b", "vinur Netskrafls"), "."
              ]),
            ]),
            m(DialogButton,
              {
                id: "btn-thanks",
                title: "Áfram",
                onmouseover: buttonOver,
                onmouseout: buttonOut,
                onclick: (ev: MouseEvent) => {
                  ev.preventDefault();
                  view.popDialog();
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

