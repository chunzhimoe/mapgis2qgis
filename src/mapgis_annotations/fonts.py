"""Register a bundled CJK font inside the rendering process, without OS install."""
from pathlib import Path
import shutil

from .errors import AnnotationError
from .shapefiles import sha256

FONT_PATH = Path(__file__).parent/'fonts/NotoSansCJKsc-Regular.otf'
LICENSE_PATH = FONT_PATH.parent/'OFL.txt'
PROBE = '中文地质矿产图注记五龙沟ηγδβΩT123'


def prepare_render_font(output, requested_family):
    from qgis.PyQt.QtGui import QFont, QFontDatabase, QRawFont

    font_id = QFontDatabase.addApplicationFont(str(FONT_PATH))
    families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    if not families:
        raise AnnotationError('Cannot load bundled Chinese font: ' + str(FONT_PATH))
    bundled_family = families[0]
    bundled = QRawFont(str(FONT_PATH), 12)
    if not bundled.isValid() or any(index == 0 for index in bundled.glyphIndexesForString(PROBE)):
        raise AnnotationError('Bundled font lacks required Chinese/Greek glyphs')
    requested = requested_family or bundled_family
    font = QFont(requested)
    raw = QRawFont.fromFont(font)
    available = requested in QFontDatabase().families()
    fallback = not available or not raw.isValid() or any(index == 0 for index in raw.glyphIndexesForString(PROBE))
    if fallback:
        font = QFont(bundled_family)
    folder = Path(output)/'fonts'
    folder.mkdir()
    shutil.copyfile(FONT_PATH, folder/FONT_PATH.name)
    shutil.copyfile(LICENSE_PATH, folder/LICENSE_PATH.name)
    (folder/'README.txt').write_text('Noto Sans CJK SC is bundled under SIL OFL 1.1.\n'
        'MapGIS2QGIS registers this font automatically for rendering.\n'
        'For opening map.qgz in an external QGIS, install this OTF font if the font is unavailable.\n', encoding='utf-8')
    return font, {'requested_family':requested, 'family':font.family(), 'fallback_used':fallback,
                  'bundled_family':bundled_family, 'probe':PROBE, 'probe_glyphs_verified':True,
                  'font_file':'fonts/'+FONT_PATH.name, 'font_sha256':sha256(FONT_PATH)}
