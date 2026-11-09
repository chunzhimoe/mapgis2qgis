"""Check real Qt glyphs and embedded PDF fonts, not only label placement counts."""
import gc
import json
import os
from pathlib import Path
import sys

from mapgis_annotations.runtime import configure_runtime


def paint_probe(font, output):
    from qgis.PyQt.QtGui import QImage, QColor, QPainter, QPdfWriter
    from mapgis_annotations.fonts import PROBE
    font.setPointSize(28)
    image = QImage(1600, 150, QImage.Format_ARGB32)
    image.fill(QColor('white'))
    painter = QPainter(image)
    painter.setFont(font)
    painter.setPen(QColor('black'))
    painter.drawText(20, 85, PROBE)
    painter.end()
    assert image.save(str(output/'font-probe.png'))
    pdf = QPdfWriter(str(output/'font-probe.pdf'))
    pdf.setResolution(96)
    painter = QPainter(pdf)
    painter.setFont(font)
    painter.drawText(20, 85, PROBE)
    painter.end()


def main():
    configure_runtime()
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from qgis.core import QgsApplication
    from qgis.PyQt.QtGui import QRawFont
    from mapgis_annotations.fonts import prepare_render_font, PROBE
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], False)
    app.initQgis()
    font, report = prepare_render_font(output, 'MapGIS Missing Font For Regression')
    assert report['fallback_used']
    assert report['family'] == report['bundled_family']
    glyphs = QRawFont.fromFont(font).glyphIndexesForString(PROBE)
    assert len(glyphs) == len(PROBE) and all(glyphs)
    paint_probe(font, output)
    gc.collect()
    pdf = (output/'font-probe.pdf').read_bytes()
    assert b'/FontFile' in pdf, 'The PDF must embed a font program'
    report.update(status='PASS', glyph_indexes=glyphs, pdf_font_embedded=True)
    (output/'font-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))
    del font
    gc.collect()
    app.exitQgis()


if __name__ == '__main__':
    main()
