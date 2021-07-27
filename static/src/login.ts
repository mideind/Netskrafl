/*

  Login.ts

  Login UI for Explo using the Mithril library

  Copyright (C) 2021 Miðeind ehf.
  Author: Vilhjálmur Þorsteinsson

  The GNU Affero General Public License, version 3, applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

  This UI is built on top of Mithril (https://mithril.js.org), a lightweight,
  straightforward JavaScript single-page reactive UI library.

*/

export { main };

import { m, ComponentFunc } from "mithril";
import { AnimatedExploLogo, NetskraflLegend } from "logo";

function main($state: { loginUrl: string; }) {
  // Mount the Mithril component tree as a child of the div.container element
  // on the login page (login-explo.html)
  const root = document.getElementById("container");
  m.mount(root,
    {
      view: () => { return m(LoginForm, { loginUrl: $state.loginUrl }); }
    }
  );
}

const LoginForm: ComponentFunc<{ loginUrl: string }> = (initialVnode) => {

  const loginUrl = initialVnode.attrs.loginUrl;
  let loginInProgress = false;

  function doLogin(ev: MouseEvent) {
    loginInProgress = true;
    ev.preventDefault();
    window.location.href = loginUrl;
  }

  return {
    view: () => {
      return m.fragment({}, [
        // This is visible on large screens
        m("div.loginform-large", [
          m(AnimatedExploLogo, {
            className: "login-logo",
            width: 200,
            withCircle: false,
            msStepTime: 150,
            once: true
          }),
          m(NetskraflLegend, {
            className: "login-legend",
            width: 600,
            msStepTime: 0
          }),
          m("div.welcome", [
            "Netskrafl er vettvangur ",
            m("b", "yfir 20.000 íslenskra skraflara"),
            " á netinu."
          ]),
          m("div.welcome", [
            "Netskrafl notar Google Accounts innskráningu, þá sömu og er notuð m.a. í Gmail. " +
            "Til að auðkenna þig sem notanda og halda innskráningunni virkri " +
            "er óhjákvæmilegt að geyma þar til gerða smáköku (",
            m("i", "cookie"), ") í vafranum þínum."
          ]),
          m("div.welcome",
            "Til auðkenningar tengir Netskrafl tölvupóstfang og nafn við hvern notanda. " +
            "Að öðru leyti eru ekki geymdar aðrar upplýsingar um notendur " +
            "en þær sem þeir skrá sjálfir. Annáll er haldinn um umferð um vefinn."
          ),
          m("div.login-btn-large",
            { onclick: doLogin },
            loginInProgress ? "Skrái þig inn..." : [
              "Innskrá ", m("span.glyphicon.glyphicon-play")
            ]
          )
        ]),
        // This is visible on small screens
        m("div.loginform-small", [
          m(AnimatedExploLogo, {
            className: "login-logo",
            width: 160,
            withCircle: false,
            msStepTime: 150,
            once: true
          }),
          m(NetskraflLegend, {
            className: "login-legend",
            width: 650,
            msStepTime: 0
          }),
          m("div.login-btn-small",
            { onclick: doLogin },
            loginInProgress ? "Skrái þig inn..." : "Innskrá "
          )
        ])
      ]);
    }
  };

};
