/*

  Logo.ts

  Animated Explo / Netskrafl logo & legend component

  Copyright (C) 2021 Miðeind ehf.
  Original author: Vilhjálmur Þorsteinsson

  The GNU Affero General Public License, version 3, applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

*/

export { ExploLogo, AnimatedExploLogo, NetskraflLegend };

import { m, ComponentFunc } from "mithril";

// SVG code for Explo logo
const headerLogo = `<svg width="134" height="134" viewBox="-32 -8 134 134" fill="none" xmlns="http://www.w3.org/2000/svg">`;
const circle = `<circle class="shadow" cx="35" cy="59" r="63" fill="#ffffff"/>`;
const pieces: string[][] = [
  // Orange box on top
  [
  `<path d="M65.2672 12.542L54.3998 18.813L43.5323 25.146L32.6649 18.813L21.7354 12.542L43.5323 0L65.2672 12.542Z" fill="#FDC12C"/>`,
  `<path d="M43.5323 25.1457V37.6877L21.7354 25.1457V12.5416L43.5323 25.1457Z" fill="#E69419"/>`,
  `<path d="M65.2661 12.5416V25.1457L43.5312 37.6877V25.1457L65.2661 12.5416Z" fill="#F8DA95"/>`
  ],
  // Red box
  [
  `<path d="M43.5318 37.6847L32.6644 43.9557L21.7349 50.2267L10.8674 43.9557L0 37.6847L21.7349 25.1427L43.5318 37.6847Z" fill="#AA3731"/>`,
  `<path d="M21.7349 50.23V62.7719L0 50.23V37.688L21.7349 50.23Z" fill="#721D19"/>`
  ],
  // Green box
  [
  `<path d="M65.2672 50.23L54.3998 56.501L43.5323 62.7719L32.6028 56.501L21.7354 50.23L43.5323 37.688L65.2672 50.23Z" fill="#669256"/>`,
  `<path d="M43.5323 62.7716V75.3756L21.7354 62.7716V50.2296L43.5323 62.7716Z" fill="#496A38"/>`,
  `<path d="M65.2661 50.2296V62.7716L43.5312 75.3756V62.7716L65.2661 50.2296Z" fill="#B7C7AD"/>`
  ],
  // Light blue box
  [
  `<path d="M43.5318 75.3754L32.6644 81.6464L21.7349 87.9174L10.8674 81.6464L0 75.3754L21.7349 62.7714L43.5318 75.3754Z" fill="#83C8CE"/>`,
  `<path d="M21.7349 87.918V100.46L0 87.918V75.376L21.7349 87.918Z" fill="#5699A5"/>`
  ],
  // Pink box at the bottom
  [
  `<path d="M65.2672 87.918L54.3998 94.1889L43.5323 100.46L32.6649 94.1889L21.7354 87.918L43.5323 75.376L65.2672 87.918Z" fill="#E39FA5"/>`,
  `<path d="M43.5323 100.46V113.002L21.7354 100.46V87.9177L43.5323 100.46Z" fill="#B6676D"/>`,
  `<path d="M65.2661 87.9177V100.46L43.5312 113.002V100.46L65.2661 87.9177Z" fill="#EACFD1"/>`
  ]
];
// SVG code for the letters 'netskrafl'
const headerLetters = `<svg viewBox="0 0 992.73 323.47" fill="none" xmlns="http://www.w3.org/2000/svg">`;
const letters: string[][] = [
  [`<path fill="#514c4c"`,
  `    d="M1728.66,1133.94a1.85,1.85,0,0,1-2-2v-54.59c0-10.41-4.91-17.28-14.73-17.28-9.43,0-14.93,6.87-14.93,17.28V1132a1.85,1.85,0,0,1-2,2h-23.56a1.86,1.86,0,0,1-2-2v-91.12a1.86,1.86,0,0,1,2-2h23.56a1.85,1.85,0,0,1,2,2v6.68h.2c4.32-5.89,12.37-10.8,24.55-10.8,21,0,32.4,14.53,32.4,35.34V1132a1.86,1.86,0,0,1-2,2Z"`,
  `    transform="translate(-1401.69 -918.27)"/>`],
  [`<path fill="#514c4c"`,
  `    d="M1769.19,1109a68.34,68.34,0,0,1-3.34-22.58c0-10,1.18-16.89,3.14-22.78,5.5-17.08,20.62-26.9,40.84-26.9,21,0,35.55,10,41,26.71,2,6.28,3.15,13.15,3.15,29.25a1.92,1.92,0,0,1-2.16,2h-57.54a1,1,0,0,0-1.18,1.18,21.17,21.17,0,0,0,1.18,5.3c2.55,8.24,9.82,12.56,19.64,12.56a30.5,30.5,0,0,0,21.79-8.44c1-.78,2-1,2.75,0l13,12.18a1.77,1.77,0,0,1,.2,2.75c-9,9.62-23,15.9-40.45,15.9C1789.61,1136.1,1774.69,1126.09,1769.19,1109Zm56.55-32.59a1,1,0,0,0,1.18-1.18,23.82,23.82,0,0,0-1-7.07c-2.16-6.48-8-10.41-15.91-10.41s-13.75,3.93-15.91,10.41a23.82,23.82,0,0,0-1,7.07,1,1,0,0,0,1.18,1.18Z"`,
  `    transform="translate(-1401.69 -918.27)"/>`],
  [`<path fill="#514c4c"`,
  `    d="M1898.61,1135.12c-22,0-30.24-9.82-30.24-31.62v-43.2a1,1,0,0,0-1.18-1.18h-5.89a1.85,1.85,0,0,1-2-2v-16.3a1.85,1.85,0,0,1,2-2h5.89a1,1,0,0,0,1.18-1.18v-25.53a1.85,1.85,0,0,1,2-2h23.37a1.85,1.85,0,0,1,2,2v25.53a1,1,0,0,0,1.18,1.18H1909a1.86,1.86,0,0,1,2,2v16.3a1.85,1.85,0,0,1-2,2h-12.18a1,1,0,0,0-1.18,1.18v42c0,7.06,2.36,9.42,8.64,9.42H1909a1.86,1.86,0,0,1,2,2v19.45a1.86,1.86,0,0,1-2,2Z"`,
  `    transform="translate(-1401.69 -918.27)"/>`],
  [`<path fill="#514c4c"`,
  `    d="M1919.28,1121.37a1.91,1.91,0,0,1,0-2.75l12.77-14.33a1.89,1.89,0,0,1,2.75,0c8.44,6.48,19.24,10.41,29.06,10.41,10,0,14.73-3.73,14.73-9,0-4.51-2.56-7.26-13.55-8.24l-10.61-1.18c-20-2-31-12-31-29.06,0-18.66,14.33-30.44,39.07-30.44,16.11,0,29.66,5.1,38.49,11.78a2.14,2.14,0,0,1,.2,3l-11,13.55a1.92,1.92,0,0,1-2.75.39,49.74,49.74,0,0,0-25.72-7.66c-8,0-12,3.14-12,7.86,0,4.32,2.36,6.87,13.16,7.85l10.4,1.18c22.39,2.16,31.62,13,31.62,28.86-.2,19.44-15.32,32.6-42.42,32.6C1942.65,1136.1,1928.32,1129.23,1919.28,1121.37Z"`,
  `    transform="translate(-1401.69 -918.27)"/>`],
  [`<path fill="#514c4c"`,
  `    d="M2077.79,1133.94c-1.38,0-2.16-.59-2.95-2l-21.21-38.29-9.81,12.17V1132a1.86,1.86,0,0,1-2,2h-23.56a1.85,1.85,0,0,1-2-2v-129.6a1.86,1.86,0,0,1,2-2h23.56a1.86,1.86,0,0,1,2,2v72.06l27.29-33.58a4.5,4.5,0,0,1,3.73-2H2100a1.1,1.1,0,0,1,.78,2l-29.06,33.58,33.19,57.54a1.2,1.2,0,0,1-1,2Z"`,
  `    transform="translate(-1401.69 -918.27)"/>`],
  [`<path fill="#514c4c"`,
  `    d="M2115.68,1133.94a1.85,1.85,0,0,1-2-2v-91.12a1.85,1.85,0,0,1,2-2h23.57a1.85,1.85,0,0,1,2,2v8.05h.2c4.51-7.65,13.15-12.17,24.74-12.17,6.28,0,12.57,2.16,16.69,5.69a1.93,1.93,0,0,1,.59,2.75l-11,20c-.78,1-1.57,1-2.75.4-4.51-2.95-9-4.52-13.74-4.32-10.21.39-14.73,7.85-14.73,20.61V1132a1.85,1.85,0,0,1-2,2Z"`,
  `    transform="translate(-1401.69 -918.27)"/>`],
  [`<path fill="#514c4c"`,
  `    d="M2246.58,1133.94a1.86,1.86,0,0,1-2-2v-6.29h-.19c-4.91,6.29-13.16,10.41-26.12,10.41-16.89,0-31.61-8.84-31.61-29.06,0-21,15.9-30.63,39.47-30.63H2243a1,1,0,0,0,1.18-1.18v-3.54c0-8.83-4.32-13-19.44-13-9.62,0-16.69,2.75-21.21,6.09a1.56,1.56,0,0,1-2.55-.39l-8.84-15.52a1.89,1.89,0,0,1,.59-2.74c8.06-5.7,19.64-9.43,35.35-9.43,31,0,42.22,10.6,42.22,34.36V1132a1.85,1.85,0,0,1-2,2Zm-2.36-31.61v-6.48a1,1,0,0,0-1.18-1.18h-13.35c-11.58,0-16.89,3.34-16.89,10.8,0,6.67,4.72,10,13.75,10C2238.33,1115.48,2244.22,1111.16,2244.22,1102.33Z"`,
  `    transform="translate(-1401.69 -918.27)"/>`],
  [`<path fill="#514c4c"`,
  `    d="M2291.92,1133.94a1.86,1.86,0,0,1-2-2V1060.3a1,1,0,0,0-1.17-1.18h-5.89a1.86,1.86,0,0,1-2-2v-16.3a1.86,1.86,0,0,1,2-2h5.89a1,1,0,0,0,1.17-1.18v-4.51c0-23.18,10.8-32.8,33.39-32.8h10.8a1.86,1.86,0,0,1,2,2v18.45a1.86,1.86,0,0,1-2,2h-6.09c-8.64,0-10.8,2.16-10.8,10.21v4.71a1,1,0,0,0,1.18,1.18h15.51a1.85,1.85,0,0,1,2,2v16.3a1.85,1.85,0,0,1-2,2h-15.51a1,1,0,0,0-1.18,1.18V1132a1.85,1.85,0,0,1-2,2Zm90.13,1.18c-21,0-29.46-9.23-29.46-30.24v-102.5a1.86,1.86,0,0,1,2-2h23.56a1.86,1.86,0,0,1,2,2v100.34c0,6.48,2.55,9,8.24,9h4.13a1.85,1.85,0,0,1,2,2v19.45a1.85,1.85,0,0,1-2,2Z"`,
  `    transform="translate(-1401.69 -918.27)"/>`]
];

const footer = `</svg>`;

const WIDTH = 134;
const NUM_STEPS = pieces.length;

const AnimatedExploLogo: ComponentFunc<{
  width: number; withCircle: boolean; msStepTime: number; once?: boolean; className?: string
}> = (initialVnode) => {

  // Animation step time in milliseconds
  const msStepTime = initialVnode.attrs.msStepTime || 0;
  const width = initialVnode.attrs.width;
  const scale = width / WIDTH;
  const withCircle = initialVnode.attrs.withCircle || false;
  const once = initialVnode.attrs.once ? true : false;
  const className = initialVnode.attrs.className;

  function doStep() {
    // Check whether we're still in the delay period

    // Check if we need to reverse direction
    if (this.delta < 0 && this.step == 0) {
      this.delta = 1;
    } else if (this.delta > 0 && this.step == NUM_STEPS) {
      // All steps completed; should we reverse direction
      // or stop the animation (if once == true)?
      if (once) {
        // We're done
        this.delta = 0;
        clearInterval(this.ival);
        this.ival = 0;
      }
      else
        // Reverse direction
        this.delta = -1;
    }
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
      let r: string[] = [ headerLogo ];
      if (withCircle)
        // Include white background circle, with drop shadow
        r.push(circle);
      for (let i = 0; i < this.step; i++)
        for (let piece of pieces[i])
            r.push(piece);
      r.push(footer);
      let attribs: any = {
        style: {
          "transform": `scale(${scale})`,
          "transform-origin": "left top"
        }
      };
      if (className !== undefined && className !== null)
        attribs.class = className;
      return m("div", attribs, m.trust(r.join("\n")));
    }
  };
};

const LETTER_WIDTH = 992.73;
const NUM_LETTER_STEPS = letters.length;

const NetskraflLegend: ComponentFunc<{
  width: number; msStepTime: number; className?: string
}> = (initialVnode) => {

  // Animation step time in milliseconds
  const msStepTime = initialVnode.attrs.msStepTime || 0;
  const width = initialVnode.attrs.width;
  const scale = width / LETTER_WIDTH;
  const className = initialVnode.attrs.className;

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
    step: msStepTime ? 0 : NUM_LETTER_STEPS, // Current step number
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
      let r: string[] = [ headerLetters ];
      for (let i = 0; i < this.step; i++)
        for (let letter of letters[i])
          r.push(letter);
      r.push(footer);
      let attribs: any = {
        style: {
          "transform": `scale(${scale})`,
          "transform-origin": "left top"
        }
      };
      if (className)
        attribs.class = className;
      return m("div", attribs, m.trust(r.join("\n")));
    }
  };
};

const ExploLogo: ComponentFunc<{ scale: number; legend: boolean; }> = (initialVnode) => {

  // The Explo logo, with or without the legend ('explo' or 'Netskrafl')

  const scale = initialVnode.attrs.scale || 1.0;
  const legend = initialVnode.attrs.legend;

  return {
    view: (vnode) => {
      return m("img",
        legend ?
          {
            alt: 'Netskrafl',
            width: 89 * scale, height: 40 * scale,
            src: '/static/explo-logo.svg'
          }
          :
          {
            alt: 'Netskrafl',
            width: 23 * scale, height: 40 * scale,
            src: '/static/explo-logo-only.svg'
          }
      );
    }
  };
};
