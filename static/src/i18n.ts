/*

  i8n.ts

  Single page UI for Explo using the Mithril library

  Copyright (C) 2021 Miðeind ehf.
  Author: Vilhjálmur Þorsteinsson

  The Creative Commons Attribution-NonCommercial 4.0
  International Public License (CC-BY-NC 4.0) applies to this software.
  For further information, see https://github.com/mideind/Netskrafl


  This module contains internationalization (i18n) utility functions,
  allowing for translation of displayed text between languages.

  Text messages for individual locales are loaded from the
  /static/assets/messages.json file, which is fetched from the server.

*/

export { t, mt, loadMessages };

import { m, VnodeChildren } from "mithril";

// Type declarations
type Messages = { [key: string]: { [locale: string]: string | string[] }};
type FlattenedMessages = { [key: string]: { [locale: string]: string }};
type Interpolations = { [key: string]: string };

// Current exact user locale and fallback locale ("en" for "en_US"/"en_UK"/...)
// This is overwritten in setLocale()
let currentLocale = "is_IS";
let currentFallback = "is";

// Regex that matches embedded interpolations such as "Welcome, {username}!"
// Interpolation identifiers should only contain ASCII characters, digits and '_'
const rex = /{\s*(\w+)\s*}/g;

let messages: FlattenedMessages = {};
let messagesLoaded = false;

function setLocale(locale: string, m: Messages): void {
  // Set the current i18n locale and fallback
  currentLocale = locale;
  currentFallback = locale.split("_")[0];
  // Flatten the Messages structure, enabling long strings
  // to be represented as string arrays in the messages.json file
  messages = {};
  for (let key in m) {
    for (let lc in m[key]) {
      let s = m[key][lc];
      if (Array.isArray(s))
        s = s.join("");
      if (messages[key] === undefined)
        messages[key] = {};
      messages[key][lc] = s;
    }
  }
  messagesLoaded = true;
}

async function loadMessages(locale: string) {
  // Load the internationalization message JSON file from the server
  // and set the user's locale
  try {
    const messages: Messages = await m.request({
      method: "GET",
      url: "/static/assets/messages.json",
    });
    setLocale(locale, messages);
  }
  catch {
    setLocale(locale, {});
  }
}

function t(key: string, ips: Interpolations = {}): string {
  // Main text translation function, supporting interpolation
  const msgDict = messages[key];
  if (msgDict === undefined)
    // No dictionary for this key - may actually be a missing entry
    return messagesLoaded ? key : "";
  // Lookup exact locale, then fallback, then resort to returning the key
  const message = msgDict[currentLocale] || msgDict[currentFallback] || key;
  // If we have an interpolation object, do the interpolation first
  return Object.keys(ips).length ? interpolate(message, ips) : message;
}

function mt(cls: string, children: VnodeChildren): VnodeChildren {
  // Wrapper for the Mithril m() function that auto-translates
  // string and array arguments
  if (typeof children == "string") {
    return m(cls, t(children));
  }
  if (Array.isArray(children)) {
    return m(cls, children.map((item) => (typeof item == "string") ? t(item) : item));
  }
  return m(cls, children);
}

function interpolate(message: string, ips: Interpolations) {
  // Replace interpolation placeholders with their corresponding values
  return message.replace(rex, (match, key) => ips[key] || match);
}
