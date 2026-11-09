# SPDX-License-Identifier: Apache-2.0
# Projection decoding adapted from leecugb/mapgis2shp (pymapgis/reader.py).
# See THIRD_PARTY_NOTICES.md and licenses/Apache-2.0.txt.
"""MapGIS header CRS candidates; coordinate validation belongs to georef.

No fixed regional datum shifts are supplied. A recognised ellipsoid alone does
not establish a datum, and a decoded header is only a candidate, not proof.
PyProj is imported only when constructing a CRS.
"""
from dataclasses import dataclass
import math
import struct

from .errors import MissingDependencyError, NativeFormatError


def decode_dms(value):
    """Decode signed DDDMMSS.sss, rejecting invalid minutes/seconds and NaN."""
    if not math.isfinite(value):
        return None
    degrees, tail = divmod(abs(value), 10000)
    minutes, seconds = divmod(tail, 100)
    if minutes >= 60 or seconds >= 60:
        return None
    return math.copysign(degrees + minutes / 60 + seconds / 3600, value)


def read_header_parameters(raw):
    """Read documented fixed offsets without importing a GIS dependency."""
    if len(raw) < 215:
        raise NativeFormatError('Truncated MapGIS coordinate header')
    def number(offset):
        value = struct.unpack_from('<d', raw, offset)[0]
        return value if math.isfinite(value) else None
    return {'projection': raw[109], 'ellipsoid': raw[110], 'scale': number(143),
            'central_meridian': decode_dms(struct.unpack_from('<d', raw, 151)[0]),
            'latitude_origin': decode_dms(struct.unpack_from('<d', raw, 175)[0]),
            'standard_parallel_1': decode_dms(struct.unpack_from('<d', raw, 183)[0]),
            'standard_parallel_2': decode_dms(struct.unpack_from('<d', raw, 191)[0]),
            'false_easting': number(199), 'false_northing': number(207)}


@dataclass(frozen=True)
class HeaderCRS:
    wkt: str = None
    factor: float = 1.0
    reason: str = ''
    warnings: tuple = ()


# Index numbers depend on the originating installation's ellip.dat. These are
# the conventional mappings used by mapgis2shp, never an automatic datum shift.
_GEOGRAPHIC_EPSG = {1: 4214, 2: 4610, 7: 4326, 9: 4322}
_ELLIPSOIDS = {10: 'aust_SA', 11: 'aust_SA', 16: 'krass', 116: 'clrk80'}


def header_crs(parameters):
    """Build a candidate for lon/lat, TM, Albers or Lambert from header values.

    Returns an unassigned candidate with an explicit reason on invalid/unknown
    parameters. Geographic coordinates keep factor 1 even if scale is zero/NaN.
    Transverse Mercator uses MapGIS's conventional 500 km false easting; its
    header offsets 199/207 are only established here for the conic projections.
    """
    try:
        from pyproj import CRS
        from pyproj.crs import ProjectedCRS
        from pyproj.exceptions import CRSError
    except ImportError as exc:
        raise MissingDependencyError('Header CRS decoding needs pyproj: install ".[spatial]"') from exc
    p, code = parameters, parameters['ellipsoid']
    warnings = ['ELLIPSOID_INDEX_ASSUMED: verify the originating ellip.dat',
                'NO_REGIONAL_DATUM_SHIFT: no fixed towgs84 parameters applied']
    if code in _GEOGRAPHIC_EPSG:
        base = CRS.from_epsg(_GEOGRAPHIC_EPSG[code])
    elif code in _ELLIPSOIDS:
        base = CRS.from_proj4('+proj=longlat +ellps=%s +type=crs' % _ELLIPSOIDS[code])
        warnings.append('ELLIPSOID_ONLY: datum is not established')
    else:
        return HeaderCRS(reason='unknown ellipsoid index %s' % code)
    projection = p['projection']
    if projection == 0:
        return HeaderCRS(base.to_wkt(), 1.0, 'geographic header candidate', tuple(warnings))
    if projection not in (2, 3, 5):
        return HeaderCRS(reason='unsupported projection index %s' % projection)
    scale, cm = p['scale'], p['central_meridian']
    if scale is None or not math.isfinite(scale) or scale <= 0:
        return HeaderCRS(reason='projected header needs a finite positive scale')
    if cm is None or not math.isfinite(cm) or abs(cm) > 180:
        return HeaderCRS(reason='invalid central meridian')
    if projection == 5:
        specification = '+proj=tmerc +lat_0=0 +lon_0=%s +k=1 +x_0=500000 +y_0=0' % cm
    else:
        angles = [p[k] for k in ('latitude_origin', 'standard_parallel_1', 'standard_parallel_2')]
        offsets = [p[k] for k in ('false_easting', 'false_northing')]
        if any(v is None or not math.isfinite(v) or abs(v) > 90 for v in angles) or \
                any(v is None or not math.isfinite(v) for v in offsets):
            return HeaderCRS(reason='invalid conic latitude or false origin')
        specification = ('+proj=%s +lon_0=%s +lat_0=%s +lat_1=%s +lat_2=%s +x_0=%s +y_0=%s' %
                         (('aea' if projection == 2 else 'lcc'), cm, *angles, *offsets))
    try:
        operation = CRS.from_proj4(specification + ' +ellps=WGS84 +units=m +type=crs').coordinate_operation
        crs = ProjectedCRS(name='MapGIS %s / %s' % (base.name, {2: 'Albers', 3: 'Lambert', 5: 'TM'}[projection]),
                           conversion=operation, geodetic_crs=base)
    except CRSError:
        return HeaderCRS(reason='invalid projection parameters rejected by PROJ')
    return HeaderCRS(crs.to_wkt(), scale / 1000, 'projected header candidate', tuple(warnings))
