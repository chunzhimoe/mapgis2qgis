"""Build small synthetic MapGIS 6.x work/project files (no real map data is shipped).

Byte layout follows mapgis_annotations.mapgis_native; slot 0 of every section is a dummy.
"""
import struct
from pathlib import Path

DATA_START = 400


def _packed_dms(deg):
    d = int(deg)
    m = int(round((deg - d) * 60))
    return float(d * 10000 + m * 100)


def _attribute_blob(fields, records):
    """fields: [(name, type, length, width, decimals)], type 0 str / 3 int32 / 5 float64.
    records: one value list per slot (slot 0 included)."""
    offsets, pos = [], 1
    for f in fields:
        offsets.append(pos)
        pos += f[2]
    rlen = pos
    rec_start = 348 + 39 * len(fields)
    head = bytearray(348)
    head[0:2] = b'\x60\x44'
    struct.pack_into('<ii', head, 12, rec_start, len(records))
    head[320:322] = b'\x60\x44'
    struct.pack_into('<hii', head, 322, len(fields), len(records), rlen)
    out = bytearray(head)
    for (name, typ, length, width, dec), off in zip(fields, offsets):
        d = bytearray(39)
        raw = name.encode('gb18030')
        d[0:len(raw)] = raw
        d[20] = typ
        struct.pack_into('<ihh', d, 21, off, length, width)
        d[29] = dec
        out += d
    for values in records:
        r = bytearray(rlen)
        r[0] = 1
        for (name, typ, length, width, dec), off, v in zip(fields, offsets, values):
            if v is None:
                continue
            if typ == 0:
                raw = v.encode('gb18030')[:length - 1]
                r[off:off + len(raw)] = raw
            elif typ == 3:
                struct.pack_into('<i', r, off, v)
            elif typ == 5:
                struct.pack_into('<d', r, off, v)
        out += r
    return bytes(out)


def _file(type_char, sections, proj=5, ellipsoid=1, scale=250000.0, cm=105.0):
    header = bytearray(DATA_START + 120)
    header[0:4] = b'WMAP'
    header[4] = 0x60
    header[5:7] = b'D2'
    header[7] = ord(type_char)
    struct.pack_into('<i', header, 12, DATA_START)
    header[109] = proj
    header[110] = ellipsoid
    struct.pack_into('<d', header, 143, scale)
    struct.pack_into('<d', header, 151, _packed_dms(cm) if cm is not None else 0.0)
    body, pos = bytearray(), len(header)
    for i in range(10):
        data = sections.get(i, b'')
        struct.pack_into('<ii', header, DATA_START + 10 * i, pos + len(body), len(data))
        body += data
    return bytes(header + body)


def write_points(path, points, fields=None, records=None, **header):
    """points: dicts x, y, type (0 text/1 subgraph), text, subgraph, color, alive."""
    recs, chars = bytearray(93), bytearray()
    for p in points:
        r = bytearray(93)
        r[0] = 1 if p.get('alive', True) else 0
        struct.pack_into('<2d', r, 7, p['x'], p['y'])
        r[32] = p.get('type', 0)
        if r[32] == 0:
            raw = p.get('text', '').encode('gb18030')
            struct.pack_into('<hi', r, 1, len(raw), len(chars))
            chars += raw
        else:
            struct.pack_into('<i', r, 34, p.get('subgraph', 1))
        struct.pack_into('<i', r, 84, p.get('color', 0))
        recs += r
    sections = {0: bytes(recs), 1: bytes(chars)}
    if fields:
        sections[2] = _attribute_blob(fields, [[None] * len(fields)] + list(records))
    Path(path).write_bytes(_file('2', sections, **header))


def _arc_section(arcs):
    """arcs: list of (points, alive) -> (57-byte records, coordinate block)."""
    recs, coords = bytearray(57), bytearray(b'\0\0')
    for pts, alive in arcs:
        r = bytearray(57)
        r[0] = 1 if alive else 0
        struct.pack_into('<ii', r, 10, len(pts), len(coords))
        struct.pack_into('<h', r, 20, 3)
        struct.pack_into('<i', r, 24, 5 << 16)
        struct.pack_into('<f', r, 30, 0.25)
        coords += b''.join(struct.pack('<2d', x, y) for x, y in pts)
        recs += r
    return recs, coords


def write_lines(path, lines, fields=None, records=None, **header):
    """lines: list of (points, alive)."""
    recs, coords = _arc_section(lines)
    sections = {0: bytes(recs), 1: bytes(coords)}
    if fields:
        sections[2] = _attribute_blob(fields, [[None] * len(fields)] + list(records))
    Path(path).write_bytes(_file('1', sections, **header))


def write_regions(path, arcs, regions, fields=None, records=None, **header):
    """arcs: list of (points, alive), arc id = position + 1.
    regions: list of (arc id list with 0 ring separators / negative = reversed, alive, fill)."""
    recs, coords = _arc_section(arcs)
    fills = bytearray(40)
    for ids, alive, fill in regions:
        f = bytearray(40)
        f[0] = 1 if alive else 0
        struct.pack_into('<ii', f, 1, len(ids) + 1, len(coords))
        struct.pack_into('<ih', f, 9, fill, 7)
        coords += struct.pack('<%di' % (len(ids) + 1), 0, *ids)
        fills += f
    sections = {0: bytes(recs), 1: bytes(coords), 3: bytes(24 * (len(arcs) + 1)), 8: bytes(fills)}
    if fields:
        sections[9] = _attribute_blob(fields, [[None] * len(fields)] + list(records))
    Path(path).write_bytes(_file('3', sections, **header))


def write_project(path, layer_paths):
    """Minimal .mpj: header + 400-byte layer records (kind, flags, GBK path)."""
    kinds = {'.wl': 0, '.wt': 1, '.wp': 2}
    head = bytearray(1113)
    head[0:4] = b'WMAP'
    head[4] = 0x60
    head[5:8] = b'D2:'
    struct.pack_into('<IH', head, 8, 9, len(layer_paths))
    body = bytearray()
    for p in layer_paths:
        r = bytearray(400)
        r[0] = kinds[Path(p).suffix.lower()]
        r[1] = 3
        raw = str(p).encode('gb18030')
        r[2:2 + len(raw)] = raw
        body += r
    Path(path).write_bytes(bytes(head + body))
