"""The model's own functions, written out where they are called.

A port of ``src/sim/functions.js``. A function block is a name, a list of
parameters and one equation; a call of it is replaced by its body with the
arguments put in for the parameters, so nothing downstream has to know
functions exist. A reference in the body that is not a parameter means what
it means where the function is written, and carries that scope with it.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set

from ..names import qualified_name, resolve_reference
from .lang import Binary, Call, Cond, Node, ParseError, Ref, Unary, parse

MAX_DEPTH = 32


class FunctionError(ValueError):
    def __init__(self, message: str, block_name: Optional[str] = None) -> None:
        super().__init__(message)
        self.block_name = block_name


def _scoped(ast: Node, params: Set[str], system: str) -> Node:
    t = ast.type
    if t == 'ref':
        return ast if ast.name in params else Ref(ast.name, ast.indices, system)  # type: ignore[attr-defined]
    if t == 'unary':
        return Unary(ast.op, _scoped(ast.operand, params, system))  # type: ignore[attr-defined]
    if t == 'binary':
        return Binary(ast.op, _scoped(ast.left, params, system),  # type: ignore[attr-defined]
                      _scoped(ast.right, params, system))  # type: ignore[attr-defined]
    if t == 'cond':
        return Cond(_scoped(ast.test, params, system), _scoped(ast.then, params, system),  # type: ignore
                    _scoped(ast.otherwise, params, system))  # type: ignore[attr-defined]
    if t == 'call':
        return Call(ast.name, [_scoped(a, params, system) for a in ast.args], ast.scope)  # type: ignore
    return ast


def _substitute(ast: Node, bound: Dict[str, Node], fn_name: str) -> Node:
    t = ast.type
    if t == 'ref':
        arg = bound.get(ast.name)  # type: ignore[attr-defined]
        if arg is None:
            return ast
        if ast.indices:  # type: ignore[attr-defined]
            raise FunctionError(f"'{ast.name}[…]' asks for an index of a parameter of '{fn_name}'. An "  # type: ignore
                                'argument is a single value, already worked out where the function is called: put '
                                'the index there instead.', fn_name)
        return arg
    if t == 'unary':
        return Unary(ast.op, _substitute(ast.operand, bound, fn_name))  # type: ignore[attr-defined]
    if t == 'binary':
        return Binary(ast.op, _substitute(ast.left, bound, fn_name),  # type: ignore[attr-defined]
                      _substitute(ast.right, bound, fn_name))  # type: ignore[attr-defined]
    if t == 'cond':
        return Cond(_substitute(ast.test, bound, fn_name), _substitute(ast.then, bound, fn_name),  # type: ignore
                    _substitute(ast.otherwise, bound, fn_name))  # type: ignore[attr-defined]
    if t == 'call':
        return Call(ast.name, [_substitute(a, bound, fn_name) for a in ast.args], ast.scope)  # type: ignore
    return ast


class UserFunctions:
    """The functions of one model, parsed once, ready to be inlined."""

    def __init__(self, functions: List[Dict[str, Any]],
                 callable_: Optional[Callable[[str, str], bool]] = None) -> None:
        self.defs: Dict[str, Dict[str, Any]] = {}
        declared = {qualified_name(f) for f in functions if f.get('name')}
        self._declared = declared
        for f in functions:
            if not f.get('name'):
                continue
            name = qualified_name(f)
            parameters = [str(p) for p in f.get('parameters') or []]
            text = str(f.get('equation') if f.get('equation') is not None else '').strip()
            if not text:
                what = f'its parameters ({", ".join(parameters)})' if parameters else \
                    'numbers and the built-in functions'
                raise FunctionError(f"'{name}' has no body yet. Write what it works out to in terms of {what}, or "
                                    'delete it and the equations that call it.', name)
            system = f.get('system') or ''
            try:
                ast = parse(text, calls=lambda n, s=system: bool(self.resolve(n, s))
                            or bool(callable_ and callable_(n, s)))
            except ParseError as e:
                raise FunctionError(f"{e} in the body of '{name}' (at character {e.position + 1})", name) from None
            self.defs[name] = {'name': name, 'parameters': parameters, 'block': f,
                               'ast': _scoped(ast, set(parameters), system)}

    def __len__(self) -> int:
        return len(self.defs)

    def resolve(self, written: str, system: str) -> Optional[str]:
        q = resolve_reference(written, system or '', lambda n: n in self._declared)
        return q if q and q in self._declared else None

    def inline(self, ast: Node, owner: Optional[str] = None, system: str = '') -> Node:
        return self._expand(ast, owner, system, [], 0)

    def _expand(self, ast: Node, owner: Optional[str], system: str, stack: List[str], depth: int) -> Node:
        if depth > MAX_DEPTH:
            raise FunctionError(f"'{stack[-1] if stack else owner}' nests function calls more than {MAX_DEPTH} deep.",
                                owner)
        t = ast.type

        def go(node: Node) -> Node:
            return self._expand(node, owner, system, stack, depth)

        if t in ('ref', 'num'):
            return ast
        if t == 'unary':
            return Unary(ast.op, go(ast.operand))  # type: ignore[attr-defined]
        if t == 'binary':
            return Binary(ast.op, go(ast.left), go(ast.right))  # type: ignore[attr-defined]
        if t == 'cond':
            return Cond(go(ast.test), go(ast.then), go(ast.otherwise))  # type: ignore[attr-defined]
        if t == 'call':
            args = [go(a) for a in ast.args]  # type: ignore[attr-defined]
            scope = ast.scope if ast.scope is not None else system  # type: ignore[attr-defined]
            q = self.resolve(ast.name, scope)  # type: ignore[attr-defined]
            fn = self.defs.get(q) if q else None
            if fn is None:
                return Call(ast.name, args, ast.scope)  # type: ignore[attr-defined]
            if fn['name'] in stack:
                chain = ' → '.join([*stack, fn['name']])
                raise FunctionError(f"'{fn['name']}' calls itself ({chain}). A function is worked out where it is "
                                    'called, so there would be nothing to stop at.', stack[0] if stack else owner)
            params = fn['parameters']
            if len(args) != len(params):
                named = f' ({", ".join(params)})' if params else ''
                raise FunctionError(f"'{fn['name']}' takes {len(params)} argument{'' if len(params) == 1 else 's'}"
                                    f"{named}, but is called with {len(args)}.", owner)
            body = _substitute(fn['ast'], dict(zip(params, args)), fn['name'])
            return self._expand(body, owner, fn['block'].get('system') or '', [*stack, fn['name']], depth + 1)
        return ast
