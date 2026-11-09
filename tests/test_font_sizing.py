import math
import unittest

from mapgis_annotations import AnnotationError
from mapgis_annotations.font_sizing import estimate_font_size


class AdaptiveFontSize(unittest.TestCase):
    def test_dense_and_long_labels_shrink_with_fixed_anchors(self):
        labels = [(x,y,'地质') for x in range(10) for y in range(10)]
        before = list(labels)
        dense = estimate_font_size(labels, 10)
        long = estimate_font_size([(x,y,'成矿地质构造') for x,y,_ in labels], 10)
        self.assertLess(dense['font_size'], 1)
        self.assertLessEqual(long['font_size'], dense['font_size'])
        self.assertEqual(labels, before)

    def test_units_and_translation_do_not_change_decision(self):
        labels = [(x,y,'ηγT<sub>2</sub>') for x in range(12) for y in range(5)]
        original = estimate_font_size(labels, 5)['font_size']
        scaled = estimate_font_size([(x*1000+1e7,y*1000-1e7,t) for x,y,t in labels], 5000)
        self.assertAlmostEqual(scaled['font_size'], original*1000)

    def test_sparse_empty_and_coincident_anchors_are_reported(self):
        self.assertEqual(estimate_font_size([], 9)['font_size'], 9)
        result = estimate_font_size([(0,0,'中文'),(0,0,'时代'),(0,0,'')], 9)
        self.assertEqual(result['duplicate_anchors'], 1)
        self.assertEqual(result['labels'], 2)
        self.assertFalse(result['estimated'])
        result = estimate_font_size([(0,0,'A'),(1000,1000,'B')], 9)
        self.assertEqual(result['font_size'], 9)

    def test_invalid_numeric_values_fail(self):
        for maximum in (0, -1, math.inf, math.nan):
            with self.assertRaises(AnnotationError):
                estimate_font_size([], maximum)
        with self.assertRaises(AnnotationError):
            estimate_font_size([(math.nan,0,'A')], 9)
