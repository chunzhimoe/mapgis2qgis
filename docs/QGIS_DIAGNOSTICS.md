# Windows 的 PyQGIS 导入报错

`QGIS export requires PyQGIS; use QGIS Python, not pip install qgis` 表示制图阶段导入 `qgis.core` 失败。旧提示没有展示底层 ImportError，不能仅凭这句话判断电脑上没有 QGIS。离线安装包已经包含 QGIS，不要另用 pip 安装同名包。

前面的 `You will likely lose important projection information ... PROJ string` 是 PyProj 对 CRS 格式转换的警告，不是这次中断的异常；程序的 CRS 输出保留 WKT。也不能凭该警告判定坐标错误。

## 已安装版本的诊断

下载仓库 `tools/qgis_diagnose.py`，不需要升级安装包。脚本只检查导入，不读取地质数据，不修改安装目录、注册表或系统环境变量。

在 Windows **命令提示符（cmd）** 中执行，下面假设脚本保存在下载目录，软件安装在 `E:\map2gis`；按实际位置更换：

```bat
cd /d "%USERPROFILE%\Downloads"
"E:\map2gis\python.exe" qgis_diagnose.py --output qgis-diagnostic.json
```

PowerShell 对应命令：

```powershell
Set-Location "$env:USERPROFILE\Downloads"
& 'E:\map2gis\python.exe' .\qgis_diagnose.py --output .\qgis-diagnostic.json
```

应使用安装目录中的 `python.exe`，不要用裸 `python` 命令，避免调用其他环境。将生成的 `qgis-diagnostic.json` 中失败信息提供给维护者。报告包含安装路径、应用/组件版本、与 GIS 有关的环境变量、模块来源及完整异常链，不包含地质数据或完整环境变量表。

脚本在两个独立子进程中按实际转换顺序检查 PyProj、Shapely、PyQGIS：

- `normal`：保留当前环境，调用当前已安装程序的运行环境配置。
- `bundled_environment`：在子进程中移除外部 Python/GIS 配置，明确使用当前安装内的 QGIS Python、DLL、Qt 插件目录。

若第一项失败、第二项通过，说明这两组启动环境的差异影响了导入，可据报告继续定位；两项均失败时，查看具体模块和 traceback，检查缺失文件或版本问题。`PASS` 只表示本次导入检查通过，不代表 PDF 导出已验证。失败探测退出码为 1 属于预期诊断结果，报告仍会写出。

如果急需先导出数据，可取消 GUI 的“生成全图 QGIS/PDF”并另选一个新输出目录；纯数据流程不依赖 PyQGIS。要生成地图仍需解决该导入错误，修改 `strict_native` 或字号配置不能解决它。

参考：[QGIS 官方独立应用配置说明](https://docs.qgis.org/3.40/en/docs/pyqgis_developer_cookbook/intro.html#running-custom-applications)、[Conda QGIS Windows 激活脚本](https://github.com/conda-forge/qgis-feedstock/blob/main/recipe/scripts/activate.bat)。
