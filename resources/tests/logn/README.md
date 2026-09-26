# Tests for logn.html

`test-ui.py` is the page in headless Chrome: its (i) panels, and that the page
still does what it did. Serve the repository and start Chrome first, on ports
8813 and 9313 unless `LOGN_HTTP_PORT` and `LOGN_CDP_PORT` say otherwise
(check them with `lsof -nP -iTCP:<port> -sTCP:LISTEN`: other sessions use
ports too, and a server that fails to start looks like one that works):

    python3 -m http.server 8813 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --remote-debugging-port=9313 --no-first-run \
      --user-data-dir=/tmp/logntest --disable-gpu about:blank

    python3 resources/tests/logn/test-ui.py

It exits 0 when every check passes (68 of them). With `LOGN_SHOTS=<folder>` it
also saves a screenshot with a panel open in each of the four layouts it
checks: light and dark, 1500 × 950 and 420 × 900.

## What it checks

**The (i)s.** `KvotInfo.audit()` (resources/js/kvot-info.js) finds 32 topics,
no slot without a topic and no "Read more" whose target is missing. At load
the (i)s on screen are those of the Distributions bar, the metric pills, the
two metric panels and the four open or closed section headings; opening the
settings shows one per setting. One opens its panel with its title and kicker,
between the site header and footer and against the right-hand edge; the ×,
Escape (sent as a CDP key event) and the same (i) close it, and the × gives the
focus back to the (i). A topic that marks the current choice follows the
setting while it is open. "Read more" opens the equations and brings the
heading into view below the header. The metrics topic lists what cannot be
chosen and why, the Distributions topic counts the distributions and names
the hidden ones, and the (i) in a panel's heading follows the metric in the
panel. The fit method's (i) is in a cloned template, so it is checked that it
works there.

**Where they stand.** The (i)s of the two bars, the right-hand panel and the
section headings share one right-hand edge, in all four layouts; a setting's
(i) ends its label line, over the right-hand end of its field; the settings'
(i)s stand level row by row; and there is no horizontal scroll.

**No tooltips.** The only `title` left in the page's content is on the dot of
a distribution tab, a button with no text (the × of a tab keeps one too, once
there are two). The metric fields keep their names as `aria-label`, and each
setting is named by its `<label>`. A greyed-out metric says why it cannot be
chosen when it is clicked, which its tooltip used to say on hover only.

**The page as it was.** μ = 0 and σ = 1 give a mean of 1.6487; the chart
draws the five traces it always drew; swapping σ for gsd offers e^σ and leaves
the result where it was; the data set 2 3 4 … 48 is fitted by maximum
likelihood to μ = 2.225879 and σ = 1.021352 and by the method of moments to a
mean of 136/9; a second distribution brings the Comparison. No script error
at any point.

The multi-distribution behaviour is tested in more depth by
`resources/tests/site/test-chrome-distributions.py` (ports 8765 and 9222
written into it; copy it and change them to run it beside another session),
and `resources/tests/site/characterise.py` fingerprints the page with the
rest of the site.
