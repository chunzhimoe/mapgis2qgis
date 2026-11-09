## MapGIS2QGIS 0.4.3

全内置桌面版：Python、Tk GUI、MapGIS 原生转换库、QGIS、PyProj 和 Shapely 均包含在安装包内。

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
