from pathlib import Path
import tempfile
import unittest
import shapefile

from mapgis_annotations import AnnotationError, ConversionConfig, convert_layer, parse_note


class ParserTests(unittest.TestCase):
    def test_scripts_and_baseline_reset(self):
        note = parse_note('Pt#-1#=J#-2#+2#=(mb)')
        self.assertEqual(note.unicode, 'Pt₁J₂²(mb)')
        self.assertEqual(note.html, 'Pt<sub>1</sub>J<sub>2</sub><sup>2</sup>(mb)')

    def test_escape_spaces_and_fraction(self):
        self.assertEqual(parse_note('<岩 & A  B>').html, '&lt;岩&#160;&amp;&#160;A&#160;&#160;B&gt;')
        note = parse_note('/419.9±2.0/U—Pb/')
        self.assertEqual(note.plain, '419.9±2.0 / U—Pb')
        self.assertEqual(note.kind, 'FRACTION')
        self.assertIn('<sub>U—Pb</sub>', note.html)

    def test_unknown_not_silently_removed(self):
        self.assertIn('UNKNOWN_CONTROL', parse_note('A#?B').warnings)
        self.assertEqual(parse_note('A#?B').plain, 'A#?B')
        with self.assertRaises(AnnotationError):
            parse_note('A#?B', strict=True)

    def test_unicode_fallback_and_empty(self):
        self.assertEqual(parse_note(None).kind, 'EMPTY')
        self.assertIn('EMPTY_CONTROL', parse_note('#+').warnings)
        self.assertIn('HTML_REQUIRED', parse_note('A#-B').warnings)
        self.assertEqual(parse_note('A#-B').html, 'A<sub>B</sub>')


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'input' / 'unrelated_region.shp'
        self.source.parent.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def make_source(self, text='T#-2', encoding='gbk', field='说明'):
        with shapefile.Writer(str(self.source), shapeType=shapefile.POINT, encoding=encoding) as writer:
            writer.field('ID', 'N', 8)
            writer.field(field, 'C', 254)
            writer.field('DETAILS' if encoding == 'utf-8' else '岩石描述', 'C', 80)
            for xy in [(1.25, 4.5), (9.0, -3.25)]:
                writer.point(*xy)
                writer.record(7, text, '中文岩性')
        self.source.with_suffix('.cpg').write_text(encoding)

    def test_arbitrary_field_region_duplicate_ids_and_geometry(self):
        self.make_source()
        original = self.source.read_bytes()
        destination = self.root / 'output'
        report = convert_layer(self.source, destination, ConversionConfig(note_field='说明'))
        self.assertEqual(report['records'], 2)
        self.assertEqual((destination / self.source.name).read_bytes(), original)
        with shapefile.Reader(str(destination / self.source.name), encoding='utf-8') as reader:
            records = reader.records()
            self.assertEqual([r['SRC_FID'] for r in records], [0, 1])
            self.assertEqual([r['ID'] for r in records], [7, 7])
            self.assertEqual(records[0][report['output_note_field']], 'T₂')
            self.assertEqual(records[0][report['field_map']['岩石描述']], '中文岩性')
        with self.assertRaises(AnnotationError):
            convert_layer(self.source, destination, ConversionConfig(note_field='说明'))

    def test_auto_field_utf8(self):
        self.make_source(encoding='utf-8', field='TEXT')
        self.assertEqual(convert_layer(self.source, self.root/'out')['encoding'], 'utf-8')

    def test_uppercase_companions(self):
        self.make_source()
        for path in list(self.source.parent.iterdir()):
            path.rename(path.with_suffix(path.suffix.upper()))
        result = convert_layer(self.source.with_suffix('.SHP'), self.root/'out', ConversionConfig(note_field='说明'))
        self.assertEqual(result['records'], 2)

    def test_overflow_is_atomic_and_does_not_truncate(self):
        self.make_source(text='岩'*100)
        with self.assertRaisesRegex(AnnotationError, 'overflow'):
            convert_layer(self.source, self.root/'out', ConversionConfig(note_field='说明'))
        self.assertFalse((self.root/'out').exists())

    def test_deleted_rows_rejected(self):
        self.make_source()
        path = self.source.with_suffix('.dbf')
        data = bytearray(path.read_bytes())
        header_length = int.from_bytes(data[8:10], 'little')
        data[header_length] = ord('*')
        path.write_bytes(data)
        with self.assertRaisesRegex(AnnotationError, 'Deleted'):
            convert_layer(self.source, self.root/'out', ConversionConfig(note_field='说明'))


if __name__ == '__main__':
    unittest.main()
