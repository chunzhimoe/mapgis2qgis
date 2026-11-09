"""Atomic, region-independent native/SHP -> annotations -> optional map workflow."""
from dataclasses import dataclass, field
import json
from pathlib import Path
import tempfile

from .errors import AnnotationError
from .georef import export_native
from .mapgis_native import EXT_KIND
from .shapefiles import publish, sha256
from .workflow import WorkflowConfig, run_workflow, verify_dataset, write_json
from .audit import audit_shapefiles


class PipelineCancelled(AnnotationError):
    """Cancellation at a stage boundary; the new output is not published."""


@dataclass
class PipelineConfig:
    input_format: str = 'auto'
    native: dict = field(default_factory=dict)
    annotations: dict = field(default_factory=dict)
    render: dict = field(default_factory=lambda: {'enabled': False})
    strict_native: bool = True

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise AnnotationError('Pipeline configuration must be an object')
        # Existing workflow profiles remain usable without rewriting their JSON.
        if value and set(value) <= {'conversion', 'annotation_layers', 'pairing', 'crosswalks'}:
            return cls(annotations=value)
        if set(value) - {'input_format', 'native', 'annotations', 'render', 'strict_native'}:
            raise AnnotationError('Unknown pipeline configuration keys')
        try:
            config = cls(**value)
        except TypeError as exc:
            raise AnnotationError(str(exc)) from exc
        config.validate()
        return config

    def validate(self):
        if self.input_format not in ('auto', 'native', 'shp'):
            raise AnnotationError('input_format must be auto, native or shp')
        if not isinstance(self.strict_native, bool):
            raise AnnotationError('strict_native must be boolean')
        if not isinstance(self.native, dict) or set(self.native) - {'epsg', 'factor', 'style', 'georeference'}:
            raise AnnotationError('Invalid native options')
        if not isinstance(self.annotations, dict):
            raise AnnotationError('annotations must be an object')
        WorkflowConfig.from_dict(self.annotations).validate()
        allowed = {'enabled','width_mm','dpi','font_size','font_family','font_unit','render_crs',
                   'max_pixels','missing_crs','details','title','auto_font_size'}
        if not isinstance(self.render, dict) or set(self.render) - allowed or not isinstance(self.render.get('enabled', False), bool):
            raise AnnotationError('Invalid render options')
        if not isinstance(self.render.get('auto_font_size', False), bool):
            raise AnnotationError('auto_font_size must be boolean')
        from .render_views import validate_views
        validate_views(self.render.get('details', []))


def _kind(source, requested):
    if requested != 'auto':
        return requested
    if source.is_file():
        if source.suffix.upper() in set(EXT_KIND) | {'.MPJ'}:
            return 'native'
        raise AnnotationError('Use a native file/project or a flat SHP directory')
    native = any(p.suffix.upper() in EXT_KIND for p in source.rglob('*') if p.is_file())
    shp = any(source.glob('*.shp')) or any(source.glob('*.SHP'))
    if native and shp:
        raise AnnotationError('Both native files and SHP found; specify input_format')
    if not native and not shp:
        raise AnnotationError('No native MapGIS or SHP data found')
    return 'native' if native else 'shp'


def _relocate(value, old, new):
    if isinstance(value, str):
        return new + value[len(old):] if value == old or value.startswith(old + '/') or value.startswith(old + '\\') else value
    if isinstance(value, list):
        return [_relocate(v, old, new) for v in value]
    if isinstance(value, dict):
        return {_relocate(k, old, new): _relocate(v, old, new) for k, v in value.items()}
    return value


def _finalize_paths(stage, destination):
    """Relocate embedded absolute provenance paths and rehash inner manifests first."""
    for path in stage.rglob('*.json'):
        content = json.loads(path.read_text(encoding='utf-8'))
        write_json(path, _relocate(content, str(stage), str(destination)))
    for path in sorted(stage.rglob('*.json'), key=lambda p: len(p.parts), reverse=True):
        content = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(content, dict) and 'product_sha256' in content:
            content['product_sha256'] = {relative: sha256(path.parent/relative) for relative in content['product_sha256']}
            write_json(path, content)


def run_pipeline(source, output, config=None, *, progress=None, cancelled=None):
    config = PipelineConfig.from_dict(config) if isinstance(config, dict) else config or PipelineConfig()
    if not isinstance(config, PipelineConfig):
        raise AnnotationError('config must be PipelineConfig or dictionary')
    config.validate()
    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.exists():
        raise AnnotationError('Input does not exist: ' + str(source))
    source_root = source if source.is_dir() else source.parent
    if output.exists() or output.is_relative_to(source_root) or source_root.is_relative_to(output):
        raise AnnotationError('Output must be a new directory outside the input tree')
    kind = _kind(source, config.input_format)
    def event(stage, percent):
        if cancelled and cancelled():
            raise PipelineCancelled('已取消，未发布输出目录')
        if progress:
            progress({'stage': stage, 'percent': percent})
    output.parent.mkdir(parents=True, exist_ok=True)
    event('prepare', 0)
    with tempfile.TemporaryDirectory(prefix='.mapgis-pipeline-', dir=str(output.parent)) as temporary:
        stage = Path(temporary)/'result'
        stage.mkdir()
        native = None
        if kind == 'native':
            event('native', 5)
            native = export_native(source, stage/'native', **config.native)
            if config.strict_native and (native['summary']['unreadable'] or native['summary']['missing_project_layers']):
                raise AnnotationError('Native input has unreadable or missing layers; see input files or set strict_native=false')
            working = stage/'native'
            sources = dict(native['source_sha256'])
            if source.is_file():
                sources[str(source)] = sha256(source)
        else:
            working = source
            sources = {str(p): sha256(p) for p in source.iterdir() if p.suffix.lower() in ('.shp','.shx','.dbf','.prj','.cpg')}
        event('audit', 25)
        audit = audit_shapefiles(working, stage/'inventory')
        event('annotations', 40)
        annotations = run_workflow(working, stage/'annotations', config.annotations, allow_no_annotations=True)
        verify_dataset(stage/'annotations')
        rendered = None
        if config.render.get('enabled', False):
            event('render', 60)
            from .qgis_adapter import export_project
            options = {k: v for k, v in config.render.items() if k != 'enabled'}
            options.setdefault('missing_crs', 'exclude')
            rendered = export_project(stage/'annotations', stage/'map', **options)
        event('verify', 90)
        if any(sha256(path) != expected for path, expected in sources.items()):
            raise AnnotationError('An original input changed during the pipeline')
        _finalize_paths(stage, output)
        verify_dataset(stage/'annotations', verify_sources=False)
        if rendered:
            export = json.loads((stage/'map/export.json').read_text(encoding='utf-8'))
            if any(sha256(stage/'map'/p) != h for p, h in export['product_sha256'].items()):
                raise AnnotationError('Rendered products failed verification')
        result = {'format_version': 2, 'kind': 'pipeline', 'status': 'PASS', 'source': str(source),
                  'input_format': kind, 'output': str(output), 'source_sha256': sources,
                  'native_summary': native['summary'] if native else None,
                  'audit': {k: v for k, v in audit.items() if k != 'layers'},
                  'annotations': {k: annotations[k] for k in ('converted_layers','converted_records','changed_notes','spatial')},
                  'map': {'path':'map/map.qgz', 'rendered_labels':rendered['rendered_labels'],
                          'excluded_layers':rendered['excluded_layers']} if rendered else None,
                  'limitations': ['原符号库完整样式未恢复；CRS候选须结合原资料核验。',
                                  '无效几何保留并报告；空间关联不等于确定地质归属。'],
                  'product_sha256': {p.relative_to(stage).as_posix(): sha256(p) for p in stage.rglob('*') if p.is_file()}}
        write_json(stage/'manifest.json', result)
        verify_dataset(stage)
        event('publish', 98)
        publish(stage, output)
    if progress:
        progress({'stage': 'complete', 'percent': 100})
    return result
