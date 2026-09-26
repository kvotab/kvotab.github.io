/* ==========================================================================
   logn.html: WHAT EACH SETTING AND SECTION IS  (for resources/js/kvot-info.js)

   The text of the panel an (i) opens: what a control is, what its choices
   do, when to change it and where it goes wrong. It replaces the hover
   tooltips the page had, so what they said is here too.

   The page hands in what the topics read (the selection, the distributions,
   the formatter) and the settings are read from their fields, so a topic is
   worked out when its panel is drawn and a choice list marks the choice in
   force. The numbers are the page's own: the defaults are those of the
   markup, the limits those it checks, the formulas those it computes with.
   ========================================================================== */
(function (root) {
  'use strict';

  const SET = 'Display and chart settings';
  const EQ = 'Equations & formulas';

  /** A list in prose: `a, b and c`. */
  const prose = (items) => (items.length > 1
    ? `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}` : items[0] || '');

  const field = (id) => document.getElementById(id);
  const onOff = (id) => (field(id) && field(id).checked ? 'on' : 'off');
  const typed = (id) => {
    const v = field(id) ? String(field(id).value).trim() : '';
    return v === '' ? 'empty' : v;
  };

  /* The metrics that each fix σ on their own. */
  const SPREAD = ['sigma', 'GSD', 'CV', 'error'];

  /**
   * The topics, keyed as the slots in logn.html are.
   *
   * @param {Object} page
   * @param {number} page.limit  most distributions the page holds
   * @param {function(): Array<{name: string, visible: boolean, active: boolean, result: ?Object}>} page.distributions
   * @param {function(): string[]} page.selection  the metrics chosen for the selected distribution
   * @param {function(): Array<?string>} page.slots  the metric in each panel
   * @param {function(): string[]} page.ids  every metric, in the order of the pills
   * @param {function(string): string} page.label  a metric's name as its pill shows it
   * @param {function(string, string): boolean} page.pairAllowed
   * @param {function(): string} page.fitMethod  'MLE' or 'MOM', for the selected distribution
   * @param {function(): ?Object} page.result  the selected distribution's statistics
   * @param {function(number, number): string} page.fmt  a number as the results write it
   * @returns {Object<string, Object|function(): Object>}
   */
  function lognInfoTopics(page) {
    const more = (id) => ({ label: EQ, id });

    /* Why metric b cannot go with metric a, which is chosen. */
    function pairReason(a, b) {
      const pair = [a, b];
      if (pair.includes('data')) return 'a data set is fitted to a distribution of its own';
      if (pair.includes('minmax')) return 'min/max fixes the distribution on its own';
      if (pair.includes('mu') && pair.includes('GM')) return 'gm = e^μ, the same number as μ';
      if (SPREAD.includes(a) && SPREAD.includes(b)) return `it fixes σ, as ${page.label(a)} does`;
      if (pair.includes('SD')) return `the page has no formula for sd with ${page.label(a === 'SD' ? b : a)}`;
      return `not offered with ${page.label(a)}`;
    }

    return {
      /* ---- the distributions and the metrics ------------------------------ */
      'set:dists': () => {
        const all = page.distributions();
        const active = all.find((d) => d.active);
        const hidden = all.filter((d) => !d.visible).map((d) => d.name);
        return {
          kicker: 'Input', title: 'Distributions',
          lead: `The page holds up to ${page.limit} lognormal distributions, lettered A to H, each in a colour of its own. The chart draws them together and the Comparison lists them side by side; the panels and Computed results are those of the selected one.`,
          facts: [
            ['On the page', `${all.length} of ${page.limit}`],
            ['Selected', active ? active.name : '—'],
            ['Hidden in the chart', hidden.length ? prose(hidden) : 'none'],
          ],
          sections: [{
            heading: 'On each tab',
            list: [
              '**The name** selects that distribution. The selected one’s name is a text field: type to rename it, up to 24 characters. Left empty, it goes by its letter.',
              '**The coloured dot** hides the distribution in the chart, or shows it again. It stays in the Comparison, and one distribution always stays drawn.',
              '**×** removes it. It is there while the page holds two or more.',
              'A red outline marks a distribution whose inputs contradict each other. The Comparison says why, and so does Computed results when it is selected.',
            ],
          }, {
            heading: '+ add',
            text: `A new distribution starts as a copy of the selected one, with the same metrics and values, so its curve starts on top of the one being worked on rather than at μ = 0, σ = 1. Greyed out at ${page.limit}.`,
          }, {
            text: 'Letters and colours go to the first free one, so removing B of A, B and C leaves C as it was. Nothing is kept: a reload starts again from one distribution with μ = 0 and σ = 1.',
          }],
        };
      },

      'set:metrics': () => {
        const sel = page.selection();
        const blocked = [];
        if (sel.length < 2) {
          for (const id of page.ids()) {
            if (sel.includes(id)) continue;
            const clash = sel.find((s) => !page.pairAllowed(s, id));
            if (clash) blocked.push(`**${page.label(id)}**: ${pairReason(clash, id)}`);
          }
        }
        return {
          kicker: 'Input', title: 'Metrics',
          lead: 'A lognormal distribution has two parameters, so two numbers fix it. Choose the two you have for the selected distribution and type them into the panels below; everything else is worked out from them.',
          facts: [['Chosen', sel.length ? prose(sel.map(page.label)) : 'none'], ['At most', '2']],
          sections: [{
            heading: 'How the choice works',
            list: [
              'The first metric chosen fills the left panel, the second the right one. Click a chosen metric to deselect it.',
              '**percentile** on its own takes both panels: two points, and the lognormal through them.',
              '**min/max** and **data** each fix a distribution on their own and take no second metric.',
              'μ, mean, gm, mode, σ, sd, gsd, CV and error factor start at the value the distribution already has, so a swap moves nothing until the number is changed; left out again, they are forgotten. **percentile**, **min/max** and **data** keep what was typed in them.',
              'A metric that cannot be chosen now is greyed out; clicking it says why, under the metrics.',
            ],
          }, {
            heading: 'Pairs that are not offered',
            list: [
              '**μ** with **gm**: gm = e^μ, the same number twice.',
              'Any two of **σ**, **gsd**, **CV** and **error factor**: each of them fixes σ on its own.',
              '**sd** with anything but **μ**, **gm** and **mean**: the page has no formula for the other pairs.',
              '**min/max** and **data** with anything.',
            ],
          }, {
            heading: 'Not available now',
            list: sel.length >= 2 ? ['Two metrics are chosen: deselect one to choose another.']
              : blocked.length ? blocked : ['Every metric can be chosen.'],
          }],
        };
      },

      /* ---- one metric panel each ------------------------------------------ */
      'metric:mu': {
        kicker: 'Metric', title: 'μ, the log-mean',
        lead: 'The mean of ln x, the natural logarithm of the variable. e^μ is the median and the geometric mean.',
        facts: [['Range', 'any number'], ['New page', '0, a median of 1']],
        sections: [{
          text: 'μ is in the logarithm of the unit of x: the same distribution in g instead of mg has a μ smaller by ln 1000 = 6.91. Adding Δ to μ multiplies the median, the mean, the mode, the sd and every percentile by e^Δ, and leaves σ, gsd, CV and the error factor as they were.',
        }, {
          heading: 'With a second metric',
          list: [
            'Any of **mean**, **mode**, **percentile**, **σ**, **sd**, **gsd**, **CV** and **error factor**; not **gm**, which is e^μ.',
            'The mean must be above e^μ, and the mode below it.',
            'The value of a percentile below 50 must be below e^μ, and above 50 above it. P50 is the median itself and fixes no spread.',
          ],
        }],
        more: more('eq-logspace'),
      },

      'metric:mean': {
        kicker: 'Metric', title: 'Mean',
        lead: 'The arithmetic mean, e^(μ + σ²/2). It is above the median by the factor e^(σ²/2): 1.13 at σ = 0.5, 1.65 at σ = 1, 7.39 at σ = 2.',
        facts: [['Range', 'above 0'], ['Unit', 'that of x']],
        sections: [{
          heading: 'With a second metric',
          list: [
            '**sd**: σ² = ln(1 + sd²/mean²) and μ = ln mean − σ²/2 — the pair a sample’s mean and standard deviation give.',
            '**μ** or **gm**: σ = √(2(ln mean − μ)). The mean must be above the median, e^μ.',
            '**mode**: σ² = ⅔ ln(mean/mode). The mean must be above the mode.',
            '**σ**, **gsd**, **CV** or **error factor**: μ = ln mean − σ²/2.',
            '**percentile**: σ = z + √(z² + 2 ln(mean/x)), with z = Φ⁻¹(p/100). At P50 and below, the value must be below the mean. Above P50, a value above the mean fits two lognormals and the page takes the one with the larger σ; beyond mean · e^(z²/2), 3.87 times the mean for P95, none fits and the results stay empty.',
          ],
        }],
        more: more('eq-central'),
      },

      'metric:GM': {
        kicker: 'Metric', title: 'Geometric mean (gm)',
        lead: 'e^μ, which for a lognormal is also the median: half of the distribution lies below it. Entering gm is entering μ = ln gm.',
        facts: [['Range', 'above 0'], ['Unit', 'that of x']],
        sections: [{
          text: 'It pairs with what μ pairs with, on the same conditions — the mean above gm, the mode below it, a percentile below 50 at a value below gm and one above 50 above it — and not with μ itself.',
        }],
        more: more('eq-central'),
      },

      'metric:mode': {
        kicker: 'Metric', title: 'Mode',
        lead: 'The most probable value, where the density of x peaks: e^(μ − σ²). It lies below the median, by the factor e^(−σ²), and below the mean.',
        facts: [['Range', 'above 0'], ['Unit', 'that of x']],
        sections: [{
          heading: 'With a second metric',
          list: [
            '**μ** or **gm**: σ = √(μ − ln mode). The mode must be below e^μ.',
            '**mean**: σ² = ⅔ ln(mean/mode). The mean must be above the mode.',
            '**σ**, **gsd**, **CV** or **error factor**: μ = ln mode + σ².',
            '**percentile**: σ = (√(z² + 4 ln(x/mode)) − z)/2, with z = Φ⁻¹(p/100). At P50 and above, the value must be above the mode. Below P50, a value under the mode fits two lognormals and the page takes the one with the larger σ; under mode · e^(−z²/4), 0.51 times the mode for P5, none fits and the results stay empty.',
            'Not **sd**: the page has no formula for that pair.',
          ],
        }, {
          text: 'In the ln(x) view the curve peaks at μ, not at the mode: the density of ln x has its peak at its mean.',
        }],
        more: more('eq-central'),
      },

      'metric:percentile': () => {
        const slots = page.slots();
        const chosen = slots.includes('percentile');
        const pair = slots[0] === 'percentile' && slots[1] === 'percentile';
        const other = slots.find((m) => m && m !== 'percentile');
        return {
          kicker: 'Metric', title: 'Percentile',
          lead: 'A point of the distribution: the value x below which p percent of it lies, x = exp(μ + zσ), with z = Φ⁻¹(p/100) the standard normal quantile.',
          facts: [
            ['Percentile', 'above 0 and below 100'],
            ['Value', 'above 0, in the unit of x'],
            ['Now', !chosen ? null : pair ? 'two points' : other ? `one point, with ${page.label(other)}` : null],
          ],
          sections: [{
            heading: 'On its own: two points',
            text: [
              'Chosen alone, percentile takes both panels, and the lognormal through the two points has σ = (ln x₁ − ln x₂)/(z₁ − z₂) and μ = ln x₁ − z₁σ. A new pair starts at P5 = 1 and P95 = 10.',
              'The two percentiles must differ, and so must the values, with the higher value at the higher percentile.',
            ],
          }, {
            heading: 'With another metric: one point',
            text: 'The point and the other metric fix the distribution together. With **σ**, **gsd**, **CV** or **error factor** any point works: μ = ln x − zσ. With μ, gm, the mean or the mode the value has to lie on the right side of it; the (i) of that metric says which.',
          }],
          more: more('eq-percentile'),
        };
      },

      'metric:minmax': {
        kicker: 'Metric', title: 'Min/max interval',
        lead: 'A central interval: min and max hold the probability P between them, with (100 − P)/2 percent of the distribution below min and as much above max.',
        facts: [['New page', 'min 1, max 2, P 97.5 %'], ['Min and max', 'above 0, min below max'], ['Probability', 'above 0 and below 100 %']],
        sections: [{
          text: [
            'The median is the geometric midpoint √(min · max): μ = (ln min + ln max)/2, and σ = ln(max/min)/(2z) with z = Φ⁻¹(½ + P/200).',
            'P is two-tailed: 95 makes min the 2.5th percentile and max the 97.5th. For P5 to P95 enter 90; max/median is then the error factor.',
            'The interval fixes the distribution on its own, so min/max takes the whole row and admits no second metric.',
          ],
        }],
        more: more('eq-percentile'),
      },

      'metric:sigma': {
        kicker: 'Metric', title: 'σ, the log standard deviation',
        lead: 'The standard deviation of ln x. It sets the shape: gsd = e^σ, CV = √(e^(σ²) − 1), error factor = e^(1.645σ). It has no unit, and a change of the unit of x leaves it as it is.',
        facts: [['Range', 'above 0'], ['New page', '1']],
        sections: [{
          text: 'For a sense of scale: at σ = 0.1 the distribution is nearly symmetric, with a CV of 0.10; at σ = 1 the central 90 % spans a factor 5.2 either side of the median; at σ = 2.3 one gsd is a factor of 10.',
        }, {
          heading: 'With a second metric',
          text: '**μ**, **gm**, **mean**, **mode** or **percentile**. Not **gsd**, **CV** or **error factor**, which fix σ as well, and not **sd**, for which the page has no formula with σ.',
        }],
        more: more('eq-spread'),
      },

      'metric:SD': {
        kicker: 'Metric', title: 'Standard deviation (sd)',
        lead: 'The arithmetic standard deviation, mean · √(e^(σ²) − 1), in the unit of x.',
        facts: [['Range', 'above 0'], ['Pairs with', 'μ, gm and mean']],
        sections: [{
          heading: 'With a second metric',
          list: [
            '**mean**: σ² = ln(1 + sd²/mean²) and μ = ln mean − σ²/2 — a sample’s mean and standard deviation.',
            '**μ** or **gm**: σ² = ln((1 + √(1 + 4 sd²/e^(2μ)))/2).',
          ],
        }, {
          text: 'The page has no formula for sd with the mode, a percentile, σ, gsd, CV or the error factor, so those pairs are not offered.',
        }],
        more: more('eq-spread'),
      },

      'metric:GSD': {
        kicker: 'Metric', title: 'Geometric standard deviation (gsd)',
        lead: 'e^σ, a factor with no unit. From median ÷ gsd to median × gsd lies 68.3 % of the distribution, and from median ÷ gsd² to median × gsd², 95.4 %.',
        facts: [['Range', '1 or more'], ['σ', 'ln gsd']],
        sections: [{
          text: [
            'A gsd of 1 is σ = 0: no spread at all, every percentile equal to the median.',
            'It pairs with **μ**, **gm**, **mean**, **mode** and **percentile**; not with **σ**, **CV** or **error factor**, which fix σ as well, and not with **sd**.',
          ],
        }],
        more: more('eq-spread'),
      },

      'metric:CV': {
        kicker: 'Metric', title: 'Coefficient of variation (CV)',
        lead: 'sd ÷ mean = √(e^(σ²) − 1), a fraction with no unit. σ = √(ln(1 + CV²)).',
        facts: [['Range', 'above 0']],
        sections: [{
          text: [
            'Enter a fraction: 0.3 for 30 %. Typed as 30 it is a CV of 3000 % and σ = 2.61.',
            'For a small CV, σ is close to it: a CV of 0.1 gives σ = 0.0998.',
            'It pairs with **μ**, **gm**, **mean**, **mode** and **percentile**.',
          ],
        }],
        more: more('eq-spread'),
      },

      'metric:error': {
        kicker: 'Metric', title: 'Error factor',
        lead: 'e^(1.645σ), the factor that spans the central 90 % either side of the median: P95 ≈ median × EF and P5 ≈ median ÷ EF.',
        facts: [['Range', '1 or more'], ['σ', 'ln(EF)/1.645']],
        sections: [{
          text: [
            'The page uses 1.645 for Φ⁻¹(0.95) = 1.64485, so the error factor and P95/median part in the fourth digit: 5.181 against 5.1803 at σ = 1.',
            'An error factor of 1 is σ = 0, no spread. It pairs with **μ**, **gm**, **mean**, **mode** and **percentile**.',
          ],
        }],
        more: more('eq-spread'),
      },

      'metric:data': {
        kicker: 'Metric', title: 'Data',
        lead: 'Values to fit a lognormal to. Paste or type them separated by spaces, commas, semicolons or new lines.',
        facts: [['At least', '2 positive values'], ['Fit', 'by the fit method below']],
        sections: [{
          heading: 'Read with care',
          list: [
            'A comma separates values, so decimals need a point: `1,5` is read as 1 and 5.',
            'Zeros, negative numbers and anything that is not a number are left out without a message. The n under the results says how many values were used.',
          ],
        }, {
          heading: 'What comes out',
          list: [
            'The fitted distribution in Computed results, and under the percentiles n, the fit method and KS.',
            '**KS** is the largest distance between the fitted CDF and the step CDF of the data, taken at the top of each step: max |i/n − F(x₍ᵢ₎)| over the sorted values. The textbook statistic also looks at the foot of each step and can be up to 1/n larger. μ and σ come from the same values, so KS tables would make the fit look better than it is: read it as a distance.',
            'In the chart, the histogram of the values behind the PDF and their step CDF beside the fitted one, while **Raw data** is on in the settings.',
          ],
        }, {
          text: 'Data fits a distribution of its own and takes no second metric; add a distribution to set it beside one given by metrics. The values are kept when data is deselected and chosen again.',
        }],
      },

      'set:fitMethod': () => {
        const m = page.fitMethod();
        return {
          kicker: 'Data', title: 'Fit method',
          lead: 'How μ and σ are worked out from the values.',
          sections: [{
            choices: [
              ['Maximum likelihood (MLE)', 'μ and σ are the mean and the standard deviation of ln x over the values, the standard deviation divided by n, not n − 1. The fitted median is then the geometric mean of the data. The default.', m === 'MLE'],
              ['Method of moments (MOM)', 'The fit takes the arithmetic mean m and variance s² of the values (divided by n): σ² = ln(1 + s²/m²), μ = ln m − σ²/2. It keeps their mean and variance exactly, which matters when the mean is what is used afterwards; one large value moves it much more than it moves MLE.', m === 'MOM'],
            ],
          }, {
            text: 'Dividing by n makes σ smaller than the n − 1 estimate by the factor √((n − 1)/n), 5 % at n = 10.',
          }],
        };
      },

      /* ---- the sections --------------------------------------------------- */
      'sec:results': () => ({
        kicker: 'Section', title: 'Computed results',
        lead: 'Every statistic of the selected distribution, worked out from its μ and σ and rounded to the significant digits of the settings.'
          + (page.distributions().length > 1 ? ' The chip in the heading names the distribution shown, and its colour runs down the left edge.' : ''),
        sections: [{
          heading: 'What is shown',
          list: [
            '**μ** and **σ**: the mean and the standard deviation of ln x, the two parameters.',
            '**Mean**: the arithmetic mean. **Median**: e^μ, which is also the geometric mean.',
            '**Mode**: the most probable value, e^(μ − σ²).',
            '**Std dev** and **Variance**: arithmetic, in the unit of x and its square.',
            '**GSD**, **CV** and **Error factor**: the spread as a factor or a fraction, with no unit.',
            '**Skewness** and **Excess kurtosis**: the shape. Both grow very fast with σ: 6.2 and 111 at σ = 1.',
            '**Entropy**: the differential entropy ½(1 + ln 2πσ²) + μ, in nats. It depends on the unit of x: in g instead of mg it is smaller by ln 1000.',
            '**Percentiles**: the 5th, 25th, 50th (the median), 75th and 95th.',
          ],
        }, {
          heading: 'When there is nothing to show',
          text: 'Dashes with nothing below them mean the inputs do not fix a distribution yet: a field left empty, or a pair that no lognormal fits. Dashes with a message below them mean the inputs contradict each other, and the message says how.',
        }, {
          text: 'For a distribution fitted to data a line under the percentiles gives n, the fit method and the KS distance; the (i) of the data panel says what KS is.',
        }],
        more: more('equations-details'),
      }),

      'sec:chart': () => {
        const ln = field('lnViewToggle') && field('lnViewToggle').checked;
        const curves = { both: 'PDF and CDF', pdf: 'PDF only', cdf: 'CDF only' }[field('curveMode') ? field('curveMode').value : 'both'];
        return {
          kicker: 'Section', title: 'Distribution chart',
          lead: 'The density (PDF, left axis) and the cumulative distribution (CDF, right axis, 0 to 1) of every distribution that is not hidden, on one x-axis.',
          facts: [['x-axis', ln ? 'ln x, the ln(x) view' : 'x, linear'], ['Curves', curves]],
          sections: [{
            heading: 'What is drawn',
            list: [
              'The PDF, filled: darker between the percentiles of the shaded band (P5 to P95 on a new page), faint in the tails.',
              'A dashed line from the axis up to the PDF at the reference percentile, the median on a new page.',
              'The CDF: in a second colour for one distribution, dotted in each one’s own colour for several.',
              'For a distribution fitted to data, the histogram of the values and their step CDF.',
            ],
          }, {
            heading: 'Several distributions',
            text: 'Each is drawn in its own colour, with the fill fainter so that one shows through another, and a legend names them. Clicking a name in the legend hides that distribution until the chart is next drawn, which any change does; the dot on its tab hides it until it is shown again.',
          }, {
            heading: 'Reading it',
            list: [
              'In the ln(x) view the axis numbers are natural logarithms: 0 is x = 1, 2.30 is x = 10.',
              'The x-axis runs from the chart minimum percentile to the chart maximum percentile, wide enough for every distribution drawn.',
              'Hovering shows values. The toolbar at the top right zooms, pans and saves a PNG, and its button Toggle normal / ln-x view switches the ln(x) view.',
              'The chart is drawn only while this section is open, and again when it is opened.',
            ],
          }],
        };
      },

      'sec:settings': {
        kicker: 'Section', title: 'Display and chart settings',
        lead: 'How the numbers are written and what the chart draws. They apply to every distribution on the page.',
        sections: [{
          list: [
            '**Significant digits**: Computed results and the Comparison. The CSV keeps full precision.',
            '**Optional unit**: the title of the chart’s x-axis. It converts nothing.',
            'The rest: the chart — its scale and curves, the x-range, the shaded band and the reference line.',
          ],
        }, {
          text: 'The chart percentiles are checked together: 0 < minimum < maximum < 100, with the band and the reference line inside that range. A value that breaks this is outlined in red with a line saying why, and until it is put right, changes made here are not applied. A band or line that is switched off is not checked, and its percentiles are greyed out.',
        }, {
          text: 'The settings are not kept: a reload starts from the defaults.',
        }],
      },

      'sec:compare': () => ({
        kicker: 'Section', title: 'Comparison',
        lead: 'The distributions side by side, a column each under its name and colour. The section is there while the page holds two or more.',
        facts: [['Distributions', String(page.distributions().length)]],
        sections: [{
          heading: 'Rows',
          text: [
            'μ, σ, the mean, median and mode, the standard deviation, gsd, CV, the error factor, and P5, P50 and P95; Data n and KS as well once any distribution is fitted to data. The numbers are rounded to the significant digits.',
            'The line under the names says when a distribution is incomplete, why it does not resolve, or that it is hidden in the chart; a hidden one is compared all the same. The selected distribution’s name is underlined in its colour.',
          ],
        }, {
          heading: 'Download as CSV',
          text: 'The same rows at full precision, one column per distribution, as `lognormal-comparison.csv`: comma-separated, UTF-8 with a byte-order mark so that spreadsheet programs read μ and σ. The Data n and KS rows are always there, empty for a distribution without data.',
        }],
      }),

      'sec:equations': {
        kicker: 'Section', title: 'Equations & formulas',
        lead: 'The relations the page computes with, from μ and σ to every other way of giving a lognormal, and back.',
        sections: [{
          heading: 'Notation',
          list: [
            'μ and σ: the mean and the standard deviation of ln x.',
            'μ_g and σ_g: the geometric mean and standard deviation, gm and gsd.',
            'μ_a and σ_a: the arithmetic mean and standard deviation, mean and sd.',
            'Φ⁻¹: the quantile function of the standard normal distribution; Φ⁻¹(0.95) = 1.645.',
          ],
        }, {
          text: 'Each pair of metrics is solved in closed form from these relations; the (i) of a metric gives the formula for each pair it takes, and the (i) of the fit method the fits to data.',
        }],
      },

      /* ---- Display and chart settings ------------------------------------- */
      'set:digits': () => {
        const now = field('precisionSelect') ? field('precisionSelect').value : '5';
        const r = page.result();
        const shown = (d) => (r ? `The mean as ${page.fmt(r.mean, Number(d))}, the variance as ${page.fmt(r.variance, Number(d))}.` : '');
        return {
          kicker: SET, title: 'Significant digits',
          lead: 'How many significant digits the numbers in Computed results and the Comparison are rounded to.',
          facts: [['New page', '5'], ['Written out', 'from 0.0001 to under 1 000 000'], ['Otherwise', 'exponent notation, one digit fewer: `1.235e+6` at 5']],
          sections: [{
            choices: ['3', '5', '7', '10'].map((d) => [d, shown(d), d === now]),
          }, {
            text: 'The CSV of the Comparison is not rounded, and the KS distance always has four decimals.',
          }],
        };
      },

      'set:unit': () => {
        const u = field('unitInput') ? field('unitInput').value.trim() : '';
        const ln = field('lnViewToggle') && field('lnViewToggle').checked;
        return {
          kicker: SET, title: 'Optional unit',
          lead: 'A name for the unit of x, for the title of the chart’s x-axis: `mg/L` gives `mg/L` on a linear axis and `ln(mg/L)` in the ln(x) view.',
          facts: [['Now', u || 'none'], ['Axis title', ln ? (u ? `ln(${u})` : 'ln(x)') : (u || 'x')], ['At most', '20 characters']],
          sections: [{
            text: 'It converts nothing. The inputs, the results and the Comparison are in whatever unit the numbers were typed in, and μ is in its logarithm.',
          }],
        };
      },

      'set:lnview': () => ({
        kicker: SET, title: 'ln(x) view',
        lead: 'Plots ln x along the x-axis instead of x. A lognormal is then a normal bell, symmetric about μ, and distributions of very different size can be read against each other.',
        facts: [['Now', onOff('lnViewToggle')], ['New page', 'on']],
        sections: [{
          list: [
            'The axis numbers are natural logarithms: 0 is x = 1, 2.30 is x = 10, −2.30 is x = 0.1.',
            'The curve is the density of ln x. It peaks at μ, the logarithm of the median, not at the mode, and its height is not that of the density of x.',
            'The CDF and the percentiles are the same either way; only the axis changes.',
            'Unticked, the axis is linear in x, and the long right tail of a wide distribution squeezes its body against the left edge.',
            'The chart’s toolbar has a button, Toggle normal / ln-x view, that switches it too.',
          ],
        }],
      }),

      'set:curves': () => {
        const v = field('curveMode') ? field('curveMode').value : 'both';
        return {
          kicker: SET, title: 'Curves',
          lead: 'Which curves the chart draws.',
          sections: [{
            choices: [
              ['PDF and CDF', 'The density on the left axis and the cumulative distribution on the right, 0 to 1. The default.', v === 'both'],
              ['PDF only', 'The density, with its shaded band, its reference line and the histogram of any data.', v === 'pdf'],
              ['CDF only', 'The cumulative distribution, with the step CDF of any data. The shaded band, the reference line and the histogram belong to the PDF and are not drawn.', v === 'cdf'],
            ],
          }],
        };
      },

      'set:raw': () => ({
        kicker: SET, title: 'Raw data',
        lead: 'For a distribution fitted to data: the histogram of the values behind its PDF, and their step CDF beside the fitted one.',
        facts: [['Now', onOff('showRawData')], ['New page', 'on']],
        sections: [{
          text: [
            'The histogram is scaled as a probability density, so that it sits on the PDF’s axis. Plotly chooses the bins, up to √n of them, with that limit kept between 5 and 50. In the ln(x) view it is a histogram of ln x.',
            'Off, only the fitted curves are drawn, which is worth it once several fits overlap. A distribution given by metrics has no data and is not affected.',
          ],
        }],
      }),

      'set:chartMin': () => ({
        kicker: SET, title: 'Chart minimum percentile',
        lead: 'Where the x-axis starts, as a percentile: at the lowest value this percentile takes among the distributions drawn.',
        facts: [['Now', typed('chartMinPct')], ['New page', '0.1'], ['Must be', 'above 0 and below the maximum']],
        sections: [{
          text: 'The shaded band and the reference line must lie at or above it. On a linear axis a lower value changes little, since the left tail is squeezed against zero; in the ln(x) view each smaller one stretches the axis further to the left.',
        }],
      }),

      'set:chartMax': () => ({
        kicker: SET, title: 'Chart maximum percentile',
        lead: 'Where the x-axis ends, as a percentile: at the highest value this percentile takes among the distributions drawn.',
        facts: [['Now', typed('chartMaxPct')], ['New page', '99.9'], ['Must be', 'below 100 and above the minimum']],
        sections: [{
          text: 'The shaded band and the reference line must lie at or below it. On a linear axis the right tail is long: at σ = 1, P99.9 is 22 times the median, and a maximum of 99 or 95 shows the body of the distribution better.',
        }],
      }),

      'set:band': () => ({
        kicker: SET, title: 'Shaded band',
        lead: 'Shades each PDF between the percentiles in Shade from and Shade to, and fades the tails outside them, so that the central part stands out.',
        facts: [['Now', onOff('shadeBand')], ['New page', 'on, P5 to P95']],
        sections: [{
          text: [
            'With several distributions every band is fainter, so that one shows through another. The band is drawn with the PDF only.',
            'Off, each PDF is one filled curve, and the two percentiles are greyed out and not checked.',
          ],
        }],
      }),

      'set:shadeFrom': () => ({
        kicker: SET, title: 'Shade from percentile',
        lead: 'The lower edge of the shaded band, as a percentile of each distribution.',
        facts: [['Now', typed('shadeLower')], ['New page', '5'], ['Must be', 'at least the chart minimum, below Shade to']],
        sections: [{ text: 'Greyed out, and not checked, while the shaded band is switched off.' }],
      }),

      'set:shadeTo': () => ({
        kicker: SET, title: 'Shade to percentile',
        lead: 'The upper edge of the shaded band, as a percentile of each distribution.',
        facts: [['Now', typed('shadeUpper')], ['New page', '95'], ['Must be', 'at most the chart maximum, above Shade from']],
        sections: [{ text: 'Greyed out, and not checked, while the shaded band is switched off.' }],
      }),

      'set:ref': () => ({
        kicker: SET, title: 'Reference line',
        lead: 'A dashed vertical line at the Reference-line percentile, from the axis up to each PDF, in the colour of its distribution.',
        facts: [['Now', onOff('referenceLine')], ['New page', 'on, P50 (the median)']],
        sections: [{
          text: [
            'It is drawn with the PDF only: with Curves at CDF only there is none.',
            'Off, its percentile is greyed out and not checked.',
          ],
        }],
      }),

      'set:refPct': () => ({
        kicker: SET, title: 'Reference-line percentile',
        lead: 'Where the reference line stands, as a percentile of each distribution: 50 is the median, 95 the 95th percentile.',
        facts: [['Now', typed('referencePct')], ['New page', '50'], ['Must be', 'within the chart minimum and maximum']],
        sections: [{ text: 'Greyed out, and not checked, while the reference line is switched off.' }],
      }),
    };
  }

  root.lognInfoTopics = lognInfoTopics;
}(typeof self !== 'undefined' ? self : this));
