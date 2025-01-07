/*

  Util.ts

	Utility functions for the Explo user interface

  Copyright © 2025 Miðeind ehf.
  Author: Vilhjálmur Þorsteinsson

  The Creative Commons Attribution-NonCommercial 4.0
  International Public License (CC-BY-NC 4.0) applies to this software.
  For further information, see https://github.com/mideind/Netskrafl

  The following code is based on
  https://developer.mozilla.org/en-US/docs/Web/API/Pointer_events/Pinch_zoom_gestures

*/

export { addPinchZoom, registerSalesCloud };

type ZoomFunc = () => void;

// Global vars to cache event state
var evCache: PointerEvent[] = [];
var origDistance = -1;
const PINCH_THRESHOLD = 10; // Minimum pinch movement
var hasZoomed = false;

function addPinchZoom(attrs: any, funcZoomIn: ZoomFunc, funcZoomOut: ZoomFunc) {
  // Install event handlers for the pointer target
  attrs.onpointerdown = pointerdown_handler;
  attrs.onpointermove = pointermove_handler.bind(null, funcZoomIn, funcZoomOut);
  // Use same handler for pointer{up,cancel,out,leave} events since
  // the semantics for these events - in this app - are the same.
  attrs.onpointerup = pointerup_handler;
  attrs.onpointercancel = pointerup_handler;
  attrs.onpointerout = pointerup_handler;
  attrs.onpointerleave = pointerup_handler;
}

function pointerdown_handler(ev: PointerEvent) {
  // The pointerdown event signals the start of a touch interaction.
  // This event is cached to support 2-finger gestures
  evCache.push(ev);
}

function pointermove_handler(funcZoomIn: ZoomFunc, funcZoomOut: ZoomFunc, ev: PointerEvent) {
  // This function implements a 2-pointer horizontal pinch/zoom gesture. 
  //
  // If the distance between the two pointers has increased (zoom in), 
  // the target element's background is changed to "pink" and if the 
  // distance is decreasing (zoom out), the color is changed to "lightblue".
  //
  // Find this event in the cache and update its record with this event
  for (let i = 0; i < evCache.length; i++) {
    if (ev.pointerId == evCache[i].pointerId) {
      evCache[i] = ev;
      break;
    }
  }
 
  // If two pointers are down, check for pinch gestures
  if (evCache.length == 2) {
    // Calculate the distance between the two pointers
    const curDistance = Math.sqrt(
      Math.pow(evCache[0].clientX - evCache[1].clientX, 2) +
      Math.pow(evCache[0].clientY - evCache[1].clientY, 2)
    );
 
    if (origDistance > 0) {
      if (curDistance - origDistance >= PINCH_THRESHOLD) {
        // The distance between the two pointers has increased
        if (!hasZoomed)
          funcZoomIn();
        hasZoomed = true;
      }
      else
      if (origDistance - curDistance >= PINCH_THRESHOLD) {
        // The distance between the two pointers has decreased
        if (!hasZoomed)
          funcZoomOut();
        hasZoomed = true;
      }
    }
    else
    if (origDistance < 0) {
      // Note the original difference between two pointers
      origDistance = curDistance;
      hasZoomed = false;
    }
  }
}

function pointerup_handler(ev: PointerEvent) {
  // Remove this pointer from the cache and reset the target's
  // background and border
  remove_event(ev);
  // If the number of pointers down is less than two then reset diff tracker
  if (evCache.length < 2) {
    origDistance = -1;
  }
}

function remove_event(ev: PointerEvent) {
  // Remove this event from the target's cache
  for (let i = 0; i < evCache.length; i++) {
    if (evCache[i].pointerId == ev.pointerId) {
      evCache.splice(i, 1);
      break;
    }
  }
}

// SalesCloud stuff
function doRegisterSalesCloud(i,s,o,g,r,a?:any,m?:any) {
  i.SalesCloudObject=r;
  i[r]=i[r]||function(){(i[r].q=i[r].q||[]).push(arguments);};
  i[r].l=1*(new Date() as any);
  a=s.createElement(o);
  m=s.getElementsByTagName(o)[0];
  a.src=g;
  m.parentNode.insertBefore(a,m);
}

function registerSalesCloud() {
  doRegisterSalesCloud(
     window,
     document,
     'script',
     'https://cdn.salescloud.is/js/salescloud.min.js',
     'salescloud'
  );
}
