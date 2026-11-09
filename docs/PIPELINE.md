# 完整处理流程

```sh
mapgis-annotations pipeline 原生文件夹或工程.MPJ 新输出目录 --config examples/wulonggou_pipeline.json
# 通用自动字段识别，不依赖地区命名：
mapgis-annotations pipeline 输入目录 新输出目录
mapgis-annotations verify 新输出目录
```

Python：`run_pipeline(source, output, PipelineConfig(...))`，或传入同结构字典。配置字段为`input_format`（auto/native/shp）、`native`、`annotations`、`render`、`strict_native`。既有注记配置可直接作为配置文件使用，等同于放在annotations中。渲染默认关闭；`--render`开启，需PyQGIS。原生读取和空间功能需安装`.[spatial]`。

输出：`native/`（原生输入时）、`annotations/`、`inventory.json/.csv`、可选`map/`、根`manifest.json`。整个目录是一次原子发布；任一步失败不发布新目录，不覆盖输入。根manifest记录全部产物哈希与原始输入哈希。发布前重定位子步骤的暂存路径并重算内层哈希，最终目录可直接verify，子目录annotations也可verify。

`progress`回调接收`stage/percent`；`cancelled`回调在阶段边界检查。CLI的`--events`写JSONL，`--cancel-file`供GUI协调停止。取消不会发布输出，长渲染会在当前阶段结束后停止。

原生输入有不可读/缺失图层时默认拒绝完整流程；只有显式`strict_native=false`才允许部分转换，并在native_summary保留数量。无文字的几何图层也可处理。无效/空几何只统计，不自动修复；未安装Shapely时报告geometry_validity_checked=false。

## 渲染

render配置接受export_project的幅面、dpi、字号、字体、render_crs、missing_crs、details、title。完整流程默认missing_crs=exclude，单独export_project仍默认error。空图层不参与范围，未定位图层可排除绘制；两者的数据副本仍保留在map/data，并写入excluded_layers。

局部details最多6项。每项有唯一name（简单文件名），通过extent指定输出CRS范围，或用layer、field（默认LABEL_TXT）、text定位图元；pick为first/middle。padding为左/下/右/上四个正数，单位是输出CRS单位；size默认1600×1050。layers可指定局部可见层。生成details/*.png和overview.png，注记继续固定原坐标。examples/wulonggou_pipeline.json仅为示例，不是通用默认规则。

完整转换不意味着原始符号库、字体旋转或任意CRS被无条件恢复。结果保留相关限制和未绘制层清单，几何分析仍须检查无效面及匹配歧义。
