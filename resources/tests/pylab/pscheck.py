"""A checker for the Encapsulated PostScript that saveas and print write,
for the tests (there is no PostScript interpreter to draw it with here).

    problems, counts = check_eps(text)

reads the file as an interpreter would: the DSC header and bounding box,
the tokens (strings, hex and ASCII85 strings, arrays, dictionaries,
procedures), and the operators PyLAB writes, run on an operand stack that
checks their operands' number and kinds, gsave/grestore and begin/end
balanced, the fonts selected defined, and each image's data (ASCII85,
then Flate) decoded to exactly width x height x 3 bytes. problems lists
what is wrong (empty when nothing is); counts says how many of each
operator ran.
"""
import re
import zlib

DELIMS = b'()<>[]{}/%'
WS = b' \t\r\n\f\x00'
NUM = re.compile(rb'[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$')


class Name(str):
    """An executable name."""


class Lit(str):
    """A literal name (/name)."""


class Proc(list):
    """A procedure, {...}."""


MARK = object()


class Reader:
    def __init__(self, data):
        self.d = data
        self.i = 0

    def raw_until(self, end):
        """The bytes up to (not with) end, which is passed over."""
        j = self.d.find(end, self.i)
        if j < 0:
            raise ValueError(f'no {end!r} after the data')
        s = self.d[self.i:j]
        self.i = j + len(end)
        return s

    def token(self):
        d, n = self.d, len(self.d)
        while self.i < n:
            c = d[self.i:self.i + 1]
            if c in WS:
                self.i += 1
            elif c == b'%':
                j = d.find(b'\n', self.i)
                self.i = n if j < 0 else j + 1
            else:
                break
        if self.i >= n:
            return None
        c = d[self.i:self.i + 1]
        if c == b'(':
            depth, j, out = 0, self.i, bytearray()
            j += 1
            while True:
                if j >= n:
                    raise ValueError('an unclosed string')
                ch = d[j:j + 1]
                if ch == b'\\':
                    nxt = d[j + 1:j + 2]
                    if nxt in b'01234567' and nxt:
                        m = re.match(rb'[0-7]{1,3}', d[j + 1:j + 4])
                        out.append(int(m.group(0), 8) & 255)
                        j += 1 + len(m.group(0))
                        continue
                    out += {b'n': b'\n', b'r': b'\r', b't': b'\t', b'b': b'\b', b'f': b'\f'}.get(nxt, nxt)
                    j += 2
                    continue
                if ch == b'(':
                    depth += 1
                elif ch == b')':
                    if depth == 0:
                        self.i = j + 1
                        return bytes(out)
                    depth -= 1
                if ord(ch) > 126 or (ord(ch) < 32 and ch not in b'\n\r\t'):
                    raise ValueError('a string with a byte that is not clean 7-bit text')
                out += ch
                j += 1
        if d.startswith(b'<<', self.i):
            self.i += 2
            return Name('<<')
        if d.startswith(b'>>', self.i):
            self.i += 2
            return Name('>>')
        if d.startswith(b'<~', self.i):
            self.i += 2
            return ('a85', self.raw_until(b'~>'))
        if c == b'<':
            self.i += 1
            h = re.sub(rb'\s', b'', self.raw_until(b'>'))
            if not re.fullmatch(rb'[0-9A-Fa-f]*', h):
                raise ValueError('a hex string with a character that is not hex')
            return bytes.fromhex((h + b'0' * (len(h) % 2)).decode())
        if c in b'[]{}':
            self.i += 1
            return Name(c.decode())
        if c == b'/':
            j = self.i + 1
            while j < n and d[j:j + 1] not in WS and d[j:j + 1] not in DELIMS:
                j += 1
            name = d[self.i + 1:j].decode('latin-1')
            self.i = j
            return Lit(name)
        j = self.i
        while j < n and d[j:j + 1] not in WS and d[j:j + 1] not in DELIMS:
            j += 1
        tok = d[self.i:j]
        self.i = j
        if NUM.match(tok):
            return float(tok)
        return Name(tok.decode('latin-1'))


def ascii85(data):
    data = re.sub(rb'\s', b'', data)
    out = bytearray()
    group = []
    for ch in data:
        if ch == ord('z') and not group:
            out += b'\0\0\0\0'
            continue
        if not 33 <= ch <= 117:
            raise ValueError('a character that is not ASCII85')
        group.append(ch - 33)
        if len(group) == 5:
            v = 0
            for g in group:
                v = v * 85 + g
            out += v.to_bytes(4, 'big')
            group = []
    if group:
        k = len(group)
        group += [84] * (5 - k)
        v = 0
        for g in group:
            v = v * 85 + g
        out += v.to_bytes(4, 'big')[:k - 1]
    return bytes(out)


def check_eps(text):
    data = text.encode('latin-1') if isinstance(text, str) else text
    problems = []
    lines = data.decode('latin-1').split('\n')
    if not lines[0].startswith('%!PS-Adobe-3.0 EPSF-3.0'):
        problems.append('the first line is not %!PS-Adobe-3.0 EPSF-3.0')
    bb = [ln for ln in lines if ln.startswith('%%BoundingBox:')]
    if len(bb) != 1 or not re.fullmatch(r'%%BoundingBox: 0 0 \d+ \d+', bb[0].strip()):
        problems.append(f'the bounding box line is wrong: {bb}')
    if data.rstrip().split(b'\n')[-1] != b'%%EOF':
        problems.append('it does not end with %%EOF')
    if any(len(ln) > 255 for ln in lines):
        problems.append('a line is longer than 255 characters')
    counts = {}
    stack = []
    dicts = [{}]
    fonts = {'Symbol'}
    depth = 0
    point = False
    r = Reader(data)

    def pop(kind, op):
        if not stack:
            raise ValueError(f'{op}: the stack is empty')
        v = stack.pop()
        if kind == 'num' and not isinstance(v, float):
            raise ValueError(f'{op}: a number was wanted, not {v!r}')
        if kind == 'lit' and not isinstance(v, Lit):
            raise ValueError(f'{op}: a literal name was wanted, not {v!r}')
        if kind == 'arr' and not isinstance(v, list):
            raise ValueError(f'{op}: an array was wanted, not {v!r}')
        if kind == 'dict' and not isinstance(v, dict):
            raise ValueError(f'{op}: a dictionary was wanted, not {v!r}')
        if kind == 'str' and not isinstance(v, bytes):
            raise ValueError(f'{op}: a string was wanted, not {v!r}')
        return v

    def nums(n, op):
        return [pop('num', op) for _ in range(n)][::-1]

    def function_ok(f, op):
        t = f.get('FunctionType')
        if t == 2.0:
            if len(f.get('C0', [])) != 3 or len(f.get('C1', [])) != 3 or f.get('Domain') != [0.0, 1.0]:
                raise ValueError(f'{op}: a type 2 function needs Domain [0 1] and three components in C0 and C1')
            if any(not 0 <= v <= 1 for v in f['C0'] + f['C1']):
                raise ValueError(f'{op}: a colour component outside 0..1')
        elif t == 3.0:
            fs = f.get('Functions', [])
            if not fs or len(f.get('Bounds', [])) != len(fs) - 1 or len(f.get('Encode', [])) != 2 * len(fs):
                raise ValueError(f'{op}: a type 3 function needs n functions, n - 1 bounds and 2n encode values')
            b = [0.0] + f['Bounds'] + [1.0]
            if any(b[k] >= b[k + 1] for k in range(len(b) - 1)):
                raise ValueError(f'{op}: the bounds do not increase')
            for g in fs:
                function_ok(g, op)
        else:
            raise ValueError(f'{op}: a function of type {t}')

    def run(tok):
        nonlocal depth, point
        if isinstance(tok, (float, bytes, Lit, list, dict)) or isinstance(tok, tuple):
            stack.append(tok)
            return
        op = str(tok)
        counts[op] = counts.get(op, 0) + 1
        for dct in reversed(dicts):
            if op in dct:
                v = dct[op]
                if isinstance(v, str) and not isinstance(v, (Name, Lit)):
                    run(Name(v))           # an operator loaded under another name (/m /moveto load def)
                    return
                if isinstance(v, Proc):
                    if op == 'isofont':
                        base, new = pop('lit', op), pop('lit', op)
                        if base not in ('Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique', 'Helvetica-BoldOblique',
                                        'Courier', 'Courier-Bold', 'Courier-Oblique', 'Courier-BoldOblique'):
                            raise ValueError(f'isofont of {base}, which is not a standard font')
                        fonts.add(str(new))
                        return
                    raise ValueError(f'{op}: a procedure the checker does not know')
                stack.append(v)
                return
        if op in ('true', 'false'):
            stack.append(op == 'true')
        elif op in ('[', '<<'):
            stack.append(MARK)
        elif op == ']':
            k = len(stack) - 1 - stack[::-1].index(MARK)
            arr = stack[k + 1:]
            del stack[k:]
            stack.append(list(arr))
        elif op == '>>':
            k = len(stack) - 1 - stack[::-1].index(MARK)
            items = stack[k + 1:]
            del stack[k:]
            if len(items) % 2 or not all(isinstance(items[i], Lit) for i in range(0, len(items), 2)):
                raise ValueError('a dictionary whose keys are not names')
            stack.append({str(items[i]): items[i + 1] for i in range(0, len(items), 2)})
        elif op == '{':
            body, level = Proc(), 1
            while True:
                t = r.token()
                if t is None:
                    raise ValueError('an unclosed procedure')
                if t == '{':
                    level += 1
                elif t == '}':
                    level -= 1
                    if level == 0:
                        break
                body.append(t)
            stack.append(body)
        elif op == 'def':
            v = stack.pop()
            k = pop('lit', op)
            dicts[-1][str(k)] = v
        elif op == 'load':
            k = pop('lit', op)
            stack.append(str(k) if str(k) in ('moveto', 'lineto', 'curveto', 'closepath') else None)
        elif op == 'bind':
            if not isinstance(stack[-1], Proc):
                raise ValueError('bind: a procedure was wanted')
        elif op == 'dict':
            pop('num', op)
            stack.append({})
        elif op == 'begin':
            dicts.append(pop('dict', op))
        elif op == 'end':
            if len(dicts) < 2:
                raise ValueError('end without begin')
            dicts.pop()
        elif op == 'moveto':
            nums(2, op)
            point = True
        elif op == 'lineto':
            nums(2, op)
            if not point:
                raise ValueError('lineto with no current point')
        elif op == 'curveto':
            nums(6, op)
            if not point:
                raise ValueError('curveto with no current point')
        elif op == 'closepath':
            pass
        elif op in ('newpath', 'fill', 'eofill', 'stroke', 'clip', 'eoclip', 'strokepath'):
            if op in ('newpath', 'fill', 'eofill', 'stroke'):
                point = False
        elif op == 'gsave':
            depth += 1
        elif op == 'grestore':
            depth -= 1
            if depth < 0:
                raise ValueError('grestore without gsave')
        elif op == 'setrgbcolor':
            if any(not 0 <= v <= 1 for v in nums(3, op)):
                raise ValueError('setrgbcolor: a component outside 0..1')
        elif op in ('setlinewidth', 'setmiterlimit'):
            v = nums(1, op)[0]
            if v < (1 if op == 'setmiterlimit' else 0):
                raise ValueError(f'{op}: {v}')
        elif op in ('setlinecap', 'setlinejoin'):
            if nums(1, op)[0] not in (0.0, 1.0, 2.0):
                raise ValueError(f'{op}: not 0, 1 or 2')
        elif op == 'setdash':
            pop('num', op)
            a = pop('arr', op)
            if any(not isinstance(v, float) or v < 0 for v in a):
                raise ValueError('setdash: the dashes must be numbers of no less than 0')
        elif op in ('translate', 'scale'):
            nums(2, op)
        elif op == 'concat':
            m = pop('arr', op)
            if len(m) != 6 or not all(isinstance(v, float) for v in m):
                raise ValueError('concat: a matrix of six numbers was wanted')
        elif op == 'selectfont':
            pop('num', op)
            f = pop('lit', op)
            if str(f) not in fonts:
                raise ValueError(f'selectfont: the font {f} is not defined')
        elif op == 'show':
            pop('str', op)
            if not point:
                raise ValueError('show with no current point')
        elif op == 'setcolorspace':
            if pop('lit', op) != 'DeviceRGB':
                raise ValueError('setcolorspace: DeviceRGB was wanted')
        elif op == 'currentfile':
            stack.append(('file',))
        elif op == 'filter':
            name = pop('lit', op)
            src = stack.pop()
            if not (isinstance(src, tuple) and src[0] == 'file'):
                raise ValueError('filter: the source is not the file')
            stack.append(src + (str(name),))
        elif op == 'image':
            dct = pop('dict', op)
            w, h = int(dct.get('Width', 0)), int(dct.get('Height', 0))
            if dct.get('ImageType') not in (1.0, 4.0) or dct.get('BitsPerComponent') != 8.0 or w < 1 or h < 1:
                raise ValueError('image: ImageType 1 or 4, BitsPerComponent 8 and a size were wanted')
            if len(dct.get('Decode', [])) != 6 or len(dct.get('ImageMatrix', [])) != 6:
                raise ValueError('image: Decode and ImageMatrix of six numbers were wanted')
            if dct['ImageType'] == 4.0 and len(dct.get('MaskColor', [])) != 6:
                raise ValueError('image: an ImageType 4 needs a MaskColor of six numbers')
            src = dct.get('DataSource')
            if not (isinstance(src, tuple) and src[0] == 'file'):
                raise ValueError('image: the data was wanted from the file')
            filters = src[1:]
            if filters == ('ASCII85Decode', 'FlateDecode'):
                raw = zlib.decompress(ascii85(r.raw_until(b'~>')))
            elif filters == ('ASCIIHexDecode',):
                raw = bytes.fromhex(re.sub(rb'\s', b'', r.raw_until(b'>')).decode())
            else:
                raise ValueError(f'image: filters {filters}')
            if len(raw) != w * h * 3:
                raise ValueError(f'image: {len(raw)} bytes of data, {w * h * 3} wanted')
        elif op == 'shfill':
            dct = pop('dict', op)
            if dct.get('ShadingType') != 2.0 or dct.get('ColorSpace') != 'DeviceRGB' or len(dct.get('Coords', [])) != 4:
                raise ValueError('shfill: an axial shading in DeviceRGB with four coordinates was wanted')
            function_ok(dct.get('Function', {}), op)
        elif op == 'showpage':
            pass
        else:
            raise ValueError(f'an operator the checker does not know: {op}')

    try:
        while True:
            t = r.token()
            if t is None:
                break
            run(t)
        if depth:
            problems.append(f'{depth} gsave without grestore')
        if len(dicts) != 1 or 'm' not in dicts[0].get('PyLABDict', {}):
            problems.append('the dictionaries begun are not all ended, or the prolog is missing')
        if stack:
            problems.append(f'left on the stack: {stack[:5]}')
    except (ValueError, IndexError, KeyError, zlib.error) as e:
        problems.append(f'{e} (near byte {r.i})')
    return problems, counts
