import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from mapgis_annotations.pipeline import PipelineConfig

ROOT = Path(__file__).resolve().parents[1]


class FontDistribution(unittest.TestCase):
    def test_exact_upstream_font_license_and_usable_compatibility_profiles(self):
        font = ROOT/'src/mapgis_annotations/fonts/NotoSansCJKsc-Regular.otf'
        digest = '2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b'
        self.assertEqual(hashlib.sha256(font.read_bytes()).hexdigest(), digest)
        spec = importlib.util.spec_from_file_location('package_fonts', ROOT/'tools/package_fonts.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            path = module.package_fonts(Path(temporary)/'fonts.zip')
            with zipfile.ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read('MapGIS2QGIS-fonts/NotoSansCJKsc-Regular.otf'), font.read_bytes())
                self.assertEqual(archive.read('MapGIS2QGIS-fonts/OFL.txt'), (ROOT/'licenses/SIL-OFL-1.1.txt').read_bytes())
                for name in ('generic_noto.json','wulonggou_noto.json'):
                    config = PipelineConfig.from_dict(json.loads(archive.read('MapGIS2QGIS-fonts/'+name)))
                    config.validate()
                    self.assertEqual(config.render['font_family'], 'Noto Sans CJK SC')
