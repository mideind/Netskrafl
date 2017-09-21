/*

   Ui.js

   User interface utility functions

   Copyright (C) 2015-2017 Miðeind ehf.
   Author: Vilhjalmur Thorsteinsson

   The GNU General Public License, version 3, applies to this software.
   For further information, see https://github.com/vthorsteinsson/Netskrafl

*/

function buttonOver(elem) {
   /* Show a hover effect on a button */
   if (!$(elem).hasClass("disabled"))
      $(elem).toggleClass("over", true);
}

function buttonOut(elem) {
   /* Hide a hover effect on a button */
   $(elem).toggleClass("over", false);
}

