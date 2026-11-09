"""Optional spatial processing. Distances are metres; source geometries stay intact."""
from dataclasses import dataclass, field
from collections import Counter
import math
import re

from .errors import AnnotationError, MissingDependencyError
from .notes import parse_note


def dependencies():
    try:
        from shapely.geometry import Point, box, shape
        from shapely.strtree import STRtree
        from pyproj import CRS, Transformer
    except ImportError as exc:
        raise MissingDependencyError("Install mapgis-annotations[spatial] for spatial processing") from exc
    return Point, box, shape, STRtree, CRS, Transformer


@dataclass(frozen=True)
class AnnotationPoint:
    fid: int
    x: float
    y: float
    raw: str


@dataclass
class PairingConfig:
    min_dx: float = 20.0
    max_dx: float = 500.0
    max_dy: float = 35.0
    rock_pattern: str = r'[α-ωΑ-Ω]+'
    age_pattern: str = r'(T|P|S|D|O|K)#-[1-4](#=)?'
    working_crs: str = None
    require_legend: bool = True

    def validate(self):
        values = (self.min_dx, self.max_dx, self.max_dy)
        if not all(math.isfinite(v) and v >= 0 for v in values) or self.max_dx <= self.min_dx:
            raise AnnotationError('Require 0 <= min_dx < max_dx and max_dy >= 0; all finite metres')
        try:
            re.compile(self.rock_pattern)
            re.compile(self.age_pattern)
        except (re.error, TypeError) as exc:
            raise AnnotationError('Invalid pairing regular expression: ' + str(exc)) from exc


def _canonical_age(raw):
    return raw[:-2] if raw.endswith('#=') else raw


def pair_annotations(points, crs, config=None, allowed_pairs=None):
    """Find mutual degree-one pairs, with optional legend membership.

    Even edges from ambiguous age records count toward reverse ambiguity.
    No nearest-candidate tie breaking is performed. Returns every original
    row's display text plus explicit rejection reasons for unmatched ages.
    """
    config = config or PairingConfig()
    config.validate()
    Point, box, _, STRtree, CRS, Transformer = dependencies()
    if not crs:
        raise AnnotationError('Pairing requires a CRS; coordinate units cannot be guessed')
    source_crs = CRS.from_user_input(crs)
    working = CRS.from_user_input(config.working_crs or source_crs)
    if not working.is_projected or len(working.axis_info) < 2:
        raise AnnotationError('Pairing needs a projected working_crs; degree coordinates cannot use metre thresholds')
    factors = [axis.unit_conversion_factor for axis in working.axis_info[:2]]
    if not all(math.isfinite(f) and f > 0 for f in factors):
        raise AnnotationError('Unknown projected coordinate units')
    transformer = Transformer.from_crs(source_crs, working, always_xy=True)
    points = list(points)
    if len({p.fid for p in points}) != len(points):
        raise AnnotationError('Point fid values must be unique; use original row numbers, not repeated business IDs')
    metric = {}
    for p in points:
        x, y = transformer.transform(p.x, p.y, errcheck=True)
        x, y = x*factors[0], y*factors[1]
        if not math.isfinite(x) or not math.isfinite(y):
            raise AnnotationError('Non-finite point coordinates')
        metric[p.fid] = (x, y)
    if config.require_legend and allowed_pairs is None:
        raise AnnotationError('Provide allowed_pairs from a legend, or explicitly set require_legend=False')
    allowed = set(allowed_pairs or ())
    rocks = [p for p in points if re.fullmatch(config.rock_pattern, p.raw)]
    ages = [p for p in points if re.fullmatch(config.age_pattern, p.raw)]
    tree = STRtree([Point(*metric[p.fid]) for p in rocks])
    candidates, degree = {}, Counter()
    for age in ages:
        x, y = metric[age.fid]
        indices = tree.query(box(x-config.max_dx, y-config.max_dy,
                                 x-config.min_dx, y+config.max_dy), predicate='intersects')
        roots = [rocks[int(i)] for i in indices]
        candidates[age.fid] = roots
        degree.update(p.fid for p in roots)
    display = {p.fid: parse_note(p.raw).html for p in points}
    matched, unresolved = [], []
    for age in ages:
        roots = candidates[age.fid]
        reason = None
        if not roots:
            reason = 'NO_CANDIDATE'
        elif len(roots) != 1:
            reason = 'MULTIPLE_CANDIDATES'
        elif degree[roots[0].fid] != 1:
            reason = 'REVERSE_AMBIGUITY'
        elif config.require_legend and (roots[0].raw, _canonical_age(age.raw)) not in allowed:
            reason = 'NOT_IN_LEGEND'
        if reason:
            unresolved.append({'age_fid': age.fid, 'reason': reason,
                               'candidates': sorted(p.fid for p in roots)})
            continue
        rock = roots[0]
        display[rock.fid] = parse_note(rock.raw).html + parse_note(age.raw).html
        display[age.fid] = ''
        matched.append({'rock_fid': rock.fid, 'age_fid': age.fid, 'rock': rock.raw, 'age': age.raw,
                        'html': display[rock.fid], 'dx_m': metric[age.fid][0]-metric[rock.fid][0],
                        'dy_m': metric[age.fid][1]-metric[rock.fid][1]})
    return {'pairs': matched, 'unresolved': unresolved, 'display': display,
            'working_crs': working.to_string(), 'source_crs': source_crs.to_string()}


def crosswalk(points, polygons, point_crs, polygon_crs, *, invalid_policy='exclude'):
    """All intersects, preserving outside points and invalid-geometry status.

    polygons is an iterable of (original_fid, Shapely geometry).
    Policies: exclude (default, report invalid faces), error, or include
    (explicit compatibility mode, no repair). Original data is never edited.
    """
    Point, _, _, STRtree, CRS, Transformer = dependencies()
    if invalid_policy not in ('exclude', 'error', 'include'):
        raise AnnotationError('invalid_policy must be exclude, error or include')
    if not point_crs or not polygon_crs:
        raise AnnotationError('Both point_crs and polygon_crs are required')
    transformer = Transformer.from_crs(CRS.from_user_input(point_crs), CRS.from_user_input(polygon_crs), always_xy=True)
    points, polygons = list(points), list(polygons)
    if len({p.fid for p in points}) != len(points) or len({fid for fid, _ in polygons}) != len(polygons):
        raise AnnotationError('Crosswalk row IDs must be unique')
    invalid = [fid for fid, geometry in polygons if geometry.is_empty or not geometry.is_valid]
    if invalid and invalid_policy == 'error':
        raise AnnotationError('Invalid polygon rows: ' + repr(invalid))
    selected = [(fid, g) for fid, g in polygons if fid not in set(invalid) or invalid_policy == 'include']
    tree = STRtree([g for _, g in selected])
    rows = []
    for p in points:
        x, y = transformer.transform(p.x, p.y, errcheck=True)
        hits = sorted(int(i) for i in tree.query(Point(x, y), predicate='intersects'))
        if not hits:
            rows.append({'point_fid': p.fid, 'polygon_fid': None, 'match_count': 0,
                         'polygon_valid': None, 'status': 'UNMATCHED'})
        for i in hits:
            fid, geometry = selected[i]
            rows.append({'point_fid': p.fid, 'polygon_fid': fid, 'match_count': len(hits),
                         'polygon_valid': bool(geometry.is_valid and not geometry.is_empty),
                         'status': 'MULTIPLE' if len(hits) > 1 else 'MATCHED'})
    return {'rows': rows, 'invalid_polygon_fids': invalid, 'invalid_policy': invalid_policy,
            'point_crs': CRS.from_user_input(point_crs).to_string(),
            'polygon_crs': CRS.from_user_input(polygon_crs).to_string()}
