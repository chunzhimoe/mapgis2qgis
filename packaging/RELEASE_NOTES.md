## MapGIS2QGIS 0.4.6

全内置桌面版：Python、Tk GUI、MapGIS 原生转换库、QGIS、PyProj 和 Shapely 均包含在安装包内。

完整转换默认输出根目录 `spatial_reference.json`，GUI完成后点击「空间参考 JSON」查看；原生转换和QGIS地图导出也各保留对应JSON。包含实际逐层PRJ声明、完整WKT2与标准PROJJSON、单位/轴信息、原生换算系数和依据、未定位/无效层，以及独立的制图CRS/范围。支持自定义无EPSG投影、多CRS数据、仅数据流程和已有成果只读补导出，不猜缺失CRS，不重复缩放已导出的坐标。

空间参考JSON纳入产物哈希核验。双平台已安装环境验收增加PROJJSON往返、数据与制图CRS不同、缺失CRS保留、源字节不变、相对路径搬移和GUI按钮检查；`spatial-reference-*.json`报告随Release提供。说明见仓库docs/SPATIAL_REFERENCE.md。

GUI「多选文件/工程」支持 Ctrl/Command 多选或 Shift 连选 WT/WL/WP、MPJ 或 SHP。所选文件作为同一组图层处理，生成一套标准注记、PDF和QGIS工程；不会自动扫描并导入同目录未选择的图层。MPJ引用层与直接选择文件去重，SHP自动带上同名配套文件；原生与SHP分开选择，同名SHP需重命名或分组以免混淆。输入数量/名称与完整运行路径可核对，取消对话框保留选择。

Python API接受文件列表，CLI增加 `--source-list` JSON路径数组；旧文件夹和单文件调用保持可用。双平台安装验收新增真实GUI多选原生及SHP转PDF、源哈希、未选层排除和预览检查，报告随Release提供。

修复 Windows 继承其他 Python/QGIS/Qt/Conda 环境后 `qgis._core` DLL 导入失败的问题。开始菜单和 CMD 启动器采用隔离 Python；CLI 在 GIS 加载前切换到安装包自己的路径环境，GUI 转换子进程同样隔离。只对包含 Conda QGIS 的 Windows 安装环境启用，不修改系统设置。-I 启动下日志明确使用 UTF-8，中文异常仍可读。

Windows 安装验收增加外部 Python 伪 QGIS 包与错误 Qt/PROJ/GDAL 路径、PYTHONHOME 故障注入，实际核验原生转 PDF、GUI 后台进程及预览；报告随 Release 提供。PyQGIS 失败提示保留真实 ImportError 和解释器位置。Release 附独立 `qgis_diagnose.py`，现有0.4.3可用 `--launch-gui` 在已通过诊断的内置环境中临时启动。

GUI 新增默认开启的「自动字号」，按图幅、每层注记间距和文字长度估算大小，字号栏作为上限。保留固定点位、原文字和源行，实际字号写入 `map/export.json` 的 `font_sizing`；可取消勾选使用手动大小。新增 07 自动字号 JSON，需 0.4.3；01–06 兼容旧版。间距估算不保证所有密集局部零重叠，细节可在 PDF/QGIS 中放大。

本版补入 Noto Sans CJK SC Regular 中文字体（SIL OFL 1.1）。渲染进程自动注册字体；配置指定字体缺少中文/希腊字母时使用内置字体。全图、局部图与概览标题均使用已核验的字体，字体及许可证随地图成果导出到 `map/fonts/`。外部 QGIS 若找不到该字体，可安装成果内的 OTF。

安装后测试新增真实字形索引检查、PNG 字体样张和 PDF 字体嵌入检查。Release 附带两个平台的 `fonts-*.json` 与 `font-probe-*.png/.pdf`，便于直接核对中文和希腊字母的显示。

- Windows x64：下载 `.exe`，安装后从开始菜单打开 MapGIS2QGIS。
- macOS Apple Silicon：下载 `.dmg`，打开其中的 `.pkg` 安装器，安装后从 Applications 打开版本化应用。不提供 Intel Mac 包。
- 支持原生 WT/WL/WP/MPJ、坐标候选判定、标准注记、岩性时代连排、点面关联、全图和局部预览。
- 包含 SHA-256、实际依赖版本、安装后转换/渲染核验和 GUI 测试报告。只有两个平台均通过构建与安装验证后才发布此 Release。
- `MapGIS2QGIS-profiles.zip` 包含七套完整 JSON 和中文说明，另提供 `MapGIS2QGIS-fonts.zip` 供旧版手动安装中文字体并选择兼容配置。
- 修复加载简化 JSON 时重置绘图勾选/字号/幅宽/DPI 的问题，保留未在配置中明确填写的界面参数。支持 UTF-8 BOM 配置。
- 修复 GUI 覆盖配置中 `input_format` 的问题，明确指定原生或 SHP 的配置现在会生效。
- PDF 位于用户所选输出目录下 `map/map.pdf`。两平台均实际运行通用配置的原生/SHP 转换和 PDF/QGIS 导出测试，并验证自动字号缩小后 64 条注记仍固定在原锚点。

开发安装包未签名或公证。自动坐标判定有适用边界；未定位层和无效几何会保留并报告，原符号库完整样式尚未恢复。源数据不随安装包分发。
