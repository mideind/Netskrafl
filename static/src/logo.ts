/*

  Logo.ts

  Code for an animated Explo logo component

  Copyright (C) 2021 Miðeind ehf.
  Original author: Vilhjálmur Þorsteinsson

  The GNU Affero General Public License, version 3, applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

*/

export { AnimatedExploLogo };

import { m, ComponentFunc } from "mithril";

// SVG code for logo
const header = `<svg width="134" height="134" viewBox="-32 -8 134 134" fill="none" xmlns="http://www.w3.org/2000/svg">`;
const circle = `<circle class="shadow" cx="35" cy="59" r="63" fill="#ffffff"/>`;
const pieces: string[] = [
  `<path d="M65.2672 12.542L54.3998 18.813L43.5323 25.146L32.6649 18.813L21.7354 12.542L43.5323 0L65.2672 12.542Z" fill="#FDC12C"/>`,
  `<path d="M43.5323 25.1457V37.6877L21.7354 25.1457V12.5416L43.5323 25.1457Z" fill="#E69419"/>`,
  `<path d="M65.2661 12.5416V25.1457L43.5312 37.6877V25.1457L65.2661 12.5416Z" fill="#F8DA95"/>`,
  `<path d="M43.5318 37.6847L32.6644 43.9557L21.7349 50.2267L10.8674 43.9557L0 37.6847L21.7349 25.1427L43.5318 37.6847Z" fill="#AA3731"/>`,
  `<path d="M21.7349 50.23V62.7719L0 50.23V37.688L21.7349 50.23Z" fill="#721D19"/>`,
  `<path d="M65.2672 50.23L54.3998 56.501L43.5323 62.7719L32.6028 56.501L21.7354 50.23L43.5323 37.688L65.2672 50.23Z" fill="#669256"/>`,
  `<path d="M43.5323 62.7716V75.3756L21.7354 62.7716V50.2296L43.5323 62.7716Z" fill="#496A38"/>`,
  `<path d="M65.2661 50.2296V62.7716L43.5312 75.3756V62.7716L65.2661 50.2296Z" fill="#B7C7AD"/>`,
  `<path d="M43.5318 75.3754L32.6644 81.6464L21.7349 87.9174L10.8674 81.6464L0 75.3754L21.7349 62.7714L43.5318 75.3754Z" fill="#83C8CE"/>`,
  `<path d="M21.7349 87.918V100.46L0 87.918V75.376L21.7349 87.918Z" fill="#5699A5"/>`,
  `<path d="M65.2672 87.918L54.3998 94.1889L43.5323 100.46L32.6649 94.1889L21.7354 87.918L43.5323 75.376L65.2672 87.918Z" fill="#E39FA5"/>`,
  `<path d="M43.5323 100.46V113.002L21.7354 100.46V87.9177L43.5323 100.46Z" fill="#B6676D"/>`,
  `<path d="M65.2661 87.9177V100.46L43.5312 113.002V100.46L65.2661 87.9177Z" fill="#EACFD1"/>`
];
const footer = `</svg>`;

const WIDTH = 134;
const NUM_STEPS = pieces.length;

const AnimatedExploLogo: ComponentFunc<{
  width: number; withCircle: boolean; msStepTime: number;
}> = (initialVnode) => {

  // Animation step time in milliseconds
  const msStepTime = initialVnode.attrs.msStepTime || 0;
  const width = initialVnode.attrs.width;
  const scale = width / WIDTH;
  const withCircle = initialVnode.attrs.withCircle || false;

  function doStep() {
    // Check whether we're still in the delay period

    // Check if we need to reverse direction
    if (this.delta < 0 && this.step == 0)
      this.delta = 1;
    else
    if (this.delta > 0 && this.step == NUM_STEPS)
      this.delta = -1;
    this.step += this.delta;
    m.redraw();
  }

  return {
    step: msStepTime ? 0 : NUM_STEPS, // Current step number
    delta: 1, // Modification in each step, 1 or -1
    ival: 0, // Interval timer id
    oninit: function(vnode) {
      if (msStepTime)
        this.ival = setInterval(doStep.bind(this), msStepTime);
    },
    onremove: function(vnode) {
      if (this.ival != 0) {
        clearInterval(this.ival);
        this.ival = 0;
      }
    },
    view: function(vnode) {
      let r: string[] = [ header ];
      if (withCircle)
        // Include white background circle, with drop shadow
        r.push(circle);
      for (let i = 0; i < this.step; i++)
        r.push(pieces[i]);
      r.push(footer);
      return m("div",
        {
          style: {
            "transform": `scale(${scale})`,
            "transform-origin": "top"
          }
        },
        m.trust(r.join("\n"))
      );
    }
  };
};

