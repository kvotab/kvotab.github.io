import json, sys

def flat(obj, prefix=''):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flat(v, prefix + '/' + str(k)))
    elif isinstance(obj, list):
        out[prefix] = json.dumps(obj, sort_keys=True)
    else:
        out[prefix] = obj
    return out

a = flat(json.load(open(sys.argv[1])))
b = flat(json.load(open(sys.argv[2])))
keys = sorted(set(a) | set(b))
diffs = [(k, a.get(k, '<missing>'), b.get(k, '<missing>')) for k in keys if a.get(k) != b.get(k)]
if not diffs:
    print('IDENTICAL (%d compared fields)' % len(keys))
else:
    print('%d of %d fields differ:' % (len(diffs), len(keys)))
    for k, x, y in diffs:
        print('  %-52s %s  ->  %s' % (k, str(x)[:60], str(y)[:60]))
