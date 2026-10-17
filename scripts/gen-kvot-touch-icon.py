#!/usr/bin/env python3
"""Emit resources/images/kvot-icon-180.png: the kvot mark
(resources/images/kvot-logotype.svg) on the dark plate, at 180 px, as the
touch icon that an iPhone puts on its home screen for a page with no icon of
its own - the pages whose tab shows favicon.ico, the same mark.

    python3 scripts/gen-kvot-touch-icon.py

Drawn as the pages' own touch icons are (scripts/kvot_icon.py): the square
136 px wide on a 180 px plate of #352921, then checked for being the mark.
"""
import sys

import kvot_icon as K

MARK = K.ROOT / 'resources/images/kvot-logotype.svg'
PNG180 = K.ROOT / 'resources/images/kvot-icon-180.png'


def main():
    if not K.Path(K.CHROME).exists():
        sys.exit(f'no Chrome at {K.CHROME} (set CHROME); the PNG was not drawn')
    pad = (180 - K.TOUCH_DRAWN) // 2
    K.rasterise(f'<!doctype html><body style="margin:0;background:{K.TOUCH_PLATE}">'
                f'<img src="{MARK.as_uri()}" width="{K.TOUCH_DRAWN}" height="{K.TOUCH_DRAWN}" '
                f'style="display:block;margin:{pad}px">', PNG180, 180, 180)
    # The mark's three tones are about nine per cent each: at least half that.
    bad = K.looks_drawn(PNG180, 180, {K.TOP: 0.045, K.RIGHT: 0.045, K.LEFT: 0.045})
    if bad:
        sys.exit(bad)
    print(f'wrote {PNG180.relative_to(K.ROOT)}')


if __name__ == '__main__':
    main()
