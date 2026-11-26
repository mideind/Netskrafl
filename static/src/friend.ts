/*

  Friend.ts

  Code for dialog components used in management of friends

  Copyright © 2025 Miðeind ehf.
  Original author: Vilhjálmur Þorsteinsson

  The Creative Commons Attribution-NonCommercial 4.0
  International Public License (CC-BY-NC 4.0) applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

*/

export { FriendPromoteDialog };

import { m, ComponentFunc, Vnode } from "mithril";

import { View, buttonOver, buttonOut } from "page";

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
