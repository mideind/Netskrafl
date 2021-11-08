/*

  Login.ts

  Login UI for Explo using the Mithril library

  Copyright (C) 2021 Miðeind ehf.
  Author: Vilhjálmur Þorsteinsson

  The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

  This UI is built on top of Mithril (https://mithril.js.org), a lightweight,
  straightforward JavaScript single-page reactive UI library.

*/

export { main };

import { m, ComponentFunc } from "mithril";
import { AnimatedExploLogo, NetskraflLegend } from "logo";
import { mt, t, loadMessages } from "i18n";

function main($state: { loginUrl: string; locale: string; }) {
  // Mount the Mithril component tree as a child of the div.container element
  // on the login page (login-explo.html)
  loadMessages($state.locale);
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
          mt("div.welcome", "welcome_0"),
          mt("div.welcome", "welcome_1"),
          mt("div.welcome", "welcome_2"),
          m("div.login-btn-large",
            { onclick: doLogin },
            loginInProgress ? t("Skrái þig inn...") : [
              t("Innskrá") + " ", m("span.glyphicon.glyphicon-play")
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
            loginInProgress ? t("Skrái þig inn...") : t("Innskrá")
          )
        ])
      ]);
    }
  };

};
