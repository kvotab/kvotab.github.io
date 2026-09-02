/* ==========================================================================
   UI ACTIONS  (site-wide)

   Controls declare what they do, and on which event, instead of carrying a
   snippet of JavaScript:

       <button data-on-click="openUrlDialog">
       <input  data-on-change="toggleShowTotal" type="checkbox">
       <input  data-on-keyup="keyup_lat_dd" data-on-blur="blur_lat">

   Why this exists rather than inline on* attributes:

     - the entry points into a page are discoverable: grep for data-on-
       instead of reading the markup for on*=;
     - every handler runs inside one error boundary, so a throwing control
       reports itself instead of leaving the UI half-updated;
     - the markup no longer hard-codes a global function name per control.

   The event is part of the attribute name rather than a separate
   data-action-on, because several controls need two bindings — the coordinate
   inputs recalculate on keyup and reformat on blur — and one attribute per
   element cannot express that.

   Each page registers its own handlers with registerActions(). This file owns
   only the dispatch mechanism.
   ========================================================================== */

/* name -> handler(event, element) */
const KVOT_ACTIONS = Object.create(null);

/*
  Most events bubble, so one delegated listener per type on `document` catches
  them — which also means controls rendered later (the toolbar the site header
  injects, tree rows, table rows) need no separate wiring.

  `blur` and `focus` do not bubble. Rewriting them as focusout/focusin would
  hand the handler a different event type, so instead they are bound straight
  to the elements that declare them. Nothing above the dispatcher can tell the
  difference; only the plumbing differs.
*/
const KVOT_DELEGATED_EVENTS = Object.freeze(['click', 'change', 'input', 'keyup', 'keydown']);
const KVOT_DIRECT_EVENTS = Object.freeze(['blur', 'focus']);

/**
 * Register handlers by name. Call once per page, or several times to add more.
 *
 * @param {Object<string, function(Event, Element): *>} handlers
 * @returns {void}
 */
function registerActions(handlers) {
  for (const [name, handler] of Object.entries(handlers || {})) {
    if (typeof handler !== 'function') {
      reportFailure('registerActions', new Error(`Handler for "${name}" is not a function`));
      continue;
    }
    if (name in KVOT_ACTIONS) {
      reportFailure('registerActions', new Error(`Action "${name}" is already registered`));
      continue;
    }
    KVOT_ACTIONS[name] = handler;
  }
}

/**
 * Run one declared action, reporting rather than swallowing any failure.
 *
 * @param {string} name - Handler name from the data-on-* attribute
 * @param {Event} event - The event that triggered it
 * @param {Element} element - The element that declared the action
 * @returns {void}
 */
function runAction(name, event, element) {
  const handler = KVOT_ACTIONS[name];
  if (!handler) {
    reportFailure('runAction', new Error(`No handler registered for "${name}"`));
    return;
  }
  try {
    const result = handler(event, element);
    /* Several handlers are async; an unhandled rejection is still a failure. */
    if (result && typeof result.catch === 'function') {
      result.catch(error => reportFailure(`action:${name}`, error, {
        userMessage: `“${describeControl(element)}” did not complete.`
      }));
    }
  } catch (error) {
    reportFailure(`action:${name}`, error, {
      userMessage: `“${describeControl(element)}” failed.`
    });
  }
}

/**
 * A human-readable name for a control, for use in failure messages.
 *
 * @param {Element} element
 * @returns {string}
 */
function describeControl(element) {
  if (!element) return 'This control';
  const label = element.getAttribute('aria-label')
    || element.getAttribute('title')
    || (element.textContent || '').trim()
    || (element.closest('label') ? (element.closest('label').textContent || '').trim() : '');
  const cleaned = label.replace(/\s+/g, ' ').trim();
  return cleaned ? cleaned.slice(0, 60) : (element.id || element.tagName.toLowerCase());
}

/** Elements already bound for a given non-bubbling event, so none binds twice. */
const _directlyBound = new WeakMap();

/**
 * Bind the non-bubbling actions present in the document. Safe to call again
 * after markup has been added; already-bound elements are skipped.
 *
 * @returns {void}
 */
function bindDirectActions() {
  for (const type of KVOT_DIRECT_EVENTS) {
    const attribute = 'data-on-' + type;
    for (const element of document.querySelectorAll('[' + attribute + ']')) {
      let bound = _directlyBound.get(element);
      if (!bound) {
        bound = new Set();
        _directlyBound.set(element, bound);
      }
      if (bound.has(type)) continue;
      bound.add(type);
      const name = element.getAttribute(attribute);
      element.addEventListener(type, event => runAction(name, event, element));
    }
  }
}

/**
 * Install the delegated listeners and bind the non-bubbling ones.
 * @returns {void}
 */
function installActions() {
  for (const type of KVOT_DELEGATED_EVENTS) {
    const selector = '[data-on-' + type + ']';
    const attribute = 'data-on-' + type;
    document.addEventListener(type, event => {
      const element = event.target && event.target.closest
        ? event.target.closest(selector)
        : null;
      if (!element) return;
      runAction(element.getAttribute(attribute), event, element);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindDirectActions, { once: true });
  } else {
    bindDirectActions();
  }
}

installActions();
