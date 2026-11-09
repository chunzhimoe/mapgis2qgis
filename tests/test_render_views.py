import unittest
from mapgis_annotations import AnnotationError
from mapgis_annotations.render_views import validate_views


class ViewValidation(unittest.TestCase):
    def test_generic_selection_and_extent(self):
        validate_views([{'name': 'detail', 'layer': 'arbitrary', 'text': 'X'},
                        {'name': 'area', 'extent': [10, 20, 30, 40]}])

    def test_invalid_paths_bounds_and_budget(self):
        for view in ({'name': '../escape', 'extent': [0, 0, 1, 1]},
                     {'name': 'bad', 'extent': [1, 0, 0, 1]},
                     {'name': 'big', 'extent': [0, 0, 1, 1], 'size': [100000, 100000]},
                     {'name': 'none'}, {'name': 'nan', 'layer': 'x', 'text': 'y', 'padding': [1, 1, 1, float('nan')]}):
            with self.subTest(view=view), self.assertRaises(AnnotationError):
                validate_views([view])
