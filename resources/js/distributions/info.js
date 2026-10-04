/* ==========================================================================
   distributions.html: WHAT EACH (i) SAYS  (for resources/js/kvot-info.js)

   The text of the panel an (i) opens: what a control or section is, what
   its choices do, and where the Help says more. A topic that depends on the
   page (the selected family, its parameterisations) is a function, worked
   out when the panel is drawn, so that it marks the choice in force.
   Inline markup is `code` and **bold** only.
   ========================================================================== */

import { familyById, parameterisationsOf, KNOWN, fixedKeys, FAMILIES } from './families.js';
import { EMPIRICAL_METHODS, BIN_RULES, BANDWIDTH_RULES } from './empirical.js';
import { CRITERIA } from './fit.js';
import { EXPRESSION_FUNCTIONS } from './expr.js';
import { MC_MAX } from './mc.js';
import { SCHEMES, SAMPLE_MAX, SAMPLE_TOTAL_MAX } from './sampling.js';

const more = (label, id) => ({ label, id });

export function infoTopics(app) {
  const active = () => app.activeDist();
  const continuous = FAMILIES.filter((f) => f.kind === 'continuous').length;
  const discrete = FAMILIES.filter((f) => f.kind === 'discrete').length;

  return {
    /* ---- the column ---- */
    'sec:dists': () => {
      const ds = app.state.dists;
      const hidden = ds.filter((d) => !d.visible).map((d) => app.fullName(d));
      return {
        kicker: 'Section', title: 'Distributions',
        lead: 'Every distribution on the page, each with its letter, colour and name. The charts draw them together, the Statistics tab lists them side by side, and the Monte Carlo expressions name them by their letters.',
        facts: [['On the page', `${ds.length} of 16`], ['Selected', active() ? app.fullName(active()) : '—'], ['Hidden in the charts', hidden.length ? hidden.join(', ') : 'none']],
        sections: [{
          heading: 'On each row',
          list: [
            '**The dot** hides the distribution in the charts, or shows it again. It stays in the tables. A click on its name in a chart’s legend does the same.',
            '**The name** selects the distribution for the editor below. The line under it says what it is, or why it is not defined.',
            '**×** removes it.',
          ],
        }, {
          heading: 'The buttons',
          list: [
            '**+ Add** adds a normal distribution with the mean and standard deviation of the selected one; change its family in the editor.',
            '**Duplicate** copies the selected distribution: the quick way to see what changing one number does.',
          ],
        }, {
          text: 'Letters and colours go to the first free place, so removing B leaves C as it was. The first eight colours are distinct for colour-blind readers too; the ninth to sixteenth repeat them with dashed lines.',
        }],
        more: more('The distributions', 'help-dists'),
      };
    },

    'sec:editor': () => {
      const d = active();
      return {
        kicker: 'Section', title: 'The selected distribution',
        lead: 'Everything that defines the selected distribution: its name, its family or kind, the numbers that fix it, and a truncation. Changes take effect as you type; a red field or a message says what is wrong.',
        facts: d ? [['Editing', app.fullName(d)]] : [],
        sections: [{
          list: [
            '**Facts** under the fields give the support, the mean and SD and the median of the distribution as it now is.',
            '**Truncation** limits the distribution to an interval.',
            'A fitted distribution carries its data, which the charts draw behind it; **Remove the data** drops them.',
          ],
        }],
        more: more('Parameterisations', 'help-params'),
      };
    },

    'set:name': {
      kicker: 'Setting', title: 'Name',
      lead: 'A name of your own for the distribution, shown in the list, the legends and the tables after its letter. Left empty, the family (or kind) is used. The letter stays the same whatever the name, and is what a Monte Carlo expression uses.',
    },

    'set:family': () => {
      const d = active();
      const fam = d && d.kind === 'family' ? familyById(d.family) : null;
      return {
        kicker: 'Setting', title: 'Family',
        lead: `The family of the distribution: ${continuous} continuous families, grouped by what they describe, and ${discrete} discrete ones for counts. Under **No family** are the three other kinds: an empirical distribution made from data, a table typed in, and a Monte Carlo expression of other distributions.`,
        facts: [['Now', fam ? fam.label : d ? { empirical: 'Empirical, from data', table: 'Table, typed in', mc: 'Monte Carlo of an expression' }[d.kind] : '—']],
        sections: [{
          text: 'Choosing another family starts it at the same mean and standard deviation as the distribution had, when the new family can have them (a family of one parameter takes the mean alone), and at its defaults when it cannot. Choosing **Empirical** starts it with 200 percentiles of the distribution as it was.',
        }, fam ? { heading: fam.label, text: fam.blurb } : {}],
        more: more('The families', 'help-families'),
      };
    },

    'set:param': () => {
      const d = active();
      const fam = d && d.kind === 'family' ? familyById(d.family) : null;
      const pars = fam ? parameterisationsOf(fam) : [];
      const fixed = fam ? fixedKeys(fam) : [];
      return {
        kicker: 'Setting', title: 'Given by',
        lead: 'The numbers the distribution is given by. Choosing another way converts the distribution as it is into the new numbers, so it does not move until one of them is changed.',
        sections: [
          { heading: 'For this family', choices: pars.map((p) => [p.label, p.id === KNOWN ? 'As many values of the distribution as it has free parameters, solved for.' : p.fields.map((f) => f.label).join(', '), d && p.id === d.param]) },
          {
            heading: 'Known values',
            list: [
              'Each row is a property (mean, median, mode, standard deviation, variance, coefficient of variation, a percentile, geometric mean or geometric SD) and its value; a percentile takes its level in per cent.',
              'The parameters are searched for until every value is met to about twelve significant figures. When no member of the family has the values, the distribution is not drawn until they are possible, and the message names the nearest member and the values it has.',
              ...(fixed.length ? [`This family keeps ${fixed.join(', ')} as given while it solves.`] : []),
            ],
          },
        ],
        more: more('Known values', 'help-known'),
      };
    },

    'set:trunc': () => {
      const d = active();
      const by = d && d.trunc && d.trunc.by === 'percentile' ? 'percentile' : 'value';
      return {
        kicker: 'Setting', title: 'Truncation',
        lead: 'Limits the distribution to an interval: X given lower ≤ X ≤ upper, its density raised so that it again integrates to one. Leave a bound empty for none.',
        sections: [{
          heading: 'Bounds as',
          choices: [
            ['values', 'The bounds are values of x.', by === 'value'],
            ['percentiles', 'The bounds are percentiles of the distribution before truncation, in per cent: 5 and 95 keep the middle 90 % of a continuous distribution. A percentile of 0 or 100 is no bound. Switching between the two keeps the bounds where they are.', by === 'percentile'],
          ],
        }, {
          list: [
            'The line under the bounds gives the probability the interval held before truncation, and with percentiles the values they cut at.',
            'Every statistic of a truncated distribution is worked out numerically, from the truncated quantile function.',
            'For a discrete distribution the bounds are included; for one on whole numbers they are rounded inwards (a lower bound of 2.5 starts at 3). A percentile bound is the smallest value whose cumulative probability reaches the percentile, and it is kept.',
            'A bound where the distribution has no probability at all is refused.',
          ],
        }],
        more: more('Truncation', 'help-trunc'),
      };
    },

    'set:empMethod': () => {
      const d = active();
      return {
        kicker: 'Setting', title: 'Method',
        lead: 'How the data become a distribution, without a family.',
        sections: [{ choices: EMPIRICAL_METHODS.map(([k, label]) => [label.split(' (')[0], {
          interpolated: 'Straight lines between the sorted values on the cumulative curve. Its percentiles are the usual sample percentiles (type 7), and it stays between the smallest and the largest value.',
          kde: 'A normal kernel on every value: smooth, and reaching a little beyond the data.',
          histogram: 'Equal-width bins, with the probability of each spread evenly over it.',
          ecdf: 'The sample itself: probability 1/n on each value, a discrete distribution.',
        }[k], d && d.emp && d.emp.method === k]) }],
        more: more('Empirical distributions', 'help-empirical'),
      };
    },

    'set:bandwidth': () => {
      const d = active();
      return {
        kicker: 'Setting', title: 'Bandwidth',
        lead: 'The standard deviation h of the normal kernel on each value. A small h follows the data closely and is bumpy; a large one is smooth and spreads the distribution.',
        sections: [{ choices: [...BANDWIDTH_RULES, ['given', 'Given: the h you type']].map(([k, label]) => [label.split(':')[0], label.includes(':') ? label.split(': ')[1] : label, d && d.emp && d.emp.bw === k]) },
          { text: '**In ln x** puts the kernels on the logarithms of positive data: the distribution then has no probability below zero, and h is in units of ln x.' }],
        more: more('Empirical distributions', 'help-empirical'),
      };
    },

    'set:bins': () => {
      const d = active();
      return {
        kicker: 'Setting', title: 'Bins',
        lead: 'How many bins of equal width the histogram has, from the smallest value to the largest.',
        sections: [{ choices: [...BIN_RULES, ['count', 'A number of bins: the count you type']].map(([k, label]) => [label.split(':')[0], label.split(': ')[1] || '', d && d.emp && d.emp.bins === k]) }],
        more: more('Empirical distributions', 'help-empirical'),
      };
    },

    'set:empData': {
      kicker: 'Setting', title: 'Data',
      lead: 'The values the distribution is made from, separated by spaces, commas, semicolons or new lines. Text that is not a number is skipped. Up to 5,000 values are shown here; a larger set is kept but not shown, and pasting replaces it.',
      sections: [{ text: 'The Fit tab’s **Or no family** buttons make an empirical distribution from the data entered there, file and column included.' }],
      more: more('Empirical distributions', 'help-empirical'),
    },

    'set:tableMode': () => ({
      kicker: 'Setting', title: 'Table',
      lead: 'A distribution written down by hand.',
      sections: [{ choices: [
        ['Cumulative', 'Values with their cumulative probabilities F(x), joined by straight lines: the way percentiles from an expert are often recorded. F starts at 0, ends at 1 and never decreases.', active() && active().table.mode === 'cdf'],
        ['Probabilities', 'Values with their probabilities: a discrete distribution. Probabilities that do not add up to one are scaled, and a note says so.', active() && active().table.mode === 'pmf'],
      ] }],
      more: more('Tables', 'help-tables'),
    }),

    'set:tableRows': {
      kicker: 'Setting', title: 'Rows',
      lead: 'One pair of numbers per line: the value, then its cumulative probability or its probability. The pair may be separated by spaces, a tab, a comma or a semicolon. A line without exactly two numbers is left out, and the message says how many were.',
      more: more('Tables', 'help-tables'),
    },

    'set:mcExpr': {
      kicker: 'Setting', title: 'Expression',
      lead: 'What is drawn: an expression of the distributions’ letters, evaluated draw by draw, such as `A * B`, `exp(A) / (1 + B^2)` or `max(A, B, C)`.',
      sections: [{
        list: [
          'Numbers, the letters, `+ - * / ^` (or `**`), parentheses, `pi` and `e`.',
          `The functions ${EXPRESSION_FUNCTIONS.join(', ')}.`,
          'The distributions are drawn independently, each from a stream of its own, by the sampling scheme chosen below, so the same seed gives the same draws.',
          `Up to ${MC_MAX.toLocaleString('en')} draws. Draws that give no finite number (a logarithm of zero, a division by zero) are left out and counted.`,
          'The result is redrawn whenever a distribution it uses changes. An expression cannot use itself, directly or through another.',
        ],
      }],
      more: more('Monte Carlo of an expression', 'help-mc'),
    },

    'set:mcScheme': () => {
      const d = active();
      const cur = d && d.mc ? d.mc.scheme : 'random';
      return {
        kicker: 'Setting', title: 'Sampling scheme',
        lead: 'How the letters are drawn: the uniform numbers each distribution’s draws come from. The schemes are those of the Sample tab; a simple random or Latin hypercube draw of a letter is the Sample tab’s draw of it with the same seed.',
        sections: [{
          choices: SCHEMES.map(([k, label]) => [label, {
            random: 'Independent draws: the result wanders from its exact value by about its SD/√n.',
            lhs: 'One draw of each letter in each of n equal strata of its probability, in random order: the tails of every input are drawn in proportion.',
            'lhs-centred': 'The same at the middle of each stratum.',
            sobol: 'A low-discrepancy sequence across the letters (A the first dimension, B the second, …), scrambled with the seed: the draws of the letters together fill their joint probabilities evenly, so a mean or a percentile of the result settles far faster than with random draws. Balanced when n is a power of two.',
            halton: 'Another low-discrepancy sequence, a prime base for each letter, its digits scrambled with the seed.',
          }[k], cur === k]),
        }],
        more: more('Monte Carlo of an expression', 'help-mc'),
      };
    },

    'set:shift': {
      kicker: 'Setting', title: 'Shift',
      lead: 'A number added to every value: X + shift, the whole distribution moved along x. Leave it empty for none.',
      sections: [{ list: [
        'The mean, the median, the mode and every percentile move by the shift; the SD, the skewness, the kurtosis and the entropy stay as they are. The geometric mean and SD are worked out again.',
        'A distribution on whole numbers takes a whole-number shift, so that it stays on whole numbers.',
        'The shift comes before the truncation: the bounds are values of the shifted distribution.',
        'Known values describe the shifted distribution: a shift of 100 and a mean of 105 give the family a mean of 5.',
        'A fitted distribution has no shift; one added afterwards moves the curve away from its data.',
      ] }],
      more: more('Shift', 'help-shift'),
    },

    'set:mcMethod': {
      kicker: 'Setting', title: 'The draws as',
      lead: 'How the draws become a distribution: the same four methods as an empirical distribution. Kernel density gives a smooth curve; interpolated keeps the draws’ own percentiles exactly.',
      more: more('Monte Carlo of an expression', 'help-mc'),
    },

    /* ---- the chart ---- */
    'tab:chart': () => {
      const c = app.state.chart;
      const labels = { pdf: 'density / probability', cdf: 'cumulative probability', sf: 'exceedance probability', quantile: 'quantile function', hazard: 'hazard rate', none: 'nothing' };
      return {
        kicker: 'Tab', title: 'Chart',
        lead: 'Every visible distribution drawn together, in one chart and, if chosen, a second one below.',
        facts: [['Above', labels[c.top]], ['Below', labels[c.bottom]], ['Axes', `${c.logx ? 'log' : 'linear'} x, ${c.logy ? 'log' : 'linear'} y`]],
        sections: [{
          choices: [
            ['Density / probability', 'The density of a continuous distribution; the probability of each value of a discrete one, drawn as stems.'],
            ['Cumulative probability', 'F(x) = P(X ≤ x).'],
            ['Exceedance probability', '1 − F(x) = P(X > x); with log y, the way to read a tail.'],
            ['Quantile function', 'The value at each cumulative probability: the inverse of F.'],
            ['Hazard rate', 'f(x)/(1 − F(x)): the rate of an event at x, given that it has not happened before.'],
          ],
        }, {
          list: [
            '**log x** draws the density per decade, x·f(x)·ln 10, so that areas on the logarithmic axis are still probabilities.',
            '**data** draws the data a fitted (or empirical) distribution carries: a histogram behind its density, steps beside its cumulative curve.',
            '**samples** draws each distribution’s draws from the Sample tab the same way, with dotted outlines.',
            '**bins** sets the histograms: a rule (Freedman–Diaconis, the default, Scott, Sturges, square root, Rice), a number of bins, or a bin width (in decades on a log x-axis, the edges at its multiples, so that histograms side by side share them).',
            'Pointing at a chart lists the value of every curve at that x. Clicking a name in the legend hides or shows that distribution.',
            'Under the chart are the mean, SD, median, mode and 5th and 95th percentiles of every distribution it shows, the selected one in bold, and with **samples** ticked those of each one’s draws below it.',
          ],
        }],
        more: more('The chart', 'help-chart'),
      };
    },

    'set:range': {
      kicker: 'Setting', title: 'The x-axis',
      lead: 'The x-axis covers every visible distribution from its lowest to its highest percentile given here (0.1 and 99.9 unless changed), and the data drawn with them. Values typed into **or values** replace either end.',
      sections: [{ list: ['**Save the curves as CSV** writes the upper chart’s values: the distribution, x (or p for the quantile function) and the value, one row per point drawn.'] }],
      more: more('The chart', 'help-chart'),
    },

    /* ---- statistics ---- */
    'tab:stats': {
      kicker: 'Tab', title: 'Statistics',
      lead: 'Every distribution side by side: what it is, where it lies (mean, median, mode, geometric mean), how spread it is (SD, variance, CV, geometric SD, interquartile range, median absolute deviation), its shape (skewness, excess kurtosis, entropy) and its percentiles.',
      sections: [{
        list: [
          'A moment shown as **∞** is infinite: one tail makes it so while the moments below it are finite. **undefined** means both tails do, or a lower moment is already infinite. A distribution of a single value has no skewness or kurtosis.',
          'Excess kurtosis is zero for a normal distribution. Entropy is the differential entropy, in nats, for a continuous distribution.',
          'A distribution that carries data also gets its number of values, its log-likelihood and K–S D against them.',
          '**Significant digits** round the table; **Save as CSV** keeps every digit.',
        ],
      }],
      more: more('Statistics', 'help-stats'),
    },

    /* ---- fit ---- */
    'fit:data': {
      kicker: 'Fit', title: 'Data',
      lead: 'The values to fit: pasted or typed, opened from a CSV or text file, or dropped on the box.',
      sections: [{
        list: [
          'Numbers may be separated by spaces, tabs, commas, semicolons or new lines. Text that is not a number is skipped and counted.',
          'With **decimal comma** a comma is part of a number (1,5) and only the other characters separate.',
          'A table of several columns (from a file, or pasted from a spreadsheet) offers a choice of **Column**; a first line of names is read as the header.',
          'The figures under the box describe the data; SD is the sample SD, with n − 1.',
        ],
      }],
      more: more('Fitting to data', 'help-fit'),
    },

    'fit:settings': () => {
      const f = app.state.fit;
      return {
        kicker: 'Fit', title: 'Fit',
        lead: 'Which families are fitted, how, and how the fits are ranked. The fits are redone by themselves when the data or these settings change; **Fit and rank** starts them for more than 20,000 values.',
        sections: [{
          heading: 'Families',
          choices: [
            ['by the data', 'Discrete families when every value is a whole number of zero or more, continuous ones otherwise.', f.kind === 'auto'],
            ['continuous', 'Densities, for measured quantities.', f.kind === 'continuous'],
            ['discrete', 'Probabilities, for counts.', f.kind === 'discrete'],
          ],
          text: 'A continuous and a discrete fit cannot be ranked together: one likelihood is a density, the other a probability. **Which families** narrows the list; a family that cannot take the data says why.',
        }, {
          heading: 'Method',
          choices: [
            ['maximum likelihood', 'The parameters under which the data are the most probable.', f.mle],
            ['method of moments', 'The parameters whose mean and variance (and skewness, for three; the kurtosis for the Student t) are the sample’s.', f.mom],
          ],
        }, {
          heading: 'Rank by',
          choices: CRITERIA.map(([k, label]) => [label, {
            aic: 'Akaike’s information criterion, 2k − 2 ln L. Smaller is better.',
            aicc: 'AIC with the correction for a small sample.',
            bic: 'The Bayesian information criterion, k ln n − 2 ln L, which charges more for parameters.',
            ks: 'The largest gap between the empirical and the fitted CDF.',
            ad: 'Anderson–Darling: squared gaps weighted towards the tails.',
            cvm: 'Cramér–von Mises: squared gaps, unweighted.',
            chi2p: 'Pearson’s chi-square p-value over cells of expected count five or more (discrete only). Larger is better.',
            logL: 'The log-likelihood itself. Larger is better, but it never charges for parameters.',
          }[k], f.criterion === k]),
        }, {
          heading: 'Binomial trials n',
          text: 'For the binomial and the beta-binomial: the number of trials behind each count, when it is known. Left empty, the binomial’s n is estimated and the beta-binomial is not fitted.',
        }],
        more: more('Fitting to data', 'help-fit'),
      };
    },

    'fit:results': {
      kicker: 'Fit', title: 'The fits, best first',
      lead: 'Every family fitted, scored on the same data and sorted by the criterion chosen; a click on a column’s heading sorts by it.',
      sections: [{
        list: [
          '**Parameters** with ± their standard errors, from the curvature of the log-likelihood at its maximum, where the family is regular.',
          '**Δ** is the difference from the best by the chosen criterion; **Weight** the Akaike weight exp(−Δ/2), normalised over the fits of the same method.',
          '**K–S D** and **A²** carry in brackets the p-value for a distribution chosen before the data were seen. A fitted one gets one that is too large, so they rank and do not test.',
          'For a discrete fit, **χ²** gives the statistic, its degrees of freedom (reduced by the parameters fitted) and its p-value.',
          '**Add** puts the fit into the list of distributions with its data; **Add the best** adds the first row.',
          'A family that could not be fitted is listed last, with the reason.',
        ],
      }],
      more: more('Ranking the fits', 'help-criteria'),
    },

    'fit:plot': {
      kicker: 'Fit', title: 'The fits against the data',
      lead: 'The fits ticked in the table’s first column (the three best to begin with, up to eight) against the data.',
      sections: [{
        choices: [
          ['Density', 'Over a histogram of the data (or, for counts, the frequency of each value).'],
          ['Cumulative', 'Over the empirical cumulative curve.'],
          ['P–P', 'The fitted probability of each value against its empirical probability. On the diagonal is a perfect fit.'],
          ['Q–Q', 'The sorted data against the fitted quantiles. A curve leaving the diagonal at the ends is a tail the fit gets wrong.'],
        ],
      }, {
        list: ['**bins** sets the histogram of the density plot: a rule (Freedman–Diaconis, Scott, Sturges, square root, Rice), a number of bins, or a bin width (in decades on a log x-axis, the edges at its multiples).'],
      }],
      more: more('Ranking the fits', 'help-criteria'),
    },

    'fit:empirical': {
      kicker: 'Fit', title: 'Or no family',
      lead: 'The data as a distribution of their own, added to the list: interpolated between the sorted values, a kernel density, a histogram, or the empirical CDF itself.',
      more: more('Empirical distributions', 'help-empirical'),
    },

    /* ---- calculate ---- */
    'calc:prob': {
      kicker: 'Calculate', title: 'Probabilities',
      lead: 'For every distribution: P(X ≤ x), P(X > x), P(a < X ≤ b), the density (or probability) at x and the hazard rate at x.',
      sections: [{ list: ['The numbers start at the median and the quartiles of the selected distribution.', '**Shade** colours a to b under the selected distribution’s density in the Chart tab.', 'For a discrete distribution the probability between is of the values above a and up to b.'] }],
      more: more('Calculations', 'help-calc'),
    },

    'calc:quant': {
      kicker: 'Calculate', title: 'Percentiles and intervals',
      lead: 'The values at the percentiles listed, and two intervals that hold the probability given.',
      sections: [{ choices: [
        ['central', 'The same probability left out on each side: from the (100 − c)/2 to the (100 + c)/2 percentile.'],
        ['shortest', 'The narrowest interval holding the probability: for a skewed distribution it moves towards the mode, and for a unimodal one it is the highest-density interval.'],
      ] }],
      more: more('Calculations', 'help-calc'),
    },

    'calc:tail': {
      kicker: 'Calculate', title: 'Tails and expectations',
      lead: 'Means of parts of the distribution.',
      sections: [{ choices: [
        ['E[X | X > t]', 'The mean of the values above the threshold.'],
        ['E[X | X ≤ t]', 'The mean of the values up to it.'],
        ['E[(X − t)⁺]', 'The expected excess over the threshold, counting zero below it.'],
        ['value at level', 'The percentile at the level: the value at risk.'],
        ['mean beyond it', 'The mean of the values from that percentile up: the expected shortfall, or tail value at risk.'],
      ] }, { text: 'A mean that the tail makes infinite (a Pareto with α ≤ 1) is shown as ∞.' }],
      more: more('Calculations', 'help-calc'),
    },

    'calc:compare': {
      kicker: 'Calculate', title: 'Two distributions',
      lead: 'How two distributions differ.',
      sections: [{ choices: [
        ['P(X > Y)', 'The probability that a draw of X exceeds a draw of Y, drawn independently; ties count only between two discrete distributions.'],
        ['Overlap', 'The area under the lower of the two densities (or the sum of the lower probabilities): 1 for the same distribution, 0 for two apart.'],
        ['K–S', 'The largest gap between the two cumulative curves.'],
        ['Wasserstein', 'The area between the cumulative curves: how far, on average, probability must be moved to turn one into the other.'],
        ['Hellinger', '√(1 − ∫√(f g)), from 0 (the same) to 1 (no overlap).'],
        ['Kullback–Leibler', 'The information lost when one is used for the other; not symmetric, and infinite where the second has no probability.'],
      ] }, { text: 'The overlap, Hellinger and Kullback–Leibler compare a density with a density or a probability with a probability; between a continuous and a discrete distribution they are shown as —.' }],
      more: more('Calculations', 'help-calc'),
    },

    'tab:sample': () => {
      const sm = app.state.sample;
      return {
        kicker: 'Tab', title: 'Sample',
        lead: 'n draws of each chosen distribution, by inverse transform: a number u between 0 and 1 becomes the value at probability u. The scheme decides the u’s; the seed makes the draws the same every time.',
        sections: [{
          heading: 'Scheme',
          choices: [
            [SCHEMES[0][1], 'Independent draws: what a Monte Carlo simulation takes. Its mean wanders from the distribution’s by about SD/√n.', sm.scheme === 'random'],
            [SCHEMES[1][1], 'One draw from each of n equally probable strata, at a random place in it, the strata in random order: the sample covers the whole distribution, tails included, and its mean is much closer to the distribution’s.', sm.scheme === 'lhs'],
            [SCHEMES[2][1], 'The same at the middle of each stratum: the sample is the n quantiles at (i − ½)/n, in random order. Nothing is random but the order.', sm.scheme === 'lhs-centred'],
            [SCHEMES[3][1], 'A low-discrepancy sequence (Joe and Kuo’s direction numbers), scrambled at random so that the seed matters. It fills the probabilities more evenly than random draws do, in every distribution and between them; it is balanced when n is a power of two.', sm.scheme === 'sobol'],
            [SCHEMES[4][1], 'A low-discrepancy sequence in a prime base for each distribution (2 for A, 3 for B, …), its digits scrambled at random.', sm.scheme === 'halton'],
          ],
        }, {
          list: [
            `**Draws of each**: from 1 to ${SAMPLE_MAX.toLocaleString('en')} for each distribution, ${SAMPLE_TOTAL_MAX.toLocaleString('en')} in all. Up to 200,000 in all they are drawn by themselves when anything changes; above that, **Draw** takes them.`,
            '**Seed**: any whole number. Each distribution draws from a stream of its own made from the seed and its letter, so its draws do not change when another distribution is added, changed or left out. A simple random or Latin hypercube sample is the same draws a Monte Carlo expression with that seed takes.',
            'In the two sequences the letter is also the dimension, A the first, so draws of several distributions taken together fill the space of their probabilities evenly; they have 16 dimensions, for the letters A to P.',
            'The draws of different distributions are independent of each other: no correlation is imposed.',
            '**show in the chart** draws them there: a histogram behind each density, steps beside each cumulative curve (the chart’s **samples** box is the same setting).',
            'The table sets each statistic of the draws over the distribution’s own, below it. K–S D is the largest gap between the draws’ cumulative curve and the distribution’s, with its p-value: a low-discrepancy or Latin hypercube sample has a smaller D than a random one would, and so a p-value near 1.',
          ],
        }],
        more: more('Samples', 'help-sample'),
      };
    },

    'sample:out': {
      kicker: 'Sample', title: 'Saving the draws',
      lead: 'The draws as they were drawn, a column for each distribution, its name in the first row.',
      sections: [{ list: [
        '**Save as CSV** writes them with every digit; **Save as Excel** writes a workbook with the draws and a sheet of the settings and each distribution’s exact mean and SD; **Copy** puts them on the clipboard, a tab between columns, to paste into a spreadsheet.',
        '**Fit these** hands one distribution’s draws to the Fit tab: a way to see how well a sample of that size pins down its own family.',
      ] }],
      more: more('Samples', 'help-sample'),
    },

    'calc:mc': {
      kicker: 'Calculate', title: 'Monte Carlo of an expression',
      lead: 'An expression of the distributions’ letters, drawn many times, becomes a distribution of its own in the list, which is redrawn whenever a distribution it uses changes.',
      sections: [{ list: [
        'For example `A * B` for a product of two quantities, `A + B + C` for a sum, `max(A, B)` for the larger.',
        'The distributions are drawn independently; the seed fixes the draws, and the scheme decides how evenly they cover each distribution: Latin hypercube, Sobol and Halton cover them far more evenly than simple random draws.',
        'The expression, the number of draws and the seed can be changed afterwards in the distribution’s editor.',
      ] }],
      more: more('Monte Carlo of an expression', 'help-mc'),
    },
  };
}
