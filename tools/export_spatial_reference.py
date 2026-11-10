"""Create a new spatial-reference sidecar for an existing export, read-only."""
import argparse
import json
from pathlib import Path

from mapgis_annotations.errors import AnnotationError
from mapgis_annotations.spatial_reference import export_spatial_reference
from mapgis_annotations.workflow import verify_dataset


def export_existing(directory, output):
    root, output = Path(directory).resolve(), Path(output).resolve()
    if output.is_relative_to(root):
        raise AnnotationError('For an existing export, write the sidecar outside its verified product tree')
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8')) if (root/'manifest.json').is_file() else None
    native, dataset, prefix = None, None, ''
    directory = root
    source, kind = str(root), 'shp'
    rendering = None
    if manifest is not None:
        verify_dataset(root, verify_sources=False)
        dataset = manifest
        if manifest.get('kind') == 'pipeline':
            directory, prefix = root/'annotations', 'annotations'
            dataset = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
            native_path = root/'native/native_export.json'
            if native_path.is_file():
                native = json.loads(native_path.read_text(encoding='utf-8'))
            source, kind = manifest['source'], manifest['input_format']
            render_path = root/'map/export.json'
            if render_path.is_file():
                value = json.loads(render_path.read_text(encoding='utf-8'))
                rendering = {'crs_wkt':value['render_crs'], 'extent_xy':value.get('render_extent_xy')}
    elif (root/'native_export.json').is_file():
        native = json.loads((root/'native_export.json').read_text(encoding='utf-8'))
        source, kind = native['source'], 'native'
    elif (root/'export.json').is_file():
        value = json.loads((root/'export.json').read_text(encoding='utf-8'))
        directory, prefix = root/'data', 'data'
        verify_dataset(directory, verify_sources=False)
        dataset = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        rendering = {'crs_wkt':value['render_crs'], 'extent_xy':value.get('render_extent_xy')}
        kind = 'qgis_export'
    return export_spatial_reference(directory, output, dataset=dataset, native=native,
        source=source, input_format=kind, path_prefix=prefix, rendering=rendering)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = export_existing(args.directory, args.output)
    print(json.dumps({'status':'PASS', 'output':str(args.output.resolve()),
                      'main_crs_id':report['main_crs_id'], 'summary':report['summary']}, ensure_ascii=True))


if __name__ == '__main__':
    main()
