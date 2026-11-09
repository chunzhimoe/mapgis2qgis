# Third-party notices

`src/mapgis_annotations/native_crs.py` adapts the coordinate-header decoding
approach from [leecugb/mapgis2shp](https://github.com/leecugb/mapgis2shp),
`src/pymapgis/reader.py` at commit `c4257a6cfcdc122d8827777bddf5f2604b300cc6`.
Upstream author: Shijie Li (leecugb) and pymapgis contributors.
Upstream license: Apache License 2.0, included in `licenses/Apache-2.0.txt`.
That module is distributed under Apache-2.0; the original project files retain
their MIT license. No upstream NOTICE file was present in that revision.

Changes: isolated the header decoder from GeoPandas and NumPy, added strict
signed fractional DMS validation, preserved named geographic datums where
established by conventional indices, omitted fixed regional `towgs84` shifts,
and returned auditable candidates for the existing coordinate-validation flow.
This attribution does not imply endorsement by upstream authors.

## Bundled CJK font

`src/mapgis_annotations/fonts/NotoSansCJKsc-Regular.otf` is the unmodified Noto
Sans CJK SC Regular font from [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk),
`Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf` at commit
`f8d157532fbfaeda587e826d4cd5b21a49186f7c`.
The font is distributed under SIL Open Font License 1.1. The upstream
`Sans/LICENSE` is included in `licenses/SIL-OFL-1.1.txt` and with the font in
`src/mapgis_annotations/fonts/OFL.txt`. This open Unicode font supplies Chinese
and Greek glyphs; it does not recreate a missing proprietary MapGIS symbol font.
