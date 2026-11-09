"""Explicit real-data regression, invoked with a local source and new output.

No input data are bundled in the library or test distribution.
"""
import argparse
import importlib.util
import json
import csv
from pathlib import Path

import shapefile
from mapgis_annotations import WorkflowConfig, run_workflow, verify_dataset, parse_note
from mapgis_annotations.shapefiles import open_reader


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--legacy-script', type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    legacy_script = args.legacy_script or project/'test/convert_wulonggou_annotations.py'
    if not legacy_script.is_file():
        parser.error('Provide --legacy-script pointing to the original verified converter')
    profile = json.loads((Path(__file__).resolve().parents[1]/'examples/wulonggou.json').read_text())
    config = WorkflowConfig.from_dict(profile)
    manifest = run_workflow(args.source, args.output, config)
    spec = importlib.util.spec_from_file_location('legacy_wulonggou', legacy_script)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    checked = 0
    for name, layer in manifest['layers'].items():
        if not layer['converted']:
            continue
        with open_reader(args.source/(name+'.shp'), 'gbk') as original, open_reader(args.output/layer['path'], 'utf-8') as converted:
            old, new = original.records(), converted.records()
            assert len(old) == len(new)
            field_map = layer['conversion']['field_map']
            for fid, (before, after) in enumerate(zip(old, new)):
                parsed = parse_note(before['注记'])
                reference = legacy.parse_note(before['注记'])
                assert (parsed.unicode, parsed.plain, parsed.html) == reference[:3], (name, fid)
                assert after['SRC_FID'] == fid and after['RAW_NOTE'] == before['注记']
                for field, mapped in field_map.items():
                    assert after[mapped] == (parsed.unicode if field == '注记' else before[field])
                checked += 1
    assert manifest['converted_layers'] == 15
    assert checked == manifest['converted_records'] == 20897
    assert manifest['changed_notes'] == 4489
    old_crosswalk = args.source.parent/'标准注记_QGIS/主图_注记点与地质面对应.csv'
    spatial_regression = None
    if old_crosswalk.exists():
        with old_crosswalk.open(encoding='utf-8-sig', newline='') as handle:
            reference = {(int(r['PT_SRC_FID']), int(r['POLY_FID'])) for r in csv.DictReader(handle)
                         if int(r['POLY_VALID']) == 1}
        cross = json.loads((args.output/'crosswalk_0.json').read_text())
        actual = {(r['point_fid'], r['polygon_fid']) for r in cross['rows'] if r['polygon_fid'] is not None}
        assert actual == reference, ('Valid polygon crosswalk changed', len(actual-reference), len(reference-actual))
        spatial_regression = {'valid_polygon_pairs': len(actual), 'comparison': 'ALL_MATCH',
                              'invalid_polygons_excluded': len(cross['invalid_polygon_fids']),
                              'unmatched_points_preserved': sum(r['status'] == 'UNMATCHED' for r in cross['rows'])}
    summary = {'status': 'PASS', 'converted_layers': 15, 'records': checked,
               'changed_notes': manifest['changed_notes'], 'legacy_text_comparison': 'ALL_MATCH',
               'spatial': manifest['spatial'], 'spatial_regression': spatial_regression,
               'verification': verify_dataset(args.output)}
    (args.output/'regression.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
