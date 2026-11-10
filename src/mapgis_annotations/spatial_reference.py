"""Describe exported CRS declarations without assigning or transforming data."""
import math
import json
import os
from pathlib import Path

from .errors import AnnotationError
from .shapefiles import companion, sha256, shp_files


def _load_pyproj():
    from pyproj import CRS
    from pyproj.exceptions import CRSError
    return CRS, CRSError


class _Definitions:
    def __init__(self):
        self.values, self.objects, self.identities, self.cache = {}, {}, {}, {}

    def add(self, wkt):
        if not wkt:
            return None, 'missing'
        if wkt in self.cache:
            return self.cache[wkt]
        try:
            CRS, CRSError = _load_pyproj()
        except ImportError:
            value = {'status':'unparsed', 'source_wkt':wkt, 'wkt':wkt, 'projjson':None,
                     'auth_id':None, 'error':'PyProj is unavailable; original WKT retained'}
            crs = None
        else:
            try:
                crs = CRS.from_user_input(wkt)
            except CRSError as exc:
                value = {'status':'invalid', 'source_wkt':wkt, 'wkt':wkt, 'projjson':None,
                         'auth_id':None, 'error':str(exc)}
                crs = None
            else:
                authority = crs.to_authority(min_confidence=100)
                for key, existing in self.objects.items():
                    # ESRI WKT1 rounds angular units and changes axis labels;
                    # PROJ may identify an exact authority match even when
                    # equals(ignore_axis_order=True) remains false.
                    if crs.equals(existing, ignore_axis_order=True) or (
                            authority is not None and authority == self.identities[key]):
                        self.cache[wkt] = (key, 'defined')
                        return self.cache[wkt]
                axes = []
                for axis in crs.axis_info:
                    factor = axis.unit_conversion_factor
                    axes.append({'name':axis.name, 'abbreviation':axis.abbrev, 'direction':axis.direction,
                                 'unit':axis.unit_name,
                                 'unit_conversion_factor':factor if factor is not None and math.isfinite(factor) else None})
                units = list(dict.fromkeys(axis['unit'] for axis in axes))
                value = {'status':'defined', 'name':crs.name,
                         'auth_id':':'.join(authority) if authority else None,
                         'is_geographic':crs.is_geographic, 'is_projected':crs.is_projected,
                         'unit':units[0] if len(units) == 1 else None, 'axis_info':axes,
                         'source_wkt':wkt, 'wkt':crs.to_wkt(version='WKT2_2019'),
                         'projjson':crs.to_json_dict()}
        base = value.get('auth_id') or 'crs_'+str(len(self.values)+1)
        key, index = base, 2
        while key in self.values:
            key, index = base+'#'+str(index), index+1
        self.values[key] = value
        if crs is not None:
            self.objects[key] = crs
            self.identities[key] = authority
        self.cache[wkt] = (key, value['status'])
        return self.cache[wkt]


def _read_prj(path):
    raw = path.read_bytes()
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return raw.decode(encoding), encoding, None
        except UnicodeDecodeError:
            continue
    return None, None, 'PRJ cannot be decoded as UTF-8 or GB18030; original file retained'


def spatial_reference_report(directory, *, dataset=None, native=None, source=None,
                             input_format=None, path_prefix='', rendering=None):
    """Read actual output PRJs, plus optional native conversion and render evidence.

    ``dataset`` is the annotation manifest; otherwise ``directory`` is a flat
    SHP export. Returned paths are relative to the report's dataset root.
    Missing/invalid/unparsed declarations remain explicit, even without PyProj.
    """
    from . import __version__
    directory = Path(directory).resolve()
    prefix = Path(path_prefix)
    if prefix.is_absolute() or '..' in prefix.parts:
        raise AnnotationError('Spatial reference path prefix must be relative')
    dataset_root = directory
    for _ in prefix.parts:
        dataset_root = dataset_root.parent
    if (dataset_root/prefix).resolve() != directory:
        raise AnnotationError('Spatial reference prefix does not match the dataset directory')
    definitions = _Definitions()
    frame = dict((native or {}).get('map_frame') or {})
    frame_crs, _ = definitions.add(frame.pop('crs_wkt', None))
    if frame:
        frame['crs_id'] = frame_crs
    items = dataset['layers'] if dataset is not None else {
        path.stem:{'path':path.name} for path in shp_files(directory)}
    originals = {Path(p).stem.casefold():p for p in (dataset or {}).get('source_sha256', {})
                 if Path(p).suffix.lower() == '.shp'}
    layers, data_ids = {}, set()
    for name, item in sorted(items.items()):
        path = (directory/item['path']).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise AnnotationError('Spatial reference layer is outside the dataset or missing: '+name)
        prj = companion(path, '.prj')
        wkt, encoding, error = _read_prj(prj) if prj else (None, None, None)
        crs_id, status = definitions.add(wkt)
        if prj and (error or not wkt.strip()):
            status = 'invalid'
            error = error or 'PRJ is empty; no CRS assigned'
        evidence = (native or {}).get('layers', {}).get(name)
        reference = {
            'path':(Path(path_prefix)/path.relative_to(directory)).as_posix(),
            'source':evidence['source'] if evidence else originals.get(name.casefold(), str(path)),
            'crs_id':crs_id, 'crs_status':status,
            'prj':(Path(path_prefix)/prj.relative_to(directory)).as_posix() if prj else None,
            'prj_sha256':sha256(prj) if prj else None, 'prj_decode_codec':encoding,
            'native_conversion':{key:evidence.get(key) for key in ('factor','decision','header','header_candidate')}
                                if evidence else None}
        if error:
            reference['error'] = error
        layers[name] = reference
        if status == 'defined':
            data_ids.add(crs_id)
    missing = [name for name, item in layers.items() if item['crs_status'] != 'defined']
    render_reference = None
    if rendering is not None:
        render_id, render_status = definitions.add(rendering['crs_wkt'])
        render_reference = {'crs_id':render_id, 'crs_status':render_status,
                            'extent_xy':rendering.get('extent_xy'),
                            'scope':'QGIS project and rendered map; source layer CRS declarations are preserved'}
    main = frame_crs if frame_crs in data_ids else next(iter(data_ids)) if len(data_ids) == 1 else None
    return {
        'format_version':1, 'kind':'spatial_reference', 'input_format':input_format,
        'generator':{'package':'mapgis-annotations', 'version':__version__},
        'dataset_root':str(dataset_root),
        'source':source if source is not None else (native or {}).get('source', str(directory)),
        'geometry_coordinate_order':'xy', 'main_crs_id':main,
        'data_crs_status':'mixed' if len(data_ids) > 1 else 'partial' if data_ids and missing else
                          'uniform' if data_ids else 'unassigned',
        'summary':{'layers':len(layers), 'with_crs':len(layers)-len(missing), 'without_crs':missing,
                   'invalid_crs':[n for n, v in layers.items() if v['crs_status'] == 'invalid'],
                   'unparsed_crs':[n for n, v in layers.items() if v['crs_status'] == 'unparsed'],
                   'data_crs_count':len(data_ids)},
        'crs_definitions':definitions.values, 'native_map_frame':frame or None,
        'input_issues':{'unreadable_native_sources':(native or {}).get('unreadable', {}),
                        'missing_project_layers':(native or {}).get('missing_project_layers', [])},
        'layers':layers, 'render_reference':render_reference,
        'notes':['Metadata only: no coordinate changes or CRS assignments are performed.',
                 'Native factors describe transformations already applied; do not apply them again to exported SHPs.',
                 'axis_info describes CRS definition axes; Shapefile geometry coordinates are stored as x,y.',
                 'Equivalent or 100%-confidence authority matches share a CRS id; original PRJs and hashes are retained.',
                 'Missing, invalid or unparsed CRS declarations are not guessed.']}


def export_spatial_reference(directory, output, **options):
    """Write a new UTF-8 metadata file; never overwrite an existing product."""
    output = Path(output)
    if output.exists():
        raise AnnotationError('Spatial reference output already exists: '+str(output))
    report = spatial_reference_report(directory, **options)
    try:
        report['dataset_root'] = Path(os.path.relpath(report['dataset_root'], output.resolve().parent)).as_posix()
    except ValueError:  # Different Windows drives: retain the explicit absolute root.
        pass
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    with output.open('x', encoding='utf-8') as handle:
        handle.write(payload)
    return report
