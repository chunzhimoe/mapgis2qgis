from pathlib import Path
import tempfile
import unittest

from mapgis_annotations import AnnotationError
from mapgis_annotations.qgis_adapter import export_project


class OptionalExportTests(unittest.TestCase):
    def test_invalid_resolution_rejected_without_starting_qgis(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for dpi in (0, .5, float('nan')):
                with self.assertRaises(AnnotationError):
                    export_project(root/'dataset', root/'output', dpi=dpi)
                self.assertFalse((root/'output').exists())

    def test_invalid_units_rejected_without_gis_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(AnnotationError):
                export_project(root/'dataset', root/'output', font_unit='miles')
            self.assertFalse((root/'output').exists())
