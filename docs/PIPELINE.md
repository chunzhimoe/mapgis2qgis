# 完整处理流程

```sh
mapgis-annotations pipeline 原生文件夹或工程.MPJ 新输出目录 --config examples/wulonggou_pipeline.json
# 通用自动字段识别，不依赖地区命名：
mapgis-annotations pipeline 输入目录 新输出目录
mapgis-annotations verify 新输出目录
```

Python：`run_pipeline(source, output, PipelineConfig(...))`，或传入同结构字典。配置字段为`input_format`（auto/native/shp）、`native`、`annotations`、`render`、`strict_native`。既有注记配置可直接作为配置文件使用，等同于放在annotations中。渲染默认关闭；`--render`开启，需PyQGIS。原生读取和空间功能需安装`.[spatial]`。

0.4.5 增加显式多文件选择，Python 可传 `run_pipeline(['labels.WT', 'faults.WL'], output, config)`，`export_native` 同样接受文件列表。CLI 使用 UTF-8 JSON 路径数组：`mapgis-annotations pipeline 新输出目录 --source-list selected_files.json`，不能同时填写单个 source。列表只允许文件，原生与SHP不能混选，重复路径去重；MPJ展开其引用层，文件夹与单文件旧调用不变。选择同属一张图的图层会生成一套成果，不是逐文件独立批处理。

多选时根清单和原生清单的 `source` 为绝对路径数组，原有单路径调用仍是字符串；`source_sha256` 保持路径到哈希的字典。SHP选择自动携带配套文件，并在 `input/` 保留选中输入的原样副本，确保标准注记清单在暂存目录清理后仍可核验。所有原始输入哈希继续检查；配置中的图层名仍按最终清单命名填写。

输出：`native/`（原生输入时）、`annotations/`、`inventory.json/.csv`、可选`map/`、根`manifest.json`。整个目录是一次原子发布；任一步失败不发布新目录，不覆盖输入。根manifest记录全部产物哈希与原始输入哈希。发布前重定位子步骤的暂存路径并重算内层哈希，最终目录可直接verify，子目录annotations也可verify。

0.4.6 默认增加根目录 `spatial_reference.json`，并纳入产物哈希核验；原生及 QGIS 导出目录也各保存自身范围的空间参考 JSON。它记录实际输出 PRJ、完整 WKT/标准 PROJJSON、单位、轴顺序、原生换算和制图 CRS，不变更数据。JSON 结构、逐层缺失/无效状态和旧成果补导出见 [SPATIAL_REFERENCE.md](SPATIAL_REFERENCE.md)。

`progress`回调接收`stage/percent`；`cancelled`回调在阶段边界检查。CLI的`--events`写JSONL，`--cancel-file`供GUI协调停止。取消不会发布输出，长渲染会在当前阶段结束后停止。

原生输入有不可读/缺失图层时默认拒绝完整流程；只有显式`strict_native=false`才允许部分转换，并在native_summary保留数量。无文字的几何图层也可处理。无效/空几何只统计，不自动修复；未安装Shapely时报告geometry_validity_checked=false。

## 渲染

render配置接受export_project的幅面、dpi、字号、字体、render_crs、missing_crs、details、title。完整流程默认missing_crs=exclude，单独export_project仍默认error。空图层不参与范围，未定位图层可排除绘制；两者的数据副本仍保留在map/data，并写入excluded_layers。

局部details最多6项。每项有唯一name（简单文件名），通过extent指定输出CRS范围，或用layer、field（默认LABEL_TXT）、text定位图元；pick为first/middle。padding为左/下/右/上四个正数，单位是输出CRS单位；size默认1600×1050。layers可指定局部可见层。生成details/*.png和overview.png，注记继续固定原坐标。examples/wulonggou_pipeline.json仅为示例，不是通用默认规则。

完整转换不意味着原始符号库、字体旋转或任意CRS被无条件恢复。结果保留相关限制和未绘制层清单，几何分析仍须检查无效面及匹配歧义。
