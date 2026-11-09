# 桌面工作台

```sh
mapgis-annotations gui
# 或
python -m mapgis_annotations gui
```

1. 选择原生文件夹、WT/WL/WP、MPJ工程，或已有SHP文件夹。
2. 选择输出父目录。工作台会建议一个尚不存在的新目录，输入保持不变。
3. 通用自动识别可不选配置；地区配对/点面关系使用JSON。五龙沟示例是显式可选配置，不是默认规则。
   可直接选择的六套完整配置及参数说明见 [examples/profiles](../examples/profiles/README.md)。常规全图/PDF建议用 `01_generic_full_pdf.json`，先快速检查可选 `03_quick_preview_pdf.json`。
4. 坐标参数留空时自动判定；明确知道EPSG或换算系数时再填写。幅宽单位mm，字号points为纸面点、map为输出CRS单位。
5. 勾选绘图后生成全图、PDF、局部预览和QGIS工程。源码环境需要Tcl/Tk与PyQGIS；离线安装包包含Python、Tk、QGIS与空间处理依赖。
6. 点击开始，进度与记录显示阶段状态。停止在当前步骤结束后清理暂存目录，不发布取消结果。
7. 完成后可打开标准注记数据、高清PNG及QGIS工程。预览自动缩放到可用区域，高清图可单独打开。

PDF 位于你选择的新输出目录下 `map/map.pdf`；QGIS 工程是 `map/map.qgz`，全图图片是 `map/map.png`。「打开全图」按钮打开 PNG。绘图开启且整个任务验收通过后才发布这些文件。

从 0.4.1 起，加载只含 `strict_native=false` 等部分参数的 JSON 会保留当前绘图勾选、幅宽、DPI 和字号；配置明确写出的绘图参数才更新界面。完整配置中的 `render.enabled=true` 会勾选绘图。支持 Windows 记事本保存的 UTF-8 BOM 配置，并尊重配置指定的 `input_format`。加载后仍可在界面调整显示的参数，开始时以界面值为准。

处理运行在独立Python子进程，Tk主线程只更新界面。任务配置/阶段事件/日志放在临时目录，子进程结束后清理；成功结果通过manifest及哈希核验。自动识别的CRS、未绘制层与无效面保留在结果报告中。
