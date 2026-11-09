"""Run in PyQGIS: synthetic second-region export and relocated real-map QA."""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

import shapefile
from pyproj import CRS
from mapgis_annotations import AnnotationError, run_workflow
from mapgis_annotations.qgis_adapter import export_project
from qgis.core import QgsApplication, QgsProject


def validate(real_export, report_path):
    with tempfile.TemporaryDirectory(prefix='mapgis-generic-smoke-') as temporary:
        root = Path(temporary)
        source = root/'input'
        source.mkdir()
        for name, field, xy in [('labels_other', 'TEXT', (1000,1000)), ('symbols_other','TITLE',(100,100))]:
            with shapefile.Writer(str(source/name), shapeType=1, encoding='utf-8') as writer:
                writer.field(field, 'C', 60)
                for dx, note in [(0, 'ROCK'), (10, 'Unit#-2')]:
                    writer.point(xy[0]+dx, xy[1])
                    writer.record(note)
            (source/(name+'.cpg')).write_text('UTF-8')
            (source/(name+'.prj')).write_text(CRS.from_epsg(3857).to_wkt(version='WKT1_ESRI'))
        with shapefile.Writer(str(source/'areas_other'), shapeType=5) as writer:
            writer.field('ID','N')
            writer.poly([[(990,990),(990,1020),(1030,1020),(1030,990),(990,990)]])
            writer.record(99)
        (source/'areas_other.prj').write_text(CRS.from_epsg(3857).to_wkt(version='WKT1_ESRI'))
        with shapefile.Writer(str(source/'unlocated'), shapeType=1) as writer:
            writer.field('ID','N')
            writer.point(2,3)
            writer.record(1)
        with shapefile.Writer(str(source/'empty'), shapeType=3) as writer:
            writer.field('ID','N')
        config = {'annotation_layers':['labels_other','symbols_other'],
                  'conversion':{'note_fields':{'labels_other':'TEXT','symbols_other':'TITLE'}},
                  'pairing':{'legend_layer':'symbols_other','target_layers':['labels_other'],
                             'rock_pattern':'ROCK','age_pattern':'Unit#-[0-9]+',
                             'min_dx':1,'max_dx':30,'max_dy':3}}
        run_workflow(source, root/'processed', config)
        existing = QgsApplication.instance()
        try:
            export_project(root/'processed', root/'strict', width_mm=300, dpi=96)
            raise AssertionError('Missing CRS must fail in strict mode')
        except AnnotationError as error:
            assert 'requires a CRS' in str(error)
        assert not (root/'strict').exists()
        result = export_project(root/'processed', root/'export', width_mm=300, dpi=96,
                                missing_crs='exclude', details=[{'name':'sample','layer':'labels_other',
                                'field':'DISPLAY_H','text':'ROCKUnit<sub>2</sub>', 'padding':[20,20,20,20]}])
        assert result['status'] == 'PASS' and result['rendered_labels'] == 2
        assert {e['reason'] for e in result['excluded_layers']} == {'MISSING_CRS','EMPTY_LAYER'}
        assert len(result['details']) == 1 and (root/'export/overview.png').exists()
        assert (root/'export/data/layers/unlocated/unlocated.shp').is_file()
        assert QgsApplication.instance() is existing
        try:
            export_project(root/'processed', root/'failed_export', max_pixels=10, missing_crs='exclude')
            raise AssertionError('Pixel budget not enforced')
        except AnnotationError as error:
            assert 'pixel budget' in str(error)
        assert not (root/'failed_export').exists()
        assert QgsApplication.instance() is existing
        # Relocate the actual exported map, without access through old paths.
        relocated = root/'relocated'
        shutil.copytree(real_export, relocated)
        exported = json.loads((relocated/'export.json').read_text())
        for relative, expected in exported['product_sha256'].items():
            assert hashlib.sha256((relocated/relative).read_bytes()).hexdigest() == expected
        with zipfile.ZipFile(relocated/'map.qgz') as bundle:
            name = next(n for n in bundle.namelist() if n.endswith('.qgs'))
            xml = ET.fromstring(bundle.read(name))
            for item in xml.findall('./projectlayers/maplayer/datasource'):
                datasource = item.text.split('|')[0]
                assert not Path(datasource).is_absolute(), datasource
                assert (relocated/datasource).resolve().is_relative_to(relocated.resolve())
                assert (relocated/datasource).is_file()
        project = QgsProject()
        assert project.read(str(relocated/'map.qgz'))
        assert len(project.mapLayers()) == len(exported['layers']) == 31
        assert all(layer.isValid() for layer in project.mapLayers().values())
        project.clear()
        executable = Path(sys.prefix)/'bin/pdftotext'
        text = subprocess.run([str(executable), '-raw', str(relocated/'map.pdf'), '-'],
                              check=True, capture_output=True, text=True).stdout
        text = unicodedata.normalize('NFKC', re.sub(r'\s+', '', text))
        for required in ['二长花岗岩','斑状二长花岗岩','矿产地简表','技术说明']:
            assert required in text, required
        output = {'status':'PASS','generic_crs':'EPSG:3857','generic_rendered_labels':2,
                  'existing_application_preserved':True,'failed_export_rolled_back':True,
                  'relocated_layers':31,'all_relocated_products_hash_match':True,
                  'real_rendered_labels':exported['rendered_labels'],
                  'chinese_pdf_text_verified':True,'qgis':exported['qgis']}
        report_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        print(json.dumps(output, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('real_export', type=Path)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    QgsApplication.setPrefixPath(os.environ.get('QGIS_PREFIX_PATH', sys.prefix), True)
    app = QgsApplication([], False)
    app.initQgis()
    validate(args.real_export, args.report)
    gc.collect()
    app.exitQgis()


if __name__ == '__main__':
    main()
