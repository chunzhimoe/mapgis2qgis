"""Estimate one map-unit text height per layer from fixed annotation anchors."""
from collections import defaultdict
import html
import math
import re
import unicodedata

from .errors import AnnotationError


def _aspect(text):
    plain = html.unescape(re.sub(r'<[^>]*>', '', str(text))).strip()
    width = sum(0 if unicodedata.combining(c) else
                1.0 if unicodedata.east_asian_width(c) in ('W','F') else 0.6 for c in plain)
    return max(0.6, width), bool(plain)


def estimate_font_size(labels, maximum):
    """Shrink a user size ceiling using nearby labels, without moving/hiding them.

    Inputs use destination map coordinates. A bounded spatial grid and at most
    2,000 queries avoid a quadratic all-pairs scan. This is a layout estimate;
    coincident anchors and unusually crowded groups may still overlap.
    """
    if not math.isfinite(maximum) or maximum <= 0:
        raise AnnotationError('Automatic font size needs a finite positive ceiling')
    items = []
    for x, y, text in labels:
        aspect, visible = _aspect(text)
        if visible:
            if not math.isfinite(x) or not math.isfinite(y):
                raise AnnotationError('Automatic font size needs finite label coordinates')
            items.append((x,y,aspect))
    report = {'font_size':maximum, 'font_unit':'map', 'labels':len(items), 'samples':0,
              'duplicate_anchors':len(items)-len({(x,y) for x,y,_ in items}),
              'method':'anchor-spacing-p35', 'estimated':False}
    if len(items) < 2:
        return report
    left, bottom = min(p[0] for p in items), min(p[1] for p in items)
    span = max(max(p[0] for p in items)-left, max(p[1] for p in items)-bottom)
    if span <= 0:
        return report
    cell = span / max(1, math.sqrt(len(items)))
    grid = defaultdict(list)
    def key(x,y):
        return math.floor((x-left)/cell), math.floor((y-bottom)/cell)
    for i, (x,y,_) in enumerate(items):
        bucket = grid[key(x,y)]
        if len(bucket) < 128:
            bucket.append(i)
    limits = []
    step = max(1, math.ceil(len(items)/2000))
    for i in range(0, len(items), step):
        x,y,width = items[i]
        gx,gy = key(x,y)
        candidates = []
        for cx in range(gx-1,gx+2):
            for cy in range(gy-1,gy+2):
                for j in grid.get((cx,cy), ()):
                    if j != i:
                        ox,oy,other_width = items[j]
                        dx,dy = ox-x,oy-y
                        if dx or dy:
                            candidates.append((dx*dx+dy*dy,dx,dy,other_width))
        nearby = sorted(candidates)[:4]
        if nearby:
            # Left-aligned boxes: the left label's width constrains horizontal
            # separation; a different row can instead separate them vertically.
            limit = min(max(abs(dx)/(width if dx >= 0 else other_width), abs(dy)/1.2)
                        for _,dx,dy,other_width in nearby)
            limits.append(limit*.82)
    if limits:
        limits.sort()
        chosen = limits[math.floor((len(limits)-1)*.35)]
        report.update(font_size=min(maximum, max(chosen, span*1e-12)),
                      samples=len(limits), estimated=True)
    return report
