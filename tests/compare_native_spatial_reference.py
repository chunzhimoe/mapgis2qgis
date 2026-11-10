"""Compare a new metadata-enabled pipeline with a supplied native baseline."""
import argparse
import json
from pathlib import Path

from mapgis_annotations import run_pipeline, verify_dataset
from mapgis_annotations.shapefiles import sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('baseline_native', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    baseline = json.loads((args.baseline_native/'native_export.json').read_text(encoding='utf-8'))
    result = json.loads((args.output/'manifest.json').read_text(encoding='utf-8')) if args.verify_only else \
        run_pipeline(args.source, args.output, {'strict_native':False})
    reference = json.loads((args.output/'spatial_reference.json').read_text(encoding='utf-8'))
    assert result['native_summary']['layers'] == baseline['summary']['layers']
    assert result['native_summary']['features'] == baseline['summary']['features']
    assert reference['summary']['with_crs'] == baseline['summary']['with_crs']
    assert reference['summary']['without_crs'] == sorted(baseline['summary']['without_crs'])
    components = 0
    for name, layer in baseline['layers'].items():
        assert reference['layers'][name]['native_conversion']['factor'] == layer['factor']
        for filename, expected in layer['products'].items():
            assert sha256(args.baseline_native/filename) == expected
            actual = args.output/'native'/filename
            previous = args.baseline_native/filename
            assert sha256(actual) == expected, {
                'file':filename, 'new_bytes':actual.stat().st_size, 'old_bytes':previous.stat().st_size,
                'different_offsets':[i for i,(a,b) in enumerate(zip(actual.read_bytes(), previous.read_bytes())) if a != b][:20]}
            components += 1
    verify_dataset(args.output)
    verify_dataset(args.output/'annotations')
    report = {'status':'PASS', 'layers':result['native_summary']['layers'],
              'features':result['native_summary']['features'], 'metadata_summary':reference['summary'],
              'unchanged_shp_components':components, 'factors_preserved':True,
              'source_and_product_hashes_verified':True}
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
