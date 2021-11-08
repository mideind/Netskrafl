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

export { t, ts, mt, loadMessages };

import { m, VnodeChildren } from "mithril";

// Type declarations
type Messages = { [key: string]: { [locale: string]: string | string[] }};
type FlattenedMessages = { [key: string]: { [locale: string]: VnodeChildren }};
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

function setLocale(locale: string, msgs: Messages): void {
  // Set the current i18n locale and fallback
  currentLocale = locale;
  currentFallback = locale.split("_")[0];
  // Flatten the Messages structure, enabling long strings
  // to be represented as string arrays in the messages.json file
  messages = {};
  for (let key in msgs) {
    for (let lc in msgs[key]) {
      let s: VnodeChildren = msgs[key][lc];
      if (Array.isArray(s))
        s = s.join("");
      if (messages[key] === undefined)
        messages[key] = {};
      // If the string s contains HTML markup of the form <tag>...</tag>,
      // convert it into a list of Mithril Vnode children corresponding to
      // the text and the tags
      if (s.match(/<[a-z]+>/)) {
        // Looks like the string contains HTML markup
        const vnodes: VnodeChildren[] = [];
        let i = 0;
        let tagMatch: RegExpMatchArray;
        while (i < s.length && (tagMatch = s.slice(i).match(/<[a-z]+>/))) {
          // Found what looks like an HTML tag
          // Calculate the index of the enclosed text within s
          const tag = tagMatch[0];
          let j = i + tagMatch.index + tag.length;
          // Find the end tag
          let end = s.indexOf("</" + tag.slice(1), j);
          if (end < 0) {
            // No end tag - skip past this weirdness
            i = j;
            continue;
          }
          // Add the text preceding the tag
          if (tagMatch.index > 0)
            vnodes.push(s.slice(i, i + tagMatch.index));
          // Create the Mithril node corresponding to the tag and the enclosed text
          // and add it to the list
          vnodes.push(m(tag.slice(1, -1), s.slice(j, end)));
          // Advance the index past the end of the tag
          i = end + tag.length + 1;
        }
        // Push the final text part, if any
        if (i < s.length)
          vnodes.push(s.slice(i));
        // Reassign s to the list of vnodes
        s = vnodes;
      }
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

function t(key: string, ips: Interpolations = {}): VnodeChildren {
  // Main text translation function, supporting interpolation
  // and HTML tag substitution
  const msgDict = messages[key];
  if (msgDict === undefined)
    // No dictionary for this key - may actually be a missing entry
    return messagesLoaded ? key : "";
  // Lookup exact locale, then fallback, then resort to returning the key
  const message = msgDict[currentLocale] || msgDict[currentFallback] || key;
  // If we have an interpolation object, do the interpolation first
  return Object.keys(ips).length ? interpolate(message, ips) : message;
}

function ts(key: string, ips: Interpolations = {}): string {
  // String translation function, supporting interpolation
  // but not HTML tag substitution
  const msgDict = messages[key];
  if (msgDict === undefined)
    // No dictionary for this key - may actually be a missing entry
    return messagesLoaded ? key : "";
  // Lookup exact locale, then fallback, then resort to returning the key
  const message = msgDict[currentLocale] || msgDict[currentFallback] || key;
  if (typeof message != "string")
    // This is actually an error - the client should be calling t() instead
    return "";
  // If we have an interpolation object, do the interpolation first
  return Object.keys(ips).length ? interpolate_string(message, ips) : message;
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

function interpolate(message: VnodeChildren, ips: Interpolations): VnodeChildren {
  // Replace interpolation placeholders with their corresponding values
  if (typeof message == "string") {
    return message.replace(rex, (match, key) => ips[key] || match);
  }
  if (Array.isArray(message)) {
    return message.map((item) => interpolate(item, ips));
  }
  return message;
}

function interpolate_string(message: string, ips: Interpolations): string {
  // Replace interpolation placeholders with their corresponding values
  return message.replace(rex, (match, key) => ips[key] || match);
}
