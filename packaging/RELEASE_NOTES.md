## MapGIS2QGIS 0.4.0

全内置桌面版：Python、Tk GUI、MapGIS 原生转换库、QGIS、PyProj 和 Shapely 均包含在安装包内。

- Windows x64：下载 `.exe`，安装后从开始菜单打开 MapGIS2QGIS。
- macOS Apple Silicon：下载 `.dmg`，打开其中的 `.pkg` 安装器，安装后从 Applications 打开版本化应用。不提供 Intel Mac 包。
- 支持原生 WT/WL/WP/MPJ、坐标候选判定、标准注记、岩性时代连排、点面关联、全图和局部预览。
- 包含 SHA-256、实际依赖版本、安装后转换/渲染核验和 GUI 测试报告。只有两个平台均通过构建与安装验证后才发布此 Release。

开发安装包未签名或公证。自动坐标判定有适用边界；未定位层和无效几何会保留并报告，原符号库完整样式尚未恢复。源数据不随安装包分发。
