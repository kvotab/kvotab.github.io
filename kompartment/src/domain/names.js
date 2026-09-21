/**
 * What a name may be, in one place.
 *
 * Two rules, and both have to hold at every gate a name comes through -- the
 * editor's `validateName`, `Project`'s validation of a file, the importer's
 * renaming of what an .eco file calls things -- or the rule is only advisory.
 * They used to be written out in three files, with a comment in each saying
 * the copies must agree and nothing that checked they did.
 */

import { FUNCTIONS, FUNCTION_ALIASES } from '../parser/functions.js';

/** An identifier: letters, digits and underscore, not starting with a digit. */
export const NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

/**
 * Names nothing in a model may have.
 *
 * Every function name: a block called `min` could never be referenced,
 * because the parser resolves `min(` as a call before looking for a block.
 *
 * And the three that pass NAME_RE without being names. `__proto__` passes,
 * and a model is full of maps keyed by a block's name -- the diagram layout
 * most of all. `layout['__proto__']` is not a missing entry, it is
 * `Object.prototype`, so a position written into it went onto every object in
 * the program. `constructor` and `prototype` are the same trap one step less
 * severe. No model needs any of them.
 */
export const RESERVED = new Set([
	...Object.keys(FUNCTIONS),
	...Object.keys(FUNCTION_ALIASES),
	'__proto__', 'constructor', 'prototype',
]);
