"""Command line front-end; normal conversion does not require QGIS."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .errors import AnnotationError
from .notes import parse_note
from .shapefiles import ConversionConfig, convert_layer, inspect_dataset
from .workflow import WorkflowConfig, run_workflow, verify_dataset


def main(argv=None):
    from .runtime import configure_runtime
    configure_runtime()
    parser = argparse.ArgumentParser(prog='mapgis-annotations')
    from . import __version__
    parser.add_argument('--version', action='version', version='mapgis-annotations ' + __version__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('gui', help='Open the desktop conversion workbench')
    pipeline = commands.add_parser('pipeline', help='Complete native/SHP conversion, audit and optional rendering')
    pipeline.add_argument('source')
    pipeline.add_argument('output')
    pipeline.add_argument('--config')
    pipeline.add_argument('--render', action='store_true')
    pipeline.add_argument('--events', help='Write stage progress as JSON lines')
    pipeline.add_argument('--cancel-file', help='Cancel at the next stage boundary if this file exists')
    native = commands.add_parser('from-mapgis', help='Native MapGIS .wt/.wl/.wp/.mpj -> new SHP dataset '
                                                     '(no MapGIS needed; output feeds "run")')
    native.add_argument('source', help='map folder, .mpj project or single work file')
    native.add_argument('output')
    native.add_argument('--epsg', type=int, help='override the map CRS')
    native.add_argument('--factor', type=float, help='override stored-unit -> metre factor')
    native.add_argument('--no-georef', action='store_true', help='keep stored units, no .prj (no pyproj needed)')
    native.add_argument('--no-style', action='store_true', help='only MapGIS attribute fields')
    note = commands.add_parser('parse', help='Parse a MapGIS annotation without GIS files')
    note.add_argument('text')
    note.add_argument('--strict', action='store_true')
    inspect = commands.add_parser('inspect', help='Read-only input schema inventory')
    inspect.add_argument('source')
    inspect.add_argument('--encoding')
    convert = commands.add_parser('convert', help='Convert a single point SHP into a new directory')
    convert.add_argument('source')
    convert.add_argument('output')
    convert.add_argument('--note-field')
    convert.add_argument('--encoding')
    run = commands.add_parser('run', help='Run a configured dataset workflow')
    run.add_argument('source')
    run.add_argument('output')
    run.add_argument('--config')
    verify = commands.add_parser('verify', help='Verify generated products and optional source hashes')
    verify.add_argument('directory')
    verify.add_argument('--products-only', action='store_true')
    export = commands.add_parser('export', help='Optional QGIS project and full-map export')
    export.add_argument('directory')
    export.add_argument('output')
    export.add_argument('--width-mm', type=float, default=1000)
    export.add_argument('--dpi', type=int, default=300)
    export.add_argument('--font-size', type=float, default=9)
    export.add_argument('--font-unit', choices=('points', 'map'), default='points')
    export.add_argument('--render-crs')
    export.add_argument('--font-family', default='Times New Roman')
    export.add_argument('--auto-font-size', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'gui':
            from .gui import run_gui
            return run_gui()
        if args.command == 'pipeline':
            from .pipeline import PipelineConfig, run_pipeline
            options = PipelineConfig.from_dict(json.loads(Path(args.config).read_text(encoding='utf-8'))) if args.config else PipelineConfig()
            if args.render:
                options.render['enabled'] = True
            def progress(event):
                if args.events:
                    with Path(args.events).open('a', encoding='utf-8') as handle:
                        handle.write(json.dumps(event, ensure_ascii=False) + '\n')
            result = run_pipeline(args.source, args.output, options, progress=progress,
                                  cancelled=lambda: bool(args.cancel_file and Path(args.cancel_file).exists()))
            result = {k: result[k] for k in ('status','output','native_summary','annotations','map')}
        elif args.command == 'from-mapgis':
            from .georef import export_native
            manifest = export_native(args.source, args.output, epsg=args.epsg, factor=args.factor,
                                     style=not args.no_style, georeference=not args.no_georef)
            result = {'status': 'PASS', 'output': manifest['output'], 'map_frame': manifest['map_frame'],
                      'summary': manifest['summary'], 'unreadable': manifest['unreadable'],
                      'missing_project_layers': manifest['missing_project_layers']}
        elif args.command == 'parse':
            result = asdict(parse_note(args.text, strict=args.strict))
        elif args.command == 'inspect':
            result = inspect_dataset(args.source, args.encoding)
        elif args.command == 'convert':
            result = convert_layer(args.source, args.output, ConversionConfig(note_field=args.note_field, encoding=args.encoding))
        elif args.command == 'run':
            config = WorkflowConfig.from_dict(json.loads(Path(args.config).read_text(encoding='utf-8'))) if args.config else WorkflowConfig()
            result = run_workflow(args.source, args.output, config)
            result = {k: result[k] for k in ('status', 'converted_layers', 'converted_records', 'changed_notes', 'spatial')}
        elif args.command == 'verify':
            result = verify_dataset(args.directory, verify_sources=not args.products_only)
        else:
            from .qgis_adapter import export_project
            result = export_project(args.directory, args.output, width_mm=args.width_mm,
                                    dpi=args.dpi, font_size=args.font_size, font_family=args.font_family,
                                    font_unit=args.font_unit, render_crs=args.render_crs,
                                    auto_font_size=args.auto_font_size)
            result = {'status': result['status'], 'qgis': result['qgis'],
                      'layers': len(result['layers']), 'rendered_labels': result['rendered_labels'],
                      'output': str(Path(args.output).resolve())}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (AnnotationError, OSError, ValueError, TypeError) as exc:
        print('mapgis-annotations: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
