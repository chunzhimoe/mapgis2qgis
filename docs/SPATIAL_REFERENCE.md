# 空间参考 JSON

0.4.6 起，完整转换默认生成 `输出目录/spatial_reference.json`，不需要增加处理配置。GUI 完成后点击「空间参考 JSON」打开，运行记录也显示路径。原生导出还在 `native/spatial_reference.json` 保留原生坐标换算依据；生成地图时，`map/spatial_reference.json` 记录地图的数据图层 CRS 和制图 CRS。单独 `from-mapgis` 或 `export` 命令也会在各自输出目录生成该文件。

这是一份空间参考汇总，不是处理配置文件，也不是对所有图层强制指定同一个 CRS。`crs_definitions` 中每个 `projjson` 才是可由 PROJ/PyProj 读取的标准 PROJJSON；无 EPSG 编码的有效自定义投影仍保留完整 WKT 和 PROJJSON。不以精简 PROJ 字符串替代完整定义。

## 主要字段

| 字段 | 含义 |
| --- | --- |
| `format_version` / `generator` | 汇总结构版本、生成库及版本 |
| `main_crs_id` | 已知主图框对应的数据 CRS；单一 SHP CRS 可自动作为主参考，混合 SHP CRS 不选一个冒充全部 |
| `crs_definitions` | 按内部 ID 索引的完整定义：名称、100% 匹配的 `auth_id`、WKT、标准 PROJJSON、单位及正式轴信息 |
| `data_crs_status` | `uniform`、`partial`、`mixed` 或 `unassigned`；结合逐层状态解读 |
| `summary` | 图层数、可解析 CRS 数、未定义/无效/未解析层清单及不同数据 CRS 数 |
| `layers` | 各输出图层路径、原来源、CRS ID、PRJ 路径/哈希/解码方式、原生换算记录 |
| `layers.*.native_conversion` | 原生转换已使用的 `factor`、判定原因、原头部及候选警告；已有 SHP 输入无法追溯原生换算时为 `null` |
| `native_map_frame` | 原生主图框候选、系数、范围与判断依据；其中 `layers` 是形成图框的候选组层数，最终分配数量见 `summary.with_crs` |
| `input_issues` | 允许部分转换时的原生不可读文件及工程缺失层，保持审计信息 |
| `render_reference` | 实际制图 CRS ID 与版面地图范围 `[xmin,ymin,xmax,ymax]`；不改变源数据图层 CRS |
| `dataset_root` | 相对 JSON 所在目录的数据根目录；`layers.*.path/prj` 相对这个根目录，成果整体移动后仍可定位 |

每层 `crs_status` 为 `defined`、`missing`、`invalid` 或 `unparsed`。`defined` 表示声明可解析，不代表已证明原始地理位置绝对正确。未定位层不继承主图 CRS；无效 PRJ 原文/错误会保留。没有 PyProj 时不破坏原有仅数据流程，保留 WKT 并标为 `unparsed`，不猜 EPSG。

相等的 CRS 或由 PROJ 以 100% 置信度匹配到同一权威定义的 CRS 可共用 ID，保留原 PRJ 文件及其哈希。不满足这一条件的定义分别保存，ID 不一定是 EPSG 编码；应查 `crs_definitions[id]`，不要从 ID 字符串猜坐标系。`source_wkt` 是收录的原定义文本，`wkt` 为 WKT2:2019。

`axis_info` 保留 CRS 定义的正式轴顺序；SHP 几何仍按 x,y 存储。例如五龙沟几何 x 是东坐标、y 是北坐标，地理坐标通常为经度、纬度。使用 PyProj 转换几何 x,y 时应显式使用 `always_xy=True`。

**factor 只记录已经执行的原生坐标换算，不能再次作用于输出 SHP。** 脚本只读取空间参考、导出元数据，不重投影或重新指定 CRS。原始椭球索引和基准核对限制继续保留。

## 五龙沟核验值

现有五龙沟成果共有39层，其中35层采用 `EPSG:21456`（Beijing 1954 / Gauss-Kruger CM 93E），中央经线93°E，单位米，原生主图比例尺分母50000，已应用换算系数50。`444_线`、`RECTFRAM_区`、`RECTFRAM_点`、`RECTFRAM_线` 四层仍保留图面坐标而未指定 CRS；这些层原生系数为1。

## 读取标准 PROJJSON

```python
import json
from pathlib import Path
from pyproj import CRS

reference = json.loads(Path('result/spatial_reference.json').read_text(encoding='utf-8'))
for name, layer in reference['layers'].items():
    if layer['crs_status'] == 'defined':
        definition = reference['crs_definitions'][layer['crs_id']]
        crs = CRS.from_json_dict(definition['projjson'])
        print(name, definition['auth_id'], crs.name)
```

## 旧成果只读补导出

```sh
python tools/export_spatial_reference.py 已有成果目录 另存的空间参考.json
```

工具可读取完整流程、原生导出、标准注记数据集、独立 QGIS 导出或平铺 SHP 目录。对有 manifest 的成果先核验产物，要求另存到已有成果树之外，拒绝覆盖已存在的 JSON，避免破坏旧哈希清单。旧版地图未记录范围时 `render_reference.extent_xy` 为 `null`，不编造范围。已有成果不会改写。
