"""Native MapGIS map -> georeferenced Shapefile dataset, with evidence for every decision.

MapGIS headers are frequently wrong (blank on data layers, left over from an enlarged or
reduced source map), so headers only *propose* frames and the coordinates decide:

1. frame: a Gauss-Kruger header key (ellipsoid, central meridian, scale); factor =
   scale / 1000 (paper mm -> m). The EPSG code is looked up by *name* in the PROJ
   database from datum (ellipsoid 1/16 Beijing 1954, 2 Xian 1980), 6°/3° series and zone
   prefix (easting >= 1e6 m carries the zone number); lon_0 must equal the header
   meridian. A frame is valid only if its own layers invert to plausible lon/lat
   (|lon - CM| <= 6° or 4.5°, 0..60°N). The map frame is the valid frame with most layers.
2. each layer: its own valid header frame if plausible; else any valid frame whose extent
   (+10 %) holds >= 50 % of the layer (map units, header ignored); else exactly one
   standard map-scale factor (1:500 ... 1:1,000,000) that puts the layer inside a frame,
   flagged ``factor INFERRED``; else no CRS (insets, tables, sections, own paper space):
   stored units, no .prj.
3. evidence: point layers whose attributes hold lon/lat (decimal or packed DDDMMSS, found
   by value so coded names such as CHAHBA/CHAHBB work) yield a median residual in metres.

Geographic, Albers, Lambert and additional TM ellipsoids are decoded as header
candidates too. Accepted custom CRSs retain their full WKT even without EPSG.
Unknown datums are never guessed; pass ``epsg``/``factor`` explicitly instead.
"""
import collections
import json
import math
from pathlib import Path
import re
import statistics
import tempfile
import time

from .errors import AnnotationError, MissingDependencyError
from .mapgis_native import (EXT_KIND, KIND_SUFFIX, native_files, read_native_layer,
                            scale_features, write_shapefile)
from .shapefiles import publish, sha256
from .native_crs import decode_dms, header_crs

__all__ = ['export_native', 'gk_epsg']

DATUM_PREFIX = {1: 'Beijing 1954', 16: 'Beijing 1954', 2: 'Xian 1980'}
STD_FACTORS = (1.0, 0.5, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 200.0, 250.0, 500.0, 1000.0)
LON_RE = re.compile(r'(经度|东经|^lon|^long|^jd$|^x_?lon)', re.I)
LAT_RE = re.compile(r'(纬度|北纬|^lat|^wd$|^y_?lat)', re.I)
_NAMES = None


def _pyproj():
    try:
        import pyproj
    except ImportError as exc:
        raise MissingDependencyError('Georeferencing needs pyproj: pip install ".[spatial]" '
                                     '(or use georeference=False for stored units)') from exc
    return pyproj


def _crs_by_name(name):
    global _NAMES
    if _NAMES is None:
        from pyproj.database import query_crs_info
        _NAMES = {i.name: int(i.code) for i in query_crs_info(auth_name='EPSG', pj_types='PROJECTED_CRS')}
    return _NAMES.get(name)


def gk_epsg(ellipsoid, cm, scale, sample_x):
    """(EPSG code or None, CRS name or reason) for a MapGIS Gauss-Kruger header."""
    from pyproj import CRS
    datum = DATUM_PREFIX.get(ellipsoid)
    if datum is None:
        return None, 'ellipsoid code %s has no known EPSG Gauss-Kruger series' % ellipsoid
    if cm is None:
        return None, 'no central meridian in header'
    cm = round(cm, 6)
    six = abs((cm + 3) / 6 - round((cm + 3) / 6)) < 1e-9
    three = abs(cm / 3 - round(cm / 3)) < 1e-9
    if sample_x >= 1e6:
        zone = int(sample_x // 1e6)
        names = (['%s / Gauss-Kruger zone %d' % (datum, zone)] if six and round((cm + 3) / 6) == zone else []) + \
                (['%s / 3-degree Gauss-Kruger zone %d' % (datum, zone)] if three and round(cm / 3) == zone else [])
    else:
        six_name = '%s / Gauss-Kruger CM %dE' % (datum, round(cm))
        three_name = '%s / 3-degree Gauss-Kruger CM %dE' % (datum, round(cm))
        prefer3 = bool(scale) and scale <= 10000
        names = ([six_name] if six and not prefer3 else []) + ([three_name] if three else []) + \
                ([six_name] if six and prefer3 else [])
    for name in names:
        code = _crs_by_name(name)
        if code and abs(CRS.from_epsg(code).to_dict().get('lon_0', 1e9) - cm) < 1e-9:
            return code, name
    return None, 'no EPSG Gauss-Kruger CRS for %s CM %s (x=%.0f)' % (datum, cm, sample_x)


def _dms(v):
    s = str(v).strip()
    for ch in '°′\'″"':
        s = s.replace(ch, ' ')
    parts = s.split()
    if len(parts) >= 2:
        degrees, minutes = float(parts[0]), float(parts[1])
        seconds = float(parts[2]) if len(parts) > 2 else 0
        if not (0 <= minutes < 60 and 0 <= seconds < 60):
            raise ValueError('Invalid attribute DMS minutes/seconds')
        return math.copysign(abs(degrees) + minutes / 60 + seconds / 3600, degrees)
    f = float(s)
    if abs(f) > 360:
        decoded = decode_dms(f)
        if decoded is None:
            raise ValueError('Invalid packed attribute DMS')
        return decoded
    return f


def _degree_fields(layer, lo, hi):
    out = []
    for i in range(len(layer.fields)):
        values = [v[i] for _, v in layer.features if v[i] not in (None, '')]
        if len(values) < 3:
            continue
        good = 0
        for x in values[:500]:
            try:
                good += lo <= _dms(x) <= hi
            except (TypeError, ValueError):
                pass
        if good >= 0.8 * min(len(values), 500):
            out.append(i)
    return out


def lonlat_evidence(layer, factor, epsg, window):
    """Best median residual (m) between point positions and a lon/lat attribute pair."""
    if layer.kind != 'POINT' or not epsg or not layer.features or not window:
        return None
    from pyproj import CRS, Transformer
    names = [f.name for f in layer.fields]
    lons = _degree_fields(layer, window['lon'][0] - 0.5, window['lon'][1] + 0.5)
    lats = _degree_fields(layer, window['lat'][0] - 0.5, window['lat'][1] + 0.5)
    named = [(i, j) for i in lons if LON_RE.search(names[i]) for j in lats if LAT_RE.search(names[j])]
    pairs = named + [(i, j) for i in lons for j in lats if i != j and (i, j) not in named]
    if not pairs:
        return None
    crs = CRS.from_user_input(epsg)
    t = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
    geod = crs.get_geod() if crs.is_geographic else None
    best = None
    for i, j in pairs[:12]:
        residuals = []
        for g, values in layer.features:
            try:
                lon, lat = _dms(values[i]), _dms(values[j])
            except (TypeError, ValueError):
                continue
            if g is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
                continue
            x, y = t.transform(lon, lat)
            if geod:
                residual = abs(geod.inv(lon, lat, g[0] * factor, g[1] * factor)[2])
            else:
                residual = max(abs(g[0] * factor - x), abs(g[1] * factor - y))
            if math.isfinite(residual):
                residuals.append(residual)
        if residuals:
            candidate = {'fields': [names[i], names[j]], 'n': len(residuals),
                         'median_m': round(statistics.median(residuals), 3),
                         'share_within_100m': round(sum(r <= 100 for r in residuals) / len(residuals), 4),
                         'metric': 'geodesic' if geod else 'max_axis_distance'}
            if best is None or candidate['median_m'] < best['median_m']:
                best = candidate
    return best


def _sample(layer, n=500):
    pts = []
    for g, _ in layer.features:
        if g is not None:
            pts += [g] if layer.kind == 'POINT' else (g if layer.kind == 'LINE' else [p for r in g for p in r])
    if not pts:
        return [], None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    out = pts[::max(1, len(pts) // n)]
    out += [(bbox[0], bbox[1]), (bbox[2], bbox[3]), (bbox[0], bbox[3]), (bbox[2], bbox[1])]
    return out, bbox


def plausibility(pts, factor, epsg, cm):
    from pyproj import CRS, Transformer
    crs = CRS.from_user_input(epsg)
    t = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    ll = [t.transform(x * factor, y * factor) for x, y in pts]
    lons, lats = [p[0] for p in ll], [p[1] for p in ll]
    finite = all(math.isfinite(lo) and math.isfinite(la) for lo, la in ll)
    ok = finite and all(-180 <= lo <= 180 and -90 <= la <= 90 for lo, la in ll)
    method = crs.coordinate_operation.method_name if crs.coordinate_operation else ''
    if 'Transverse Mercator' in method and cm is not None:
        width = 4.5 if '3-degree' in crs.name else 6.0
        ok = ok and all(abs((lo - cm + 180) % 360 - 180) <= width for lo in lons)
    if 'Gauss-Kruger' in crs.name:
        ok = ok and all(0 <= la <= 60 for la in lats)  # preserve the original China GK check
    if ok:
        forward = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
        restored = [forward.transform(lo, la) for lo, la in ll]
        tolerance = 1e-7 if crs.is_geographic else 0.01
        ok = all(math.isfinite(a) and abs(a - b * factor) <= tolerance
                 for actual, original in zip(restored, pts) for a, b in zip(actual, original))
    return {'ok': ok, 'lon': [round(min(lons), 4), round(max(lons), 4)],
            'lat': [round(min(lats), 4), round(max(lats), 4)]}


def _frame_crs(frame):
    return frame.get('crs_wkt') or frame['epsg']


def _containment(bb, ext):
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    if w <= 0 or h <= 0:
        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        return float(ext[0] <= cx <= ext[2] and ext[1] <= cy <= ext[3])
    ix = max(0.0, min(bb[2], ext[2]) - max(bb[0], ext[0]))
    iy = max(0.0, min(bb[3], ext[3]) - max(bb[1], ext[1]))
    return ix * iy / (w * h)


def _extent(boxes, f):
    return (min(b[0] for b in boxes) * f, min(b[1] for b in boxes) * f,
            max(b[2] for b in boxes) * f, max(b[3] for b in boxes) * f)


def _grow(ext, k=0.1):
    dx, dy = (ext[2] - ext[0]) * k, (ext[3] - ext[1]) * k
    return (ext[0] - dx, ext[1] - dy, ext[2] + dx, ext[3] + dy)


def decide_frames(layers, epsg=None, factor=None):
    """layers: {path: {'layer','pts','bbox','key'}} -> (valid frames, map key)."""
    groups = {}
    for p, item in layers.items():
        if item['key'] and item['bbox']:
            groups.setdefault(item['key'], []).append(p)
    valid = {}
    for key, members in groups.items():
        pts = [q for p in members for q in layers[p]['pts']]
        item = layers[members[0]]
        candidate = item['candidate']
        code, name, crs_input, cm = None, None, None, item['layer'].header_cm
        f = candidate.factor
        if key[0] != 'header':
            f = key[2] / 1000.0
            code, name = gk_epsg(key[0], key[1], key[2], max(x for x, _ in pts) * f)
            crs_input = code
        # Preserve the established China GK gate: a plausible inverse alone
        # must not legitimise an unrelated/stale header (e.g. Xian80 CM48).
        # Other datums and conic/geographic headers use the new candidate path.
        allow_custom = key[0] == 'header' or item['layer'].ellipsoid not in DATUM_PREFIX
        if crs_input is None and candidate.wkt and allow_custom:
            from pyproj import CRS
            crs = CRS(candidate.wkt)
            crs_input, code, name = crs, crs.to_epsg(), crs.name
        if crs_input and plausibility(pts, f, crs_input, cm)['ok']:
            from pyproj import CRS
            crs = CRS(crs_input)
            valid[key] = {'epsg': code, 'name': name, 'crs_wkt': crs.to_wkt(), 'factor': f,
                          'layers': len(members), 'cm': cm, 'geographic': crs.is_geographic,
                          'warnings': list(candidate.warnings),
                          'extent': _extent([layers[p]['bbox'] for p in members], f)}
    map_key = max(valid, key=lambda k: (valid[k]['layers'], (valid[k]['extent'][2] - valid[k]['extent'][0]) *
                                        (valid[k]['extent'][3] - valid[k]['extent'][1]))) if valid else None
    if epsg or factor:
        if map_key is None:
            keys = collections.Counter(i['key'] for i in layers.values() if i['key'] and i['bbox'])
            map_key = keys.most_common(1)[0][0] if keys else ('given', None, 0.0)
            members = [p for p, i in layers.items() if i['bbox'] and (i['key'] == map_key or not keys)]
            first = layers[members[0]] if members else None
            f = factor or (first['candidate'].factor if first else 1.0)
            valid[map_key] = {'epsg': None, 'name': None, 'factor': f, 'layers': len(members),
                              'cm': first['layer'].header_cm if first else None,
                              'extent': _extent([layers[p]['bbox'] for p in members], f) if members else None}
        frame = valid[map_key]
        if frame.get('geographic') and not epsg and factor is not None and factor != 1.0:
            raise AnnotationError('A geographic CRS needs factor=1; degree coordinates cannot be scaled to metres')
        if factor:
            if frame['extent']:
                frame['extent'] = tuple(c / frame['factor'] * factor for c in frame['extent'])
            frame['factor'] = factor
        if epsg:
            from pyproj import CRS
            crs = CRS.from_epsg(epsg)
            frame['epsg'], frame['name'] = epsg, crs.name + ' (given)'
            frame['crs_wkt'], frame['geographic'] = crs.to_wkt(), crs.is_geographic
            frame['given'] = True
            frame['cm'] = crs.to_dict().get('lon_0', frame['cm'])
            if crs.is_geographic and factor is None:
                if frame['extent']:
                    frame['extent'] = tuple(c / frame['factor'] for c in frame['extent'])
                frame['factor'] = 1.0
            elif crs.is_geographic and factor != 1.0:
                raise AnnotationError('A geographic CRS needs factor=1; degree coordinates cannot be scaled to metres')
        if not _frame_crs(frame) or not frame['extent']:
            valid.pop(map_key)
            map_key = None
    return valid, map_key


def decide_layer(item, valid, map_key):
    """-> (frame key, factor, epsg, crs name, how)"""
    pts, bb, own = item['pts'], item['bbox'], item['key']
    order = ([map_key] if map_key else []) + [k for k in valid if k != map_key]
    if not pts:
        k = own if own in valid else map_key
        return (k, valid[k]['factor'], valid[k]['epsg'], valid[k]['name'], 'empty layer') if k \
            else (None, 1.0, None, None, 'empty layer, no frame')
    for k in ([own] if own in valid else []) + [k for k in order if k != own]:
        frame = valid[k]
        if frame.get('geographic') and k != own and not frame.get('given'):
            continue  # never assign degrees to an unrelated paper-space layer
        box = tuple(c * frame['factor'] for c in bb)
        if (k == own or _containment(box, _grow(frame['extent'])) >= 0.5) and \
                plausibility(pts, frame['factor'], _frame_crs(frame), frame['cm'])['ok']:
            how = 'header frame' if k == own else 'inside map frame (header %s)' % (
                'proj_type=%d' % item['layer'].proj_type if own is None else 'frame %s differs' % (own,))
            return k, frame['factor'], frame['epsg'], frame['name'], how
    for k in order:
        frame = valid[k]
        if frame.get('geographic'):
            continue  # map-scale inference applies only to projected coordinates
        fits = [(_containment(tuple(c * f for c in bb), _grow(frame['extent'])), f) for f in STD_FACTORS]
        fits = [x for x in fits if x[0] >= 0.5]
        if len(fits) == 1 and plausibility(pts, fits[0][1], _frame_crs(frame), frame['cm'])['ok']:
            return (k, fits[0][1], frame['epsg'], frame['name'],
                    'factor INFERRED: x%g puts %.0f%% of the layer inside the map frame' % (fits[0][1], fits[0][0] * 100))
    return None, 1.0, None, None, 'no frame fits (inset, table, section or own paper space): stored units'


def _names(paths):
    used, out = set(), {}
    for p in paths:
        base = '%s_%s' % (p.stem, KIND_SUFFIX[EXT_KIND[p.suffix.upper()]])
        name, k = base, 2
        while name.upper() in used:
            name, k = '%s_%d' % (base, k), k + 1
        used.add(name.upper())
        out[p] = name
    return out


def export_native(source, output, epsg=None, factor=None, style=True, georeference=True):
    """Convert a native MapGIS map (folder, .mpj or single .wt/.wl/.wp) into a new flat
    directory of Shapefiles that ``run_workflow`` can consume directly.

    georeference=True (needs pyproj) decides unit factor and EPSG per layer as described in
    the module docstring; epsg/factor override the map frame. georeference=False keeps
    stored units without .prj. The output directory must not exist and must lie outside
    the source tree; work is staged and moved into place only on success. Source files
    are hashed before and after. Returns the manifest (also ``native_export.json``).
    """
    t0 = time.time()
    if factor is not None and (not math.isfinite(factor) or factor <= 0):
        raise AnnotationError('factor must be finite and positive')
    if georeference or epsg:
        _pyproj()
    name, paths, missing = native_files(source)
    source_root = Path(source).resolve()
    source_root = source_root if source_root.is_dir() else source_root.parent
    output = Path(output).resolve()
    if output.exists() or output.is_relative_to(source_root) or source_root.is_relative_to(output):
        raise AnnotationError('Output must be a new directory outside the input tree')
    if not paths:
        raise AnnotationError('No MapGIS .wt/.wl/.wp files found in ' + str(source))
    before = {str(p): sha256(p) for p in paths}
    layers, bad = {}, {}
    for p in paths:
        try:
            layer = read_native_layer(p, style=style)
        except AnnotationError as exc:
            bad[str(p)] = str(exc)
            continue
        pts, bbox = _sample(layer)
        key = (layer.ellipsoid, round(layer.header_cm, 6) if layer.header_cm is not None else None,
               layer.scale) if layer.proj_type == 5 and math.isfinite(layer.scale) and layer.scale > 0 else None
        candidate = header_crs(layer.header_parameters) if georeference or epsg else None
        if key is None and candidate and candidate.wkt:
            key = ('header',) + tuple(layer.header_parameters[k] for k in layer.header_parameters if k != 'scale')
            if layer.proj_type != 0:
                key += (layer.header_parameters['scale'],)
        layers[p] = {'layer': layer, 'pts': pts, 'bbox': bbox, 'key': key, 'candidate': candidate}
    valid, map_key = decide_frames(layers, epsg, factor) if georeference or epsg else ({}, None)
    names = _names(paths)
    manifest = {'source': str(Path(source).resolve()), 'map': name, 'georeference': bool(georeference or epsg),
                'map_frame': dict(valid[map_key], key=list(map_key)) if map_key else None,
                'frames': {str(k): v for k, v in valid.items()}, 'missing_project_layers': missing,
                'unreadable': bad, 'layers': {}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.mapgis-native-', dir=str(output.parent)) as temporary:
        stage = Path(temporary) / 'dataset'
        stage.mkdir()
        prj_cache = {}
        for p in paths:
            if str(p) in bad:
                continue
            item, layer = layers[p], layers[p]['layer']
            if valid:
                key, f, code, crs_name, how = decide_layer(item, valid, map_key)
            elif factor:
                key, f, code, crs_name, how = None, factor, None, None, 'given factor, no CRS'
            else:
                key, f, code, crs_name, how = None, 1.0, None, None, (
                    'no usable CRS candidate: stored units' if georeference else 'stored units (georeference off)')
            crs_input = _frame_crs(valid[key]) if key is not None else None
            check = plausibility(item['pts'], f, crs_input, valid[key]['cm']) if crs_input and item['pts'] else None
            evidence = lonlat_evidence(layer, f, crs_input, check) if crs_input else None
            if crs_input and crs_input not in prj_cache:
                from pyproj import CRS
                prj_cache[crs_input] = CRS(crs_input).to_wkt('WKT1_ESRI')
            features = scale_features(layer, f) if f != 1.0 else layer.features
            fields = write_shapefile(stage / names[p], layer.kind, layer.fields, features,
                                     prj=prj_cache.get(crs_input))
            manifest['layers'][names[p]] = {
                'source': str(p), 'kind': layer.kind, 'features': len(features),
                'null_geometries': sum(1 for g, _ in features if g is None),
                'fields': [{'name': x.name, 'type': x.kind, 'width': x.width, 'decimals': x.decimals} for x in fields],
                'header': dict(layer.header_parameters, proj_type=layer.proj_type),
                'header_candidate': {'reason': item['candidate'].reason, 'warnings': list(item['candidate'].warnings)}
                                    if item['candidate'] else None,
                'decision': how, 'factor': f, 'epsg': code, 'crs': crs_name, 'crs_wkt': crs_input,
                'lonlat_window': check,
                'lonlat_attribute_check': evidence,
                'products': {q.name: sha256(q) for q in sorted(stage.glob(names[p] + '.*'))}}
        after = {p: sha256(p) for p in before}
        if after != before:
            raise AnnotationError('Source files changed during export; nothing was written')
        entries = manifest['layers'].values()
        manifest['source_sha256'] = before
        manifest['summary'] = {
            'layers': len(manifest['layers']), 'features': sum(e['features'] for e in entries),
            'with_crs': sum(1 for e in entries if e['crs_wkt']),
            'without_crs': sorted(k for k, e in manifest['layers'].items() if not e['crs_wkt']),
            'factor_inferred': sorted(k for k, e in manifest['layers'].items() if 'INFERRED' in e['decision']),
            'epsg': sorted({e['epsg'] for e in entries if e['epsg']}),
            'unreadable': len(bad), 'missing_project_layers': len(missing),
            'seconds': round(time.time() - t0, 2)}
        (stage / 'native_export.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2,
                                                             default=str, allow_nan=False) + '\n', encoding='utf-8')
        publish(stage, output)
    manifest['output'] = str(output)
    return manifest
