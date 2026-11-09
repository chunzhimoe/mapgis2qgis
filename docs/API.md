# API与配置参考

| API | 输入 | 返回 |
|---|---|---|
| parse_note(raw, strict=False) | 字符串或None | ParsedNote(raw, unicode, plain, html, kind, warnings) |
| inspect_dataset(directory, encoding=None) | SHP目录 | 字段/几何/数量/编码/PRJ情况 |
| convert_layer(source, output, config=None) | 单点SHP、新目录、ConversionConfig | 统计、字段映射、哈希 |
| run_workflow(source, output, config=None) | 数据目录、新目录、WorkflowConfig或字典 | 完整manifest |
| verify_dataset(directory, verify_sources=True) | workflow目录 | 明确核验范围的报告 |
| pair_annotations(points, crs, config=None, allowed_pairs=None) | AnnotationPoint序列、真实CRS | pairs/unresolved/display及CRS |
| crosswalk(points, polygons, point_crs, polygon_crs, invalid_policy='exclude') | 点序列、(原行号, Shapely几何)序列 | 全部匹配/未匹配及无效面 |
| export_native(source, output, epsg=None, factor=None, style=True, georeference=True) | 原生图件文件夹、.mpj或单个.wt/.wl/.wp；新目录 | manifest（每层判定、系数、EPSG/完整WKT、候选警告、经纬度窗口、属性经纬度残差、哈希），同时写native_export.json |
| read_native_layer(path, style=True) | .wt/.wl/.wp | NativeLayer：kind、fields、features=[(几何, 属性值)]、slots、header_parameters（投影/椭球/比例尺/中央经线/原点/标准纬线/假东假北）；坐标为存储单位，不依赖pyproj |
| read_mpj_paths(path) | .mpj | 按工程所在目录解析的图层路径（含缺失文件） |
| write_shapefile(base, kind, fields, features, prj=None) | NativeField列表、要素 | 实际写出的字段定义（数值字段可能被加宽） |

可选QGIS：`from mapgis_annotations.qgis_adapter import export_project`。完整签名见源码。AnnotationError表示输入/配置不满足无损转换前提；MissingDependencyError表示缺少可选运行环境；NativeFormatError（AnnotationError子类）表示不是可读的MapGIS 6.x原生文件，或文件被截断、损坏。CLI成功退出0，预期输入错误退出2。

from-mapgis：`source output [--epsg N] [--factor F] [--no-georef] [--no-style]`。输出为扁平SHP目录，可直接作为run的输入。--no-georef保持图面单位，不写.prj，不需要pyproj；--epsg/--factor覆盖主图框（也可用于头部椭球未知的图）。每层判定写在native_export.json的decision字段：header frame、inside map frame、factor INFERRED、no frame fits、empty layer。

0.3.0：支持经纬度、Albers、Lambert、TM；经纬度保持度，`--epsg` 指定地理 CRS 时 `--factor` 只能为1或省略。factor必须有限且大于0。地理图框不向其他页面坐标图层传播，也不参与米制比例尺推断。

`native_export.json` 每层新增：`crs_wkt`（实际接受的完整CRS）、`header_candidate.reason/warnings`（候选来源与索引/基准限制）。`header.scale`等非有限头部值记为null。自定义CRS可有PRJ但没有EPSG；`summary.with_crs/without_crs`按实际CRS统计。原有字段`epsg`、`crs`、`factor`、`decision`保留。

`lonlat_attribute_check.metric`为`max_axis_distance`（投影坐标的最大轴向差，保留原口径）或`geodesic`（经纬度的椭球测地距离），`median_m`均以米计。不对已知或未知基准施加固定区域转换参数。

ConversionConfig：note_field全局字段；note_fields按图层覆盖；encoding覆盖编码，否则cpg、GB18030后备；strict_controls是否拒绝未知控制；field_aliases配置输出短名。

WorkflowConfig：conversion、annotation_layers、pairing、crosswalks。pairing包含legend_layer、target_layers、crs_overrides和PairingConfig参数。crosswalks每项points、polygons、invalid_policy及可选point_crs/polygon_crs。

PairingConfig：min_dx/max_dx/max_dy默认20/500/35米；rock_pattern/age_pattern为完整匹配正则；working_crs为距离计算投影；require_legend默认True。默认地质正则仅用于候选识别，不建立年代规范。

display以原行号为键，JSON中键为字符串；空字符串表示合并显示，原行保留。pairs包含rock_fid、age_fid、原代号、HTML和距离；unresolved包含未配对时代及全部候选行号。

既有脚本映射：parse_note → 同名函数（具名结果）；convert_layer → 参数化同名函数；join_era_labels → pair_annotations及QGIS适配；spatial_crosswalk → crosswalk；export_map → qgis_adapter.export_project。
