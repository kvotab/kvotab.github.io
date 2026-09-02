/* ==========================================================================
   0. ERROR CONTRACT

   Loaded before every other rb-* module, because they all report through it.
   Keeping it first means a failure during another module's own load still has
   somewhere to go.
   ========================================================================== */

/* ==========================================================================
   ERROR REPORTING

   Before this, failures took one of three shapes: a bare `catch (e) {}` that
   erased the problem, a `console.warn` with no indication of what the user
   should do, or an `alert()`. None of them told the user anything useful and
   the first actively hid bugs.

   Everything now goes through two functions that make the intent explicit at
   the call site:

     reportFailure(context, error, { userMessage })
         Something went wrong that the developer needs to see. Logged with the
         operation name. Pass `userMessage` when the user is waiting on the
         result and must be told it failed.

     ignoreFailure(context, error)
         Something optional failed and the program is correct to continue —
         a cosmetic DOM update, an unreadable attribute on a node we are only
         probing. Recorded at debug level so it is visible when looking for it
         but silent otherwise.

   The distinction is the point: `ignoreFailure` says "considered and ignored",
   an empty catch block says nothing at all.
   ========================================================================== */

/**
 * Report a failure that should not have happened.
 *
 * @param {string} context - What was being attempted, e.g. 'loadFromUrl'
 * @param {Error|*} error - The thrown value
 * @param {Object} [options]
 * @param {string} [options.userMessage] - Shown to the user when the failure
 *   blocks something they asked for. Omit for background failures.
 * @returns {void}
 */
function reportFailure(context, error, options = {}) {
  const detail = (error && error.message) ? error.message : String(error);
  console.error(`[${context}] ${detail}`, error);
  if (options.userMessage) {
    showFailureBanner(`${options.userMessage} (${detail})`);
  }
}

/**
 * Record a failure that is safe to continue past.
 *
 * @param {string} context - What was being attempted
 * @param {Error|*} [error] - The thrown value, when there is one
 * @returns {void}
 */
function ignoreFailure(context, error) {
  if (error === undefined) {
    console.debug(`[${context}] ignored`);
    return;
  }
  console.debug(`[${context}] ignored: ${(error && error.message) || error}`);
}

/*
  The banner is created on first use rather than sitting in rb.html, so a
  session that never fails carries no extra markup.
*/
let _failureBannerEl = null;
let _failureBannerTimer = null;

/**
 * Show a dismissable failure message at the top of the viewport.
 *
 * @param {string} message
 * @returns {void}
 */
function showFailureBanner(message) {
  try {
    if (!_failureBannerEl) {
      _failureBannerEl = document.createElement('div');
      _failureBannerEl.id = 'failureBanner';
      _failureBannerEl.className = 'failure-banner';
      _failureBannerEl.setAttribute('role', 'alert');
      const text = document.createElement('span');
      text.className = 'failure-banner-text';
      const close = document.createElement('button');
      close.type = 'button';
      close.className = 'failure-banner-close';
      close.setAttribute('aria-label', 'Dismiss');
      close.textContent = '×';
      close.addEventListener('click', hideFailureBanner);
      _failureBannerEl.appendChild(text);
      _failureBannerEl.appendChild(close);
      document.body.appendChild(_failureBannerEl);
    }
    _failureBannerEl.querySelector('.failure-banner-text').textContent = message;
    _failureBannerEl.classList.add('show');
    if (_failureBannerTimer) clearTimeout(_failureBannerTimer);
    _failureBannerTimer = setTimeout(hideFailureBanner, 12000);
  } catch (e) {
    /* The reporter itself must never throw; the console message above stands. */
    console.error('[showFailureBanner] could not display message', e);
  }
}

/**
 * Hide the failure banner if it is showing.
 * @returns {void}
 */
function hideFailureBanner() {
  if (_failureBannerTimer) { clearTimeout(_failureBannerTimer); _failureBannerTimer = null; }
  if (_failureBannerEl) _failureBannerEl.classList.remove('show');
}
