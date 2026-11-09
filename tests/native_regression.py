"""Real-data regression: native .wt/.wl/.wp conversion vs MapGIS's own _ShapeOut export.

Usage: python tests/native_regression.py SOURCE_DIR SHAPEOUT_DIR
SHAPEOUT_DIR holds <stem>_点|线|区.shp exported by MapGIS (w60_conv ``_ShapeOut``) from
the same files. No data are bundled. _ShapeOut writes one stray DBF byte per non-live
element slot (slot 0's byte at the end); records are realigned before comparing.
Geometry is compared vertex by vertex after removing consecutive duplicates (MapGIS keeps
arc-junction duplicates) and ignoring ring start/orientation/order.
"""
import argparse
import json
from pathlib import Path
import struct
import sys
import tempfile

from mapgis_annotations.mapgis_native import (EXT_KIND, KIND_SUFFIX, _CRT17, read_native_layer,
                                              write_shapefile)


def read_shp(base):
    d, x = Path(str(base) + '.shp').read_bytes(), Path(str(base) + '.shx').read_bytes()
    out = []
    for k in range((len(x) - 100) // 8):
        off = struct.unpack_from('>i', x, 100 + 8 * k)[0] * 2 + 8
        t = struct.unpack_from('<i', d, off)[0]
        if t == 0:
            out.append(None)
        elif t == 1:
            out.append([[struct.unpack_from('<2d', d, off + 4)]])
        else:
            parts, n = struct.unpack_from('<2i', d, off + 36)
            if n <= 0:
                out.append(None)
                continue
            index = list(struct.unpack_from('<%di' % parts, d, off + 44)) + [n]
            xy = struct.unpack_from('<%dd' % (2 * n), d, off + 44 + 4 * parts)
            pts = list(zip(xy[0::2], xy[1::2]))
            out.append([pts[index[j]:index[j + 1]] for j in range(parts)])
    return out


def dbf_rows(path, live=None, slots=None):
    d = Path(path).read_bytes()
    n, header, length = struct.unpack_from('<IHH', d, 4)
    fields, o, pos = [], 32, 1
    while d[o] != 0x0D:
        fields.append((d[o + 16], pos))
        pos += d[o + 16]
        o += 32
    if live is None:
        starts = [header + i * length for i in range(n)]
    else:
        starts, p, alive = [], header, set(live)
        for slot in range(1, slots):
            if slot in alive:
                starts.append(p)
                p += length
            else:
                p += 1
    return n, [[d[s + q: s + q + w].strip(b' \x00') for w, q in fields] for s in starts]


def ring_key(r):
    r = [p for j, p in enumerate(r) if j == 0 or p != r[j - 1]]
    if len(r) > 1 and r[0] == r[-1]:
        r = r[:-1]
    if not r:
        return ()
    low = min(r)
    return min(tuple(s[k:] + s[:k]) for s in (r, r[::-1]) for k, p in enumerate(s) if p == low)


def geom_key(g, kind):
    if g is None:
        return None
    if kind == 'POINT':
        return tuple(g[0][0])
    if kind == 'LINE':
        return tuple(p for j, p in enumerate(g[0]) if j == 0 or p != g[0][j - 1])
    return tuple(sorted(set(ring_key(r) for r in g)))


def same_number(a, b, decimals):
    try:
        return abs(float(a) - float(b)) <= 10 ** -decimals / 2 + 1e-9 * max(1, abs(float(a)))
    except ValueError:
        return False


def compare(source, reference):
    work = Path(tempfile.mkdtemp())
    totals = {'files': 0, 'features': 0, 'identical_files': 0, 'shapeout_truncated_values': 0,
              'shapeout_header_only_dbf': 0}
    problems = []
    for path in sorted(p for p in Path(source).rglob('*') if p.suffix.upper() in EXT_KIND):
        layer = read_native_layer(path, style=False)
        name = '%s_%s' % (path.stem, KIND_SUFFIX[layer.kind])
        prefix = '_'.join(path.relative_to(source).parent.parts)
        candidates = [Path(reference) / name] + ([Path(reference) / (prefix + '_' + name)] if prefix else [])
        ref = next((c for c in candidates if Path(str(c) + '.shp').exists()), None)
        if ref is None:
            continue
        write_shapefile(work / name, layer.kind, layer.fields, layer.features)
        issues = []
        mine, theirs = read_shp(work / name), read_shp(ref)
        if len(mine) != len(theirs):
            issues.append('feature count %d vs %d' % (len(mine), len(theirs)))
        bad = sum(geom_key(a, layer.kind) != geom_key(b, layer.kind) for a, b in zip(mine, theirs))
        if bad:
            issues.append('geometry differs: %d' % bad)
        size, sec = {'POINT': (93, 0), 'LINE': (57, 0), 'REGION': (40, 8)}[layer.kind]
        n_ref, ref_rows = dbf_rows(str(ref) + '.dbf', layer.slots, layer.sections[sec][1] // size)
        if n_ref == 0 and layer.features:
            totals['shapeout_header_only_dbf'] += 1
        else:
            _, my_rows = dbf_rows(work / (name + '.dbf'))
            for x, y in zip(my_rows, ref_rows):
                for a, b, f in zip(x, y, layer.fields):
                    if a == b or same_number(a, b, f.decimals):
                        continue
                    if len(a) > f.width and a[:f.width] == b:
                        totals['shapeout_truncated_values'] += 1
                    else:
                        issues.append('value %r vs %r in %s' % (a, b, f.name))
                        break
        totals['files'] += 1
        totals['features'] += len(layer.features)
        totals['identical_files'] += not issues
        if issues:
            problems.append({'file': str(path), 'issues': issues[:5]})
    return {'status': 'PASS' if not problems else 'FAIL', **totals, 'problems': problems}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('shapeout', type=Path)
    args = parser.parse_args()
    result = compare(args.source, args.shapeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
