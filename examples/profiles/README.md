# 可直接选择的处理配置

下载整个 `MapGIS2QGIS-profiles.zip` 并解压，在 GUI 第三行「处理配置 → 选择 JSON」选择一个文件，然后核对绘图勾选、幅宽、DPI、字号，选择新的输出目录并开始转换。配置文件不填写输入/输出路径；路径在界面选择。JSON 不支持注释，说明集中在本文件。

| 文件 | 适用场景 | PDF/QGIS 工程 | 不可读或缺失的原生层 |
|---|---|---|---|
| `01_generic_full_pdf.json` | 通用完整流程，建议先选这个 | 生成，600 mm / 300 DPI | 跳过并记录 |
| `02_strict_full_pdf.json` | 完整性核查，要求全部原生层可读 | 生成，600 mm / 300 DPI | 停止整个任务 |
| `03_quick_preview_pdf.json` | 先检查转换和地图位置 | 生成，300 mm / 96 DPI | 跳过并记录 |
| `04_data_only.json` | 只做坐标/标准注记和数据导出 | 不生成 | 跳过并记录 |
| `05_shp_full_pdf.json` | 输入是同一目录下的 SHP 文件 | 生成，600 mm / 300 DPI | 不经过原生读取 |
| `06_wulonggou_full.json` | 已验证的五龙沟图层命名，含岩性时代连排、点面关系和两个局部图 | 生成，1000 mm / 300 DPI | 跳过并记录；配对必需层仍须存在 |

## 生成结果放在哪里

```text
你选择的新输出目录/
  native/                   原生转出的 SHP；SHP 输入不生成这个目录
    native_export.json      坐标判定、unreadable、missing_project_layers
  annotations/              标准注记和关联成果
  map/
    map.pdf                 全图 PDF
    map.png                 全图图片
    map.qgz                 QGIS 工程
    preview.png             预览
    details/                配置了局部图时生成
  manifest.json             总体核验清单
```

`strict_native=false` 会继续转换可读层，未读入的层不会恢复。分析前检查 `native/native_export.json` 的 `unreadable` 和 `missing_project_layers`。读不出的原因仍需根据原文件核查。

`missing_crs=exclude` 仅排除没有可靠 CRS 的图层绘图，原生转换和注记成果中仍保留数据；结果 `manifest.json` 的 `map.excluded_layers` 列出未绘制层。全部图层均无可靠 CRS 时无法绘图，需要依据原资料设置正确坐标系，不能任意填 EPSG。

## 自动坐标、字段与通用性

- `input_format=auto` 自动识别原生或 SHP；目录同时含两类数据时须明确选择 `native` 或 `shp`。
- 没有预设 EPSG 或换算系数，默认根据原生头部和坐标证据判定；SHP 使用自身 `.prj`。
- `note_field=null` 和 `annotation_layers=null` 表示自动识别注记字段/图层。字段名不常见时，在 `conversion.note_field` 或 `conversion.note_fields` 明确指定。
- `encoding=null` 使用 `.cpg`，缺少 `.cpg` 时按库的 GB18030 后备规则读取；编码不匹配时应根据源数据指定。
- 01–05 不绑定地区/图层名，不自动执行岩性时代配对和点面关联。需要这些操作时，按真实图层名添加 `pairing`、`crosswalks`。
- 06 使用 `地质图例_点`、`5万地质矿产图_点`、`5万地质矿产图_区`，仅在图层名和内容对应时选用。局部图依赖「二长花岗岩」和已连排的 `ηγT₂`；其他图件应修改这些规则。
- `font_unit=points` 为纸面字号；06 的 `map` 字号按输出 CRS 单位。通用配置使用跨平台字体族 `sans-serif`。

## GUI 和命令行的优先级

GUI 选择配置后会显示其中的幅宽/DPI/字号/绘图开关；点击开始时，以界面里的这些值为准。EPSG 和换算系数输入框有值时覆盖配置；空白时使用配置或自动判定。0.4.1 起，加载没有写出绘图参数的简化 JSON 会保留当前界面设置。

这些完整配置也可用于 0.4.0：选中后再次确认绘图勾选。旧版加载简化 JSON 会重置绘图设置，建议用 01 或 03；旧 GUI 总是自动判断输入类型，目录混有原生和 SHP 时应把目标输入单独放一个目录，或更新到 0.4.1。

命令行直接使用配置中的参数：

```sh
mapgis-annotations pipeline 输入目录 新输出目录 --config 01_generic_full_pdf.json
```

配置中的 `details=[]` 表示生成全图，未指定局部图。幅面过大或图幅过长触发像素上限时，可改用 03，或降低 DPI/幅宽。整个任务验收通过后才发布结果，失败时检查 GUI「运行记录」。
