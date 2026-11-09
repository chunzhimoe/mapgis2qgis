"""Pure-Python reader for native MapGIS 6.x work files (.wt/.wl/.wp/.mpj) and a
standard-library Shapefile writer. No MapGIS installation, GDAL or pyshp needed.

Verified against MapGIS's own exporter (w60_conv.dll ``_ShapeOut``) on 680 real
files / 307 510 features: identical feature order, coordinates and attribute values.
Deliberate differences, all where ``_ShapeOut`` loses or corrupts data:

* its DBF has one stray byte per deleted element, shifting every later record;
  this writer produces a valid DBF;
* over-wide numbers are truncated by ``_ShapeOut`` (220 in a width-2 field -> "22");
  here such numeric fields are widened;
* layers without an attribute table get a header-only DBF from ``_ShapeOut``;
  here they get an empty ``ID`` column with one row per feature;
* polygon rings are nested by containment and oriented per the Shapefile
  specification (MapGIS ring order is not reliable); identical duplicate rings
  are dropped.

On-disk layout used (all little-endian, strings GB18030):

* header: magic ``WMAP`` with byte[4] == 0x60 (6.x), byte[7] '1' line / '2' point /
  '3' region; @12 int32 offset of a 10-entry (start, size) section table;
  @109 projection type, @110 ellipsoid, @143 float64 scale, @151 packed DDDMMSS
  central meridian; projected coordinates are stored in paper millimetres;
* every section begins with a dummy slot 0; a slot is live when its first byte
  is 1 (point 93-byte records, line/arc 57-byte records, region 40-byte records);
* region record: @1 int32 n, @5 int32 offset into section 1 of n int32
  ``[hint, +/-arc, ..., 0, +/-arc, ...]`` (0 separates rings, negative = reversed);
* attribute blob (section 2; regions section 9): @12 int32 record-table offset;
  second ``\\x60D`` block: int16 nfields, int32 slots, int32 record length,
  39-byte field descriptors from +28 (name[20], type@20 0 str / 3 int32 /
  5 float64, offset@21, length@25, width@27, decimals@29); record i belongs to
  element slot i.
"""
import datetime
import decimal
import math
import os
from pathlib import Path
import re
import struct

from .errors import NativeFormatError
from .native_crs import decode_dms, read_header_parameters

__all__ = ['NativeField', 'NativeLayer', 'read_native_layer', 'organize_rings', 'scale_features',
           'write_shapefile', 'read_mpj_paths', 'native_files', 'convert_native_file',
           'KIND_SUFFIX', 'EXT_KIND']

ENC = 'gb18030'
KIND = {0x31: 'LINE', 0x32: 'POINT', 0x33: 'REGION'}
KIND_SUFFIX = {'POINT': '点', 'LINE': '线', 'REGION': '区'}
EXT_KIND = {'.WT': 'POINT', '.WL': 'LINE', '.WP': 'REGION'}
SHP_TYPE = {'POINT': 1, 'LINE': 3, 'REGION': 5}
POINT_TYPE_NAME = {0: '注释', 1: '子图', 2: '圆', 3: '弧', 4: '版面'}
MEASURE_FIELDS = {'长度': 1, '周长': 1, '面积': 2}


def _dec(raw):
    return raw.split(b'\0', 1)[0].decode(ENC, 'surrogateescape')


class NativeField:
    """DBF-oriented field description: kind 'C' (text) or 'N' (number)."""

    def __init__(self, name, kind, width, decimals=0):
        self.name, self.kind, self.width, self.decimals = name, kind, width, decimals

    def __repr__(self):
        return 'NativeField(%r, %r, %d, %d)' % (self.name, self.kind, self.width, self.decimals)


class NativeLayer:
    """A MapGIS 6.x work file decoded to its live features.

    ``features`` is a list of ``(geometry, values)``; geometry is ``(x, y)`` for
    points, ``[(x, y), ...]`` for lines, ``[ring, ...]`` for regions (MapGIS order,
    see :func:`organize_rings`) or None. Coordinates are stored units (paper mm
    for projected maps). With ``style=True`` symbol columns are appended
    (points: 点类型/注记/子图号/颜色, lines: 线型/线颜色/线宽, regions: 填充色/图案号).
    """

    def __init__(self, path, style=True):
        self.path = str(path)
        self.raw = b = Path(path).read_bytes()
        if len(b) < 340 or b[:4] != b'WMAP' or b[4] != 0x60 or b[7] not in KIND:
            raise NativeFormatError('Not a MapGIS 6.x point/line/region file: ' + self.path)
        self.kind = KIND[b[7]]
        try:
            ds = struct.unpack_from('<i', b, 12)[0]
            self.sections = [struct.unpack_from('<2i', b, ds + 10 * i) for i in range(10)]
            self.proj_type, self.ellipsoid = b[109], b[110]
            self.header_parameters = read_header_parameters(b)
            self.scale = struct.unpack_from('<d', b, 143)[0]
            self.header_factor = (self.scale / 1000.0 if self.proj_type in (2, 3, 5) else 1.0) \
                if math.isfinite(self.scale) and self.scale > 0 else 1.0
            self.header_cm = self.header_parameters['central_meridian'] if self.proj_type in (2, 3, 5) else None
            self.fields, attrs = self._read_attributes()
            if not self.fields:
                self.fields = [NativeField('ID', 'N', 8)]
            n_attr = len(self.fields)
            reader = {'POINT': self._points, 'LINE': self._lines, 'REGION': self._regions}[self.kind]
            self.slots, geoms, styles, style_fields = reader()
        except (struct.error, IndexError) as exc:
            raise NativeFormatError('Truncated or damaged MapGIS file: %s (%s)' % (self.path, exc)) from exc
        if style:
            names = {f.name for f in self.fields}
            for f in style_fields:
                name = f.name
                while name in names:
                    name += '_'
                names.add(name)
                self.fields.append(NativeField(name, f.kind, f.width, f.decimals))
        self.features = []
        for slot, g, st in zip(self.slots, geoms, styles):
            values = list(attrs[slot]) if slot < len(attrs) else [None] * n_attr
            self.features.append((g, values + list(st) if style else values))

    def _read_attributes(self):
        s, v = self.sections[9 if self.kind == 'REGION' else 2]
        a = self.raw[s:s + v]
        if v < 32 or a[:2] != b'\x60\x44':
            return [], []
        rec_start = struct.unpack_from('<i', a, 12)[0]
        ft = a.find(b'\x60\x44', 2)
        if ft < 0:
            return [], []
        nf, slots, rlen = struct.unpack_from('<hii', a, ft + 2)
        descs, fields = [], []
        for k in range(nf):
            d = a[ft + 28 + 39 * k: ft + 28 + 39 * (k + 1)]
            typ, off = d[20], struct.unpack_from('<i', d, 21)[0]
            length, width = struct.unpack_from('<hh', d, 25)
            descs.append((typ, off, length))
            name = _dec(d[:20])
            if typ in (5, 4):
                fields.append(NativeField(name, 'N', min(width, 20), min(d[29], 15)))
            elif typ in (1, 2, 3):
                fields.append(NativeField(name, 'N', min(width, 20), 0))
            else:
                fields.append(NativeField(name, 'C', max(1, min(width, 254))))
        records = []
        for i in range(slots):
            r = a[rec_start + rlen * i: rec_start + rlen * (i + 1)]
            values = []
            for typ, off, length in descs:
                raw = r[off:off + length]
                if len(raw) < length:
                    values.append(None)
                elif typ == 0:
                    values.append(_dec(raw))
                elif typ == 3 and length == 4:
                    values.append(struct.unpack('<i', raw)[0])
                elif typ == 2 and length == 2:
                    values.append(struct.unpack('<h', raw)[0])
                elif typ == 1 and length == 1:
                    values.append(raw[0])
                elif typ in (4, 5) and length in (4, 8):
                    values.append(struct.unpack('<f' if length == 4 else '<d', raw)[0])
                else:
                    values.append(raw.hex())
            records.append(values)
        return fields, records

    def _live(self, sec, size):
        s, v = self.sections[sec]
        b = self.raw
        return [i for i in range(1, v // size) if b[s + size * i] == 1], s

    def _xy(self, off, n):
        c = struct.unpack_from('<%dd' % (2 * n), self.raw, self.sections[1][0] + off)
        return list(zip(c[0::2], c[1::2]))

    def _arc(self, o):
        n, off = struct.unpack_from('<2i', self.raw, o + 10)
        return self._xy(off, n)

    def _points(self):
        slots, s = self._live(0, 93)
        b, cs = self.raw, self.sections[1][0]
        geoms, styles = [], []
        for i in slots:
            o = s + 93 * i
            ptype = b[o + 32]
            text = sub = None
            if ptype == 0:
                n, off = struct.unpack_from('<hi', b, o + 1)
                text = _dec(b[cs + off: cs + off + n])
            elif ptype == 1:
                sub = struct.unpack_from('<i', b, o + 34)[0]
            geoms.append(struct.unpack_from('<2d', b, o + 7))
            styles.append((POINT_TYPE_NAME.get(ptype, str(ptype)), text, sub,
                           struct.unpack_from('<i', b, o + 84)[0]))
        return slots, geoms, styles, [NativeField('点类型', 'C', 8), NativeField('注记', 'C', 254),
                                      NativeField('子图号', 'N', 10), NativeField('颜色', 'N', 10)]

    def _lines(self):
        slots, s = self._live(0, 57)
        b = self.raw
        geoms, styles = [], []
        for i in slots:
            o = s + 57 * i
            geoms.append(self._arc(o))
            color = struct.unpack_from('<i', b, o + 24)[0]
            styles.append((struct.unpack_from('<h', b, o + 20)[0],
                           (color >> 16) if abs(color) >= 65536 else color,
                           round(struct.unpack_from('<f', b, o + 30)[0], 4)))
        return slots, geoms, styles, [NativeField('线型', 'N', 6), NativeField('线颜色', 'N', 10),
                                      NativeField('线宽', 'N', 12, 4)]

    def _regions(self):
        slots, s = self._live(8, 40)
        a0, narcs = self.sections[0][0], self.sections[0][1] // 57
        b, cs = self.raw, self.sections[1][0]
        geoms, styles, topo = [], [], None
        for i in slots:
            o = s + 40 * i
            n, off = struct.unpack_from('<2i', b, o + 1)
            if n > 0:
                ids = struct.unpack_from('<%di' % n, b, cs + off)[1:]
            else:   # no arc list (some generated files): derive rings from arc topology
                topo = self._topology_arcs() if topo is None else topo
                ids = topo.get(i, ())
            rings, ring = [], []
            for aid in list(ids) + [0]:
                if aid == 0:
                    if len(ring) >= 2:   # keep degenerate rings (a lone 2-point arc) like MapGIS
                        if ring[0] != ring[-1]:
                            ring.append(ring[0])
                        rings.append(ring)
                    ring = []
                    continue
                if abs(aid) >= narcs:
                    continue
                pts = self._arc(a0 + 57 * abs(aid))
                if aid < 0:
                    pts.reverse()
                ring.extend(pts[1:] if ring and pts and ring[-1] == pts[0] else pts)
            geoms.append(rings or None)
            styles.append((struct.unpack_from('<i', b, o + 9)[0], struct.unpack_from('<h', b, o + 13)[0]))
        return slots, geoms, styles, [NativeField('填充色', 'N', 10), NativeField('图案号', 'N', 6)]

    def _topology_arcs(self):
        """Region slot -> signed arc ids chained into rings (0-separated), from the 24-byte
        arc topology records (right region = forward, left region = reversed)."""
        ts, tv = self.sections[3]
        a0, b = self.sections[0][0], self.raw
        by_region = {}
        for j in range(1, tv // 24):
            right, left = struct.unpack_from('<2i', b, ts + 24 * j + 8)
            if b[a0 + 57 * j] != 1:
                continue
            for region, sign in ((right, 1), (left, -1)):
                if region > 0 and right != left:
                    by_region.setdefault(region, []).append(sign * j)
        out = {}
        for region, arcs in by_region.items():
            ends = {}
            for aid in arcs:
                pts = self._arc(a0 + 57 * abs(aid))
                if pts:
                    ends[aid] = (pts[0], pts[-1]) if aid > 0 else (pts[-1], pts[0])
            todo, seq = [a for a in arcs if a in ends], []
            while todo:
                current = todo.pop(0)
                start, end = ends[current]
                seq.append(current)
                while end != start:
                    nxt = next((a for a in todo if ends[a][0] == end), None)
                    if nxt is None:
                        break
                    todo.remove(nxt)
                    seq.append(nxt)
                    end = ends[nxt][1]
                seq.append(0)
            out[region] = tuple(seq)
        return out


def read_native_layer(path, style=True):
    """Decode a .wt/.wl/.wp file (live elements only)."""
    return NativeLayer(path, style=style)


def _area2(r):
    return sum(r[k][0] * r[k + 1][1] - r[k + 1][0] * r[k][1] for k in range(len(r) - 1))


def _inside(point, ring):
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _ring_in(inner, outer):
    step = max(1, (len(inner) - 1) // 7)
    pts = inner[:-1:step][:7] or inner[:1]
    return sum(_inside(p, outer) for p in pts) * 2 > len(pts)


def organize_rings(rings):
    """Nest rings by containment: depth 0/2/4... outer, 1/3/... hole. Returns rings in
    Shapefile order and orientation (outer clockwise, each followed by its holes)."""
    if len(rings) > 1:
        seen, unique = set(), []
        for r in rings:
            key = (len(r), frozenset(r))
            if key not in seen:
                seen.add(key)
                unique.append(r)
        rings = unique
    if len(rings) == 1:
        r = rings[0]
        return [r if _area2(r) < 0 else r[::-1]]
    order = sorted(range(len(rings)), key=lambda k: -abs(_area2(rings[k])))
    parent, depth = {}, {}
    for pos, k in enumerate(order):
        parent[k] = next((j for j in reversed(order[:pos]) if _ring_in(rings[k], rings[j])), None)
        depth[k] = 0 if parent[k] is None else depth[parent[k]] + 1
    out = []
    for k in order:
        if depth[k] % 2:
            continue
        out.append(rings[k] if _area2(rings[k]) < 0 else rings[k][::-1])
        for h in order:
            if parent[h] == k and depth[h] % 2:
                out.append(rings[h] if _area2(rings[h]) > 0 else rings[h][::-1])
    return out


def scale_features(layer, factor, scale_measures=True):
    """Features with coordinates x factor; 长度/周长 x factor and 面积 x factor^2."""
    def scaled(g):
        if g is None:
            return None
        if layer.kind == 'POINT':
            return (g[0] * factor, g[1] * factor)
        if layer.kind == 'LINE':
            return [(x * factor, y * factor) for x, y in g]
        return [[(x * factor, y * factor) for x, y in r] for r in g]
    mult = [factor ** MEASURE_FIELDS[f.name] if scale_measures and f.name in MEASURE_FIELDS else None
            for f in layer.fields]
    return [(scaled(g), [v * m if m and isinstance(v, (int, float)) else v for v, m in zip(values, mult)])
            for g, values in layer.features]


_CRT17 = decimal.Context(prec=17, rounding=decimal.ROUND_HALF_UP)


def _number(v, decimals):
    """Format like MapGIS (MS CRT): 17 significant digits, then half away from zero."""
    q = decimal.Decimal(1).scaleb(-decimals)
    d = _CRT17.create_decimal(float(v)).quantize(q, rounding=decimal.ROUND_HALF_UP)
    return '%d' % d if decimals == 0 else '{:f}'.format(d)


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and not math.isinf(v)


def _fit_fields(fields, features):
    """Widen numeric fields whose values do not fit (max DBF N width 20)."""
    out = []
    for i, f in enumerate(fields):
        if f.kind != 'N':
            out.append(f)
            continue
        need = max([len(_number(values[i], f.decimals)) for _, values in features
                    if _finite(values[i])] or [0])
        if need <= f.width:
            out.append(f)
        else:
            width = min(need, 20)
            out.append(NativeField(f.name, 'N', width, max(0, f.decimals - (need - width))))
    return out


def _cut(raw, limit):
    raw = raw[:limit]
    while raw:
        try:
            raw.decode(ENC)
            return raw
        except UnicodeDecodeError:
            raw = raw[:-1]
    return raw


def _format(v, f):
    if f.kind == 'C':
        raw = b'' if v is None else str(v).encode(ENC, 'surrogateescape')
        return _cut(raw, f.width).ljust(f.width, b' ')
    if not _finite(v):
        return b' ' * f.width
    s = _number(v, f.decimals)
    if len(s) > f.width and f.decimals:
        s = _number(v, max(0, f.decimals - (len(s) - f.width)))
    return (s if len(s) <= f.width else '*' * f.width).rjust(f.width).encode('ascii')


def _dbf_names(fields):
    seen, out = set(), []
    for f in fields:
        raw = base = _cut(f.name.encode(ENC, 'surrogateescape'), 10) or b'FIELD'
        k = 1
        while raw.upper() in seen:
            tag = str(k).encode()
            raw = _cut(base, 10 - len(tag)) + tag
            k += 1
        seen.add(raw.upper())
        out.append(raw)
    return out


def write_shapefile(base, kind, fields, features, prj=None, encoding_tag='GBK'):
    """Write base.shp/.shx/.dbf/.cpg (+ .prj). Geometry None -> null shape. Returns the
    DBF field definitions actually written (numeric fields may have been widened)."""
    base = str(base)
    stype = SHP_TYPE[kind]
    records, xs, ys = [], [], []
    for g, _ in features:
        if g is None or (kind != 'POINT' and not g):
            records.append(struct.pack('<i', 0))
            continue
        if kind == 'POINT':
            xs.append(g[0])
            ys.append(g[1])
            records.append(struct.pack('<i2d', 1, g[0], g[1]))
            continue
        parts = organize_rings(g) if kind == 'REGION' else [g]
        pts = [p for part in parts for p in part]
        px, py = [p[0] for p in pts], [p[1] for p in pts]
        xs += px
        ys += py
        index, total = [], 0
        for part in parts:
            index.append(total)
            total += len(part)
        records.append(struct.pack('<i4d2i', stype, min(px), min(py), max(px), max(py), len(parts), len(pts))
                       + struct.pack('<%di' % len(index), *index)
                       + struct.pack('<%dd' % (2 * len(pts)), *[c for p in pts for c in p]))
    bbox = (min(xs), min(ys), max(xs), max(ys)) if xs else (0.0, 0.0, 0.0, 0.0)

    def header(length):
        return struct.pack('>7i', 9994, 0, 0, 0, 0, 0, length // 2) + \
            struct.pack('<2i8d', 1000, stype, *bbox, 0, 0, 0, 0)

    with open(base + '.shp', 'wb') as shp, open(base + '.shx', 'wb') as shx:
        shp.write(header(100 + sum(8 + len(r) for r in records)))
        shx.write(header(100 + 8 * len(records)))
        offset = 100
        for number, r in enumerate(records, 1):
            shp.write(struct.pack('>2i', number, len(r) // 2) + r)
            shx.write(struct.pack('>2i', offset // 2, len(r) // 2))
            offset += 8 + len(r)
    fields = _fit_fields(fields, features)
    names = _dbf_names(fields)
    today = datetime.date.today()
    with open(base + '.dbf', 'wb') as dbf:
        dbf.write(struct.pack('<4BIHH20x', 3, today.year - 1900, today.month, today.day, len(features),
                              32 + 32 * len(fields) + 1, 1 + sum(f.width for f in fields)))
        for name, f in zip(names, fields):
            dbf.write(struct.pack('<11sc4xBB14x', name, f.kind.encode(), f.width, f.decimals))
        dbf.write(b'\r')
        for _, values in features:
            dbf.write(b' ' + b''.join(_format(v, f) for v, f in zip(values, fields)))
        dbf.write(b'\x1a')
    Path(base + '.cpg').write_text(encoding_tag, encoding='ascii')
    if prj:
        Path(base + '.prj').write_text(prj, encoding='ascii')
    return fields


def read_mpj_paths(path):
    """Layer file paths of a MapGIS project (.mpj), resolved against its folder."""
    raw = Path(path).read_bytes()
    if raw[:4] != b'WMAP' or raw[7:8] != b':':
        raise NativeFormatError('Not a MapGIS project file: ' + str(path))
    count = struct.unpack_from('<H', raw, 12)[0]
    start = None
    for m in re.finditer(rb'(?:[A-Za-z]:\\|\\|\.\\)[^\x00]{2,250}', raw):
        if _dec(m.group()).lower().endswith(('.wt', '.wl', '.wp', '.wn')):
            start = m.start() - 2
            break
    if start is None:
        raise NativeFormatError('No layer paths in project file: ' + str(path))
    base, out = Path(path).resolve().parent, []
    for i in range(count):
        record = raw[start + 400 * i: start + 400 * (i + 1)]
        if len(record) < 400:
            break
        name = _dec(record[2:252])
        out.append(Path(name) if len(name) > 1 and name[1] == ':' else (base / name.replace('\\', os.sep)))
    return [Path(os.path.normpath(str(p))) for p in out]


def native_files(source):
    """-> (name, [work files], [missing project layers]) for a folder, .mpj or single file."""
    source = Path(source)
    if source.is_file() and source.suffix.lower() == '.mpj':
        paths = read_mpj_paths(source)
        return source.stem, [p for p in paths if p.is_file() and p.suffix.upper() in EXT_KIND], \
            [str(p) for p in paths if not p.is_file()]
    if source.is_file():
        return source.stem, [source], []
    if not source.is_dir():
        raise NativeFormatError('No such MapGIS source: ' + str(source))
    files = sorted(p for p in source.rglob('*') if p.is_file() and p.suffix.upper() in EXT_KIND)
    return source.name, files, []


def convert_native_file(source, base, factor=None, prj=None, style=True):
    """Convert one work file; factor multiplies coordinates (None = stored units)."""
    layer = read_native_layer(source, style=style)
    features = scale_features(layer, factor) if factor and factor != 1 else layer.features
    fields = write_shapefile(base, layer.kind, layer.fields, features, prj=prj)
    return {'source': str(source), 'kind': layer.kind, 'features': len(features),
            'null': sum(1 for g, _ in features if g is None), 'fields': [f.name for f in fields]}
