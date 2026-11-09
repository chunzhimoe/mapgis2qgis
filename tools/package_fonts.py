"""Build a font-only compatibility kit for existing 0.4.0/0.4.1 installations."""
import argparse
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def package_fonts(output):
    folder = ROOT/'src/mapgis_annotations/fonts'
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ('NotoSansCJKsc-Regular.otf','OFL.txt','SOURCE.txt'):
            archive.write(folder/name, 'MapGIS2QGIS-fonts/'+name)
        for source, target in (('01_generic_full_pdf.json','generic_noto.json'),
                               ('06_wulonggou_full.json','wulonggou_noto.json')):
            config = json.loads((ROOT/'examples/profiles'/source).read_text(encoding='utf-8'))
            config['render']['font_family'] = 'Noto Sans CJK SC'
            archive.writestr('MapGIS2QGIS-fonts/'+target,
                             json.dumps(config, ensure_ascii=False, indent=2)+'\n')
        archive.writestr('MapGIS2QGIS-fonts/安装说明.txt',
            '现有 0.4.0/0.4.1 中文字体兼容包\n\n'
            'Windows：解压后双击 NotoSansCJKsc-Regular.otf，点击安装。\n'
            '重新打开工作台；五龙沟选择 wulonggou_noto.json，其他图件可先用 generic_noto.json。\n'
            '选择新的输出目录重新导出，PDF 位于 map/map.pdf。\n'
            '外部 QGIS 打开工程同样需要能找到此字体。\n'
            '0.4.2 起安装包内置此字体，工作台渲染会自动加载，无需手动安装。\n'
            '字体为上游未修改的 Noto Sans CJK SC，许可证见 OFL.txt，来源见 SOURCE.txt。\n'
            '本字体提供通用 Unicode 中文/希腊字形，不恢复 MapGIS 专用符号。\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'dist/MapGIS2QGIS-fonts.zip')
    print(package_fonts(parser.parse_args().output))
