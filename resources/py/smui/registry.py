"""The names the page calls, and the functions behind them.

Every analysis module registers its entry points with @api('platform.name');
dispatch() looks the name up, passes the JSON payload as keyword arguments,
and returns the result as JSON.
"""
import json
import traceback

API = {}


def api(name):
    def deco(fn):
        API[name] = fn
        return fn
    return deco


def dispatch(name, payload_json, _data=None):
    """Run one analysis. Python warnings raised on the way (a fit that did
    not converge, a singular design) come back in the result's 'warnings'."""
    import warnings
    from .util import to_json
    fn = API.get(name)
    if fn is None:
        raise KeyError(f'no backend function {name!r}')
    payload = json.loads(payload_json) if payload_json else {}
    if _data is not None:
        payload['data'] = _data
    # The page sends every call the table's name, for the code it shows; a
    # function that writes no code need not take it. Other arguments a
    # function does not take are dropped too, with a line in the log.
    for k in [k for k in payload if not _takes(fn, k)]:
        payload.pop(k)
        if k != 'table_name':
            import sys
            print(f'smui: {name} takes no argument {k!r}; ignored', file=sys.stderr)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        out = fn(**payload)
    seen = []
    for w in caught:
        text = f'{w.category.__name__}: {w.message}'
        # Deprecations are for whoever maintains the code, not for the reader
        # of the report: to the log (the browser console) with them.
        if issubclass(w.category, (DeprecationWarning, PendingDeprecationWarning, FutureWarning)):
            import sys
            print(f'smui: {name}: {text}', file=sys.stderr)
            continue
        if text not in seen:
            seen.append(text)
    if seen and isinstance(out, dict):
        out = dict(out)
        out.setdefault('warnings', seen[:12])
    return to_json(out)


def dispatch_bytes(name, payload_json, data):
    """dispatch() for a function that also takes the bytes of a file (a
    memoryview from the page), as its `data` argument."""
    return dispatch(name, payload_json, _data=bytes(data))


def _takes(fn, name):
    import inspect
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    return name in sig.parameters or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())


def names():
    return sorted(API)
