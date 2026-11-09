# MapGIS2QGIS

MapGIS 原生转换、坐标判定、标准注记、空间关联和 QGIS 渲染的一键流程与桌面工作台。Python 包名保持 `mapgis-annotations`。

```sh
mapgis-annotations gui
mapgis-annotations pipeline 原生图件目录 新结果目录 --config examples/wulonggou_pipeline.json
```

完整流程见 [docs/PIPELINE.md](docs/PIPELINE.md)，GUI 见 [docs/GUI.md](docs/GUI.md)。
七套可直接选择的 JSON 见 [配置文件与使用说明](examples/profiles/README.md)：通用完整 PDF、严格完整 PDF、快速预览、仅数据、已有 SHP 制图、五龙沟连排与局部图，以及 0.4.3 自动字号全图。Release 同时提供 `MapGIS2QGIS-profiles.zip`；已有 0.4.0 安装包可使用 01–06，07 需 0.4.3。PDF 输出位置为你选择的输出目录下 `map/map.pdf`。
0.4.2 起内置开源 Noto 中文字体，渲染时核查中文/希腊字形；Release 提供两个平台的 PNG/PDF 字体样张与核验报告。成果内的 `map/fonts/` 包含字体和许可证，便于在外部 QGIS 使用。
0.4.3 GUI 增加自动字号开关，按每层注记间距估算并缩小字号，保留原坐标和手动上限。JSON 使用 `render.auto_font_size=true`；独立导图命令使用 `export --auto-font-size`。
离线桌面安装包面向 **macOS Apple Silicon（arm64）与 Windows x64**，包含 Python、Tk、转换库、QGIS、PyProj 和 Shapely，无需另装运行环境。GitHub Actions 在推送 main 或手动触发时构建 `.dmg` 和安装 `.exe`；DMG 内含 `.pkg` 安装器及许可证/构建记录，Mac 从 Applications 打开版本化应用，Windows 从开始菜单打开。构建后实际运行安装环境的转换、渲染与 GUI 测试；两个平台全部通过后，Actions 自动发布到同一个 Release。当前开发包未签名或公证。构建说明见 [docs/DESKTOP_BUILD.md](docs/DESKTOP_BUILD.md)。

通用 MapGIS 转换与注记校正库，Python API 与命令行工具，分两段：

1. **原生读取（0.2.0 新增，0.3.0 扩展坐标解析）**：用纯 Python 直接读取 MapGIS 6.x 原生 `.wt/.wl/.wp/.mpj`，写出 Shapefile。不需要安装 MapGIS，基础读取只用标准库。投影图面坐标换算到米，经纬度保持度；坐标系候选经坐标检查后才采用，每一项判断都记入审计文件。
2. **注记校正**：把 MapGIS 注记转换为 Unicode／HTML，做严格编码检查和原记录追溯，保证坐标文件字节不变。空间关联和 QGIS 导出为可选模块。

输入目录、字段、图层、坐标系和显示规则均由数据或配置提供。

## 从 MapGIS 原生文件开始

```sh
mapgis-annotations from-mapgis 图件文件夹或工程.MPJ output/shp       # 原生 → SHP（正确单位 + .prj + 审计）
mapgis-annotations run output/shp output/new_dataset --config profile.json   # 注记校正，同下文
```

```python
from mapgis_annotations import export_native, read_native_layer
manifest = export_native('map_folder', 'output/shp')          # georeference=False 时保持图面单位，不需要 pyproj
layer = read_native_layer('map_folder/地质.WP')               # layer.fields / layer.features，只含有效图元
```

- **转换结果**：只输出有效图元；已删除图元仍留在原文件里，不会被导出。属性表的全部字段都保留。默认还附加符号列：点有 点类型/注记/子图号/颜色，线有 线型/线颜色/线宽，区有 填充色/图案号；`--no-style` 可关闭。
- **区多边形**：按区记录里的带符号弧段表重建。环的嵌套关系按几何包含来判定，因为 MapGIS 的环顺序不可靠。外环写成顺时针、洞写成逆时针；完全重复的环只保留一个。
- **与 MapGIS 自身导出（`_ShapeOut`）对比**：在 680 个真实文件、307 510 个要素上逐要素比较，要素顺序、坐标和属性值全部一致。下面几处有意不同，都是 `_ShapeOut` 自身会丢失或损坏数据的地方：
  - `_ShapeOut` 的 DBF 每遇到一个已删除图元就多写 1 个字节，导致之后的记录整体错位；本库写出的 DBF 是规范格式；
  - 数值超过字段宽度时，`_ShapeOut` 会截断（如 220 写成 22）；本库会加宽该字段；
  - 没有属性表的图层，`_ShapeOut` 只写出 DBF 头、没有记录；本库写一个空的 `ID` 列，每个要素一行。
- **坐标与坐标系**：头部只用来提出“图框”候选（椭球、中央经线、比例尺），判定靠坐标本身。每个图层按下面的顺序决定：
  1. 用自己头部的图框，前提是坐标反算到经纬度后合理（在投影带附近、纬度 0–60°N）；
  2. 头部不可信时，如果图层范围落在主图框内，就按主图框换算（例如“放大图”的头部还写着旧比例尺）；
  3. 如果某个标准比例尺系数（1:500 到 1:100 万）能唯一地把图层放进图框，就采用它，并标记为 `factor INFERRED`；
  4. 以上都不满足（插图、表格、剖面），保留图面单位，不写 `.prj`。
- **EPSG 编码**：按“基准 + 6°/3° 分带 + 是否带带号”的名称在 PROJ 数据库中查找，并要求其中央经线与头部一致。
- **独立证据**：点图层里如果有经纬度属性（十进制或 DDDMMSS，按字段值识别，代码化的字段名如 CHAHBA/CHAHBB 也能认出），会计算点位与经纬度之间的残差中位数。
- **新增投影解析（0.3.0）**：参考 [mapgis2shp](https://github.com/leecugb/mapgis2shp)，支持头部投影编号 0（经纬度）、2（Albers）、3（Lambert）、5（横轴墨卡托）。Albers/Lambert 保留原点纬度、两条标准纬线、假东/假北；带符号 DDDMMSS.sss 保留负号及小数秒。原有北京54/西安80高斯—克吕格的 EPSG 匹配和主图框逻辑保留。
- **单位与自定义 CRS**：经纬度不使用比例尺换算，即使头部比例尺是 0/NaN 也保持度。自定义投影没有 EPSG 编号时仍可写出完整 `.prj`；审计 `crs_wkt` 表示实际分配的坐标系，`epsg=null` 不等于没有 CRS，统计 `with_crs` 按实际 CRS 计数。经纬度属性残差使用椭球测地距离，单位米。
- **基准边界**：扩展支持常见索引 1/2/7/9/10/11/16/116，映射仍需与原安装环境的 `ellip.dat` 核对。仅有椭球时标记 `ELLIPSOID_ONLY`；不套用上游固定区域的 `towgs84` 参数，不将 CGCS2000 擅自认作 WGS84。自动分配前检查经纬度范围及投影正反算一致性；这只能排除部分错误，不能证明地理位置绝对正确。
- **旧图框保护**：北京54/西安80高斯—克吕格仍需通过原有EPSG分带匹配，不用通用TM候选绕过此检查。例如五龙沟目录中的旧西安80 CM48图框保留原单位且不写PRJ。其他基准的通用TM、Albers/Lambert可保留自定义WKT。
- **无法确认的情况**：未知椭球不会去猜，可用 `--epsg/--factor` 显式指定。
- **审计与保护**：判断依据、哈希和残差都写入 `native_export.json`。输出目录必须是新建的，并且在输入目录之外；处理失败时不留下任何结果；源文件处理前后都做哈希校验。
- **暂不支持**：MapGIS 5.x 文件（`byte[4]==0x05`）、网络文件 `.wn`、写回 MapGIS 格式。

安装：`python -m pip install .`；空间模块：`python -m pip install '.[spatial]'`。原生读取的米制换算和坐标系判定需要 pyproj，即空间模块；只做图面单位转换时用 `from-mapgis --no-georef`，不需要 pyproj。

开发验证：`PYTHONPATH=src python -m unittest discover -s tests -v`。

## 快速使用

Python 3.9及以上；空间模块需要Shapely 2及PyProj。QGIS导出需要外部可导入qgis.core的运行环境，普通转换不会导入QGIS或启动GUI。

```python
from mapgis_annotations import parse_note, ConversionConfig, convert_layer

note = parse_note('ηγT#-2')
print(note.unicode)  # ηγT₂
print(note.html)     # ηγT<sub>2</sub>
report = convert_layer('input/labels.shp', 'output/new_labels',
                       ConversionConfig(note_field='TEXT', encoding='gbk'))
```

```sh
mapgis-annotations parse 'Pt#-1#=J#-2#+2#=(mb)'
mapgis-annotations inspect input
mapgis-annotations convert input/labels.shp output/new_labels --note-field TEXT --encoding gbk
mapgis-annotations run input output/new_dataset --config profile.json
mapgis-annotations verify output/new_dataset
# 原始文件不在本机时，明确只核验产物：
mapgis-annotations verify output/new_dataset --products-only
```

可用`python -m mapgis_annotations`代替命令。所有输出目录必须尚不存在且与输入树分开；失败回滚，不覆盖源数据。

编码优先级：显式encoding → cpg → GB18030后备。报告列出实际编码，不凭可解码结果宣称自动检测到编码。注记字段默认只在常见字段中恰好一个候选时自动选择；其他字段命名请显式指定。

## 自定义地区、图层、字段和符号

先inspect实际数据。`examples/generic.json`展示了不同命名、字段、ASCII代号和投影的完整配置：

```json
{
  "annotation_layers": ["map_labels", "legend_labels"],
  "conversion": {
    "note_fields": {"map_labels": "TEXT", "legend_labels": "CAPTION"},
    "encoding": "utf-8"
  },
  "pairing": {
    "legend_layer": "legend_labels",
    "target_layers": ["map_labels"],
    "min_dx": 1, "max_dx": 30, "max_dy": 3,
    "rock_pattern": "[A-Z]+", "age_pattern": "Unit#-[0-9]+",
    "require_legend": true
  },
  "crosswalks": [{"points": "map_labels", "polygons": "geology", "invalid_policy": "exclude"}]
}
```

此配置已在EPSG:32648合成数据中端到端测试。仅做注记标准化可省略pairing/crosswalks。

```python
import json
from mapgis_annotations import WorkflowConfig, run_workflow, verify_dataset

with open('profile.json', encoding='utf-8') as handle:
    config = WorkflowConfig.from_dict(json.load(handle))
result = run_workflow('input', 'output/new_dataset', config)
print(result['converted_records'])
print(verify_dataset('output/new_dataset'))
```

## 配对、单位和空间关系

- min_dx/max_dx/max_dy始终按米计，默认20/500/35仅是初始值，需按图幅和排版调整。
- 投影源坐标默认用于计算，英尺等单位会换算为米；经纬度源必须显式给出适合研究区的投影working_crs，库不自动选投影区。
- 默认读取prj，缺失时可在pairing.crs_overrides按层提供真实CRS；此声明只用于计算，不会伪装成原文件自带投影。
- 所有候选边均参与反向歧义计数；双方都是唯一候选才连排，不强行取最近。默认先从legend_layer建立白名单，再处理target_layers。无图例时须显式require_legend=false。
- 未解决记录保留原因NO_CANDIDATE、MULTIPLE_CANDIDATES、REVERSE_AMBIGUITY、NOT_IN_LEGEND及候选原行号。

```python
from mapgis_annotations import AnnotationPoint, PairingConfig, pair_annotations
points = [AnnotationPoint(0, 100, 100, 'ηγ'), AnnotationPoint(1, 110, 100, 'T#-2')]
result = pair_annotations(points, 'EPSG:32648',
                         PairingConfig(min_dx=1, max_dx=30, max_dy=3),
                         allowed_pairs={('ηγ', 'T#-2')})
assert result['display'][0] == 'ηγT<sub>2</sub>'
assert result['display'][1] == ''
```

点面关联独立于排版配对，会将点变换至面的CRS，保留所有相交、边界多匹配和未匹配点。无效面策略：exclude默认排除并报告，error拒绝，include显式包含但不修复。不同读取器对错误环的解释可能不同，include不能提供确定地质归属。距离阈值和正则是排版启发式参数，不是地质规范。

## QGIS全图导出

在QGIS附带Python或已配置PyQGIS的环境安装本库，然后运行：

```sh
python -m mapgis_annotations export output/new_dataset output/new_map \
  --width-mm 1000 --dpi 300 --font-size 9 --font-unit points
```

也可在QGIS Python控制台使用API：

```python
from mapgis_annotations.qgis_adapter import export_project
export_project('output/new_dataset', 'output/new_map',
               font_size=9, font_unit='points', width_mm=1000, dpi=300)
```

points为纸面字号，map为输出地图坐标单位，render_crs可指定输出投影。重现前版五龙沟样式用font_size=100、font_unit=map。导出要求每层有有效CRS；缺失投影需根据真实资料先正确定义，不能猜测。普通pip安装qgis不能建立完整运行环境。库不固定QGIS安装位置，已有QGIS应用会复用并保持运行。

结果包含map.qgz、map.pdf、map.png、preview.png、export.json和数据副本；工程使用包内相对路径。连排新增显示字段，不删除源行、不改坐标、RAW_NOTE或LABEL_HTM。默认灰线不猜测原配色，渲染像素预算默认1.2亿，超出时降低dpi或幅面。

## 输出与保护

```text
new_dataset/
  manifest.json                 配置、统计、输入/产物SHA-256
  layers/<实际图层名>/
    <实际名称>.shp/.shx/.dbf/.cpg/.prj
    conversion.json             转换层的字段映射和警告
    display.json / pairs.csv    配对层的显示、距离及未解决记录
  crosswalk_0.json/.csv          匹配与未匹配关系
```

业务ID可重复，SRC_FID为零起始原行号。大小写配套文件均支持。删除DBF行、缺失文件、解码错误、重复字段、UTF-8字段超过254字节会拒绝处理，不静默删行或截断。超10字节或冲突的字段名自动生成短名，field_map及QGIS别名保留原名。特别长文字需用更适合的存储格式，本版SHP转换会明确拒绝溢出。

未知控制码保留并标记，strict模式可拒绝。空白子图没有可还原文本，原字号/旋转缺失不能伪装为已恢复。本库不自动配准图面坐标，也不补造符号库。

这里的图面坐标换算依赖已有图框/投影参数；没有空间参照的任意页面坐标仍需控制点配准。

## 测试和案例

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python tests/regression.py /your/local/source /your/new/regression-output
```

第二条针对五龙沟基线，使用examples/wulonggou.json，需要用户本地真实数据和旧基线；在原项目以外运行时另传`--legacy-script /path/to/original_converter.py`。原生读取的真实数据回归：`PYTHONPATH=src python tests/native_regression.py 原生图件目录 MapGIS导出的SHP目录`，按 `_ShapeOut` 缺陷对齐后逐要素、逐值比对。库实现和默认API不绑定此案例。发行包不含任何真实地图、矿点或研究结果。API参考见[docs/API.md](docs/API.md)，验收记录见[docs/VALIDATION.md](docs/VALIDATION.md)。

坐标兼容回归可用 `tests/georef_regression.py --baseline /path/to/0.2.0 --output /new/output 原生图件目录`，检查旧版本已分配 CRS 的图层坐标/属性不变，并单列新增 CRS 的图层。

## 来源与许可

原有代码为 MIT；`native_crs.py` 的适配实现为 Apache-2.0，来源和修改说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。发行包同时包含两份许可，不需要安装 mapgis2shp 或 GeoPandas。
