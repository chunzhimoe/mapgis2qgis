"""Dataset workflow: configurable layers, atomic outputs, portable audit files."""
from dataclasses import dataclass, field, asdict
from pathlib import Path
import csv
import json
import shutil
import tempfile

import shapefile

from .errors import AnnotationError
from .shapefiles import (ConversionConfig, POINT_TYPES, NOTE_CANDIDATES, convert_layer,
                         encoding_for, inspect_dataset, read_points, sha256, companion, find_shp, open_reader,
                         publish)


@dataclass
class WorkflowConfig:
    conversion: ConversionConfig = field(default_factory=ConversionConfig)
    annotation_layers: list = None
    pairing: dict = None
    crosswalks: list = field(default_factory=list)

    def validate(self):
        if not isinstance(self.conversion, ConversionConfig):
            raise AnnotationError('conversion must be ConversionConfig; use from_dict for JSON configuration')
        self.conversion.validate()
        if self.annotation_layers is not None and (not isinstance(self.annotation_layers, list) or
                any(not isinstance(n, str) or not n for n in self.annotation_layers)):
            raise AnnotationError('annotation_layers must be a list of nonempty layer names')
        if self.pairing is not None:
            if not isinstance(self.pairing, dict):
                raise AnnotationError('pairing must be a dictionary')
            from .spatial import PairingConfig
            options = {k:v for k,v in self.pairing.items() if k not in ('legend_layer','target_layers','crs_overrides')}
            try:
                PairingConfig(**options).validate()
            except TypeError as exc:
                raise AnnotationError('Invalid pairing configuration: ' + str(exc)) from exc
        if not isinstance(self.crosswalks, list):
            raise AnnotationError('crosswalks must be a list')
        for item in self.crosswalks:
            if not isinstance(item, dict) or not {'points','polygons'} <= set(item):
                raise AnnotationError('Each crosswalk needs points and polygons layer names')
            if set(item) - {'points','polygons','point_crs','polygon_crs','invalid_policy'}:
                raise AnnotationError('Unknown crosswalk configuration keys')

    @classmethod
    def from_dict(cls, value):
        unknown = set(value) - {'conversion', 'annotation_layers', 'pairing', 'crosswalks'}
        if unknown:
            raise AnnotationError('Unknown configuration keys: ' + repr(sorted(unknown)))
        try:
            return cls(conversion=ConversionConfig(**value.get('conversion', {})),
                       annotation_layers=value.get('annotation_layers'), pairing=value.get('pairing'),
                       crosswalks=value.get('crosswalks', []))
        except TypeError as exc:
            raise AnnotationError(str(exc)) from exc


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def write_csv(path, rows, columns):
    with Path(path).open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _points(source, name, conversion):
    from .spatial import AnnotationPoint
    fields, records, shapes, note_field, _ = read_points(
        find_shp(source, name), conversion.note_fields.get(name, conversion.note_field), conversion.encoding)
    if any(not geometry.points for geometry in shapes):
        raise AnnotationError('Spatial processing requires non-null point geometries in ' + name)
    return [AnnotationPoint(i, float(shape.points[0][0]), float(shape.points[0][1]), record[note_field] or '')
            for i, (record, shape) in enumerate(zip(records, shapes))]


def _crs(source, name, override=None):
    if override:
        return override
    path = companion(find_shp(source, name), '.prj')
    if not path:
        raise AnnotationError('Missing .prj for ' + name + '; provide explicit CRS in spatial configuration')
    return path.read_text(encoding='utf-8-sig')


def _spatial(source, stage, layers, config):
    from .spatial import PairingConfig, pair_annotations, crosswalk, dependencies
    summary = {'pairing': {}, 'crosswalks': []}
    if config.pairing:
        options = dict(config.pairing)
        legend = options.pop('legend_layer', None)
        targets = options.pop('target_layers', [])
        crs_overrides = options.pop('crs_overrides', {})
        settings = PairingConfig(**options)
        settings.validate()
        names = ([legend] if legend else []) + list(targets)
        if not targets:
            raise AnnotationError('Pairing requires target_layers')
        if len(set(names)) != len(names):
            raise AnnotationError('Pairing layer names must be unique')
        if settings.require_legend and not legend:
            raise AnnotationError('Pairing requires legend_layer or require_legend=false')
        allowed = None
        for name in names:
            if name not in layers or not layers[name]['converted']:
                raise AnnotationError('Pairing needs a converted annotation layer: ' + name)
            cfg = PairingConfig(**asdict(settings))
            if name == legend:
                cfg.require_legend = False
            result = pair_annotations(_points(source, name, config.conversion),
                                      _crs(source, name, crs_overrides.get(name)), cfg, allowed)
            if name == legend:
                allowed = {(p['rock'], p['age'][:-2] if p['age'].endswith('#=') else p['age']) for p in result['pairs']}
            relative = 'layers/' + name + '/display.json'
            write_json(stage / relative, result)
            write_csv(stage / 'layers' / name / 'pairs.csv', result['pairs'],
                      ['rock_fid', 'age_fid', 'rock', 'age', 'html', 'dx_m', 'dy_m'])
            layers[name]['display'] = relative
            summary['pairing'][name] = {'matched': len(result['pairs']), 'unresolved': len(result['unresolved'])}
    for i, specification in enumerate(config.crosswalks):
        options = dict(specification)
        point_name, polygon_name = options.pop('points'), options.pop('polygons')
        if point_name not in layers or polygon_name not in layers:
            raise AnnotationError('Unknown crosswalk layer')
        point_crs = _crs(source, point_name, options.pop('point_crs', None))
        polygon_crs = _crs(source, polygon_name, options.pop('polygon_crs', None))
        _, _, shape, _, _, _ = dependencies()
        path = find_shp(source, polygon_name)
        with open_reader(path, config.conversion.encoding) as reader:
            if reader.shapeType not in (shapefile.POLYGON, shapefile.POLYGONM, shapefile.POLYGONZ):
                raise AnnotationError('Crosswalk polygons must be a polygon layer')
            polygons = [(fid, shape(s.__geo_interface__) if s.shapeType != shapefile.NULL else
                         shape({'type': 'GeometryCollection', 'geometries': []}))
                        for fid, s in enumerate(reader.shapes())]
        points = [p for p in _points(source, point_name, config.conversion) if p.raw]
        result = crosswalk(points, polygons, point_crs, polygon_crs, **options)
        relative = 'crosswalk_' + str(i) + '.json'
        write_json(stage / relative, result)
        write_csv(stage / ('crosswalk_'+str(i)+'.csv'), result['rows'],
                  ['point_fid', 'polygon_fid', 'match_count', 'polygon_valid', 'status'])
        summary['crosswalks'].append({'points': point_name, 'polygons': polygon_name,
                                     'report': relative, 'rows': len(result['rows']),
                                     'invalid_polygons': len(result['invalid_polygon_fids'])})
    return summary


def run_workflow(source, output, config=None, *, allow_no_annotations=False):
    """Convert all selected annotation layers; copy other SHPs for complete maps.

    Default detection accepts single-point layers with exactly one common
    annotation field. Explicit annotation_layers/note_fields handle arbitrary
    schemas. Failure at any stage rolls back the entire new output directory.
    """
    config = config or WorkflowConfig()
    if isinstance(config, dict):
        config = WorkflowConfig.from_dict(config)
    config.validate()
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise AnnotationError('Output must be a new directory outside the input tree')
    inventory = inspect_dataset(source, config.conversion.encoding)
    known = {item['layer'] for item in inventory}
    explicit = set(config.annotation_layers or ()) | set(config.conversion.note_fields)
    if explicit - known:
        raise AnnotationError('Unknown annotation layers: ' + repr(sorted(explicit-known)))
    output.parent.mkdir(parents=True, exist_ok=True)
    original = {str(p): sha256(p) for p in source.iterdir() if p.is_file() and p.suffix.lower() in ('.shp', '.shx', '.dbf', '.prj', '.cpg')}
    with tempfile.TemporaryDirectory(prefix='.mapgis-dataset-', dir=str(output.parent)) as temporary:
        stage = Path(temporary) / 'dataset'
        stage.mkdir()
        layers = {}
        for item in inventory:
            name = item['layer']
            selected = name in explicit if config.annotation_layers is not None else (
                name in explicit or (item['shape_type'] in POINT_TYPES and
                                    (config.conversion.note_field in item['fields'] if config.conversion.note_field else
                                     any(f.casefold() in NOTE_CANDIDATES for f in item['fields']))))
            folder = stage / 'layers' / name
            if selected:
                result = convert_layer(source/item['filename'], folder, config.conversion)
            else:
                folder.mkdir(parents=True)
                for suffix in ('.shp', '.shx', '.dbf', '.cpg', '.prj'):
                    path = companion(source/item['filename'], suffix)
                    if path:
                        shutil.copyfile(path, (folder/item['filename']).with_suffix(suffix))
                result = None
            layers[name] = {'path': 'layers/'+name+'/'+item['filename'], 'converted': selected,
                            'conversion': result, 'shape_type': item['shape_type'], 'records': item['records']}
        if not allow_no_annotations and not any(v['converted'] for v in layers.values()):
            raise AnnotationError('No annotation layers selected; configure annotation_layers and note_fields')
        spatial = _spatial(source, stage, layers, config) if config.pairing or config.crosswalks else {'pairing': {}, 'crosswalks': []}
        if original != {path: sha256(path) for path in original}:
            raise AnnotationError('Source files changed during workflow')
        products = {str(p.relative_to(stage)): sha256(p) for p in stage.rglob('*') if p.is_file()}
        manifest = {'format_version': 1, 'status': 'PASS', 'config': asdict(config), 'layers': layers,
                    'spatial': spatial, 'source_sha256': original, 'product_sha256': products,
                    'converted_layers': sum(v['converted'] for v in layers.values()),
                    'converted_records': sum(v['records'] for v in layers.values() if v['converted']),
                    'changed_notes': sum(v['conversion']['changed'] for v in layers.values() if v['converted'])}
        write_json(stage/'manifest.json', manifest)
        publish(stage, output)
    return manifest


def verify_dataset(directory, *, verify_sources=True):
    directory = Path(directory).resolve()
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    for relative, expected in manifest['product_sha256'].items():
        path = (directory/relative).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or sha256(path) != expected:
            raise AnnotationError('Product missing or modified: ' + relative)
    if verify_sources:
        for path, expected in manifest['source_sha256'].items():
            if not Path(path).is_file() or sha256(path) != expected:
                raise AnnotationError('Source missing or modified: ' + path)
    return {'status': 'PASS', 'products_checked': len(manifest['product_sha256']),
            'sources_checked': len(manifest['source_sha256']) if verify_sources else 0,
            'scope': 'products-and-sources' if verify_sources else 'products-only'}
