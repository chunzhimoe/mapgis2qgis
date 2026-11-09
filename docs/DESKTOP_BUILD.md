# 全内置离线安装包

构建macOS arm64和Windows x64，Actions使用macos-15与windows-latest；不构建Intel Mac。安装包内包含Python 3.11、Tk、QGIS 3.40系列、PyShp、PyProj、Shapely及依赖，安装过程不从网络安装Python包。

## 构建

在arm64 Mac或Windows x64的Conda构建环境安装constructor、conda-standalone、setuptools、wheel（Windows另需nsis）后：

```sh
python tools/build_desktop.py
```

生成应用wheel和constructor配置，Mac生成PKG与DMG，Windows生成EXE。DMG包括安装器、应用源码、第三方许可证和构建/包版本记录。Mac安装到所选位置的`Applications/MapGIS2QGIS-0.4.0/`并生成.app；Windows默认安装到当前用户LocalAppData，生成开始菜单快捷方式与目录内.cmd启动器。安装脚本使用包内wheel离线安装库，启动器根据自身路径定位Python，不依赖用户PATH或硬编码构建路径。

## Actions

`.github/workflows/build-desktop.yml`在main推送或手动触发时运行：

1. Linux运行单元/集成测试，并确认没有跟踪changes目录。
2. macOS arm64和Windows x64分别构建全内置安装器，Mac另校验DMG。
3. 将PKG或EXE安装到临时CI主机，以安装后的Python实际运行原生转换、注记、QGIS渲染及哈希核验，再打开Tk窗口验证后台处理与预览。
4. 小型验证报告上传到Actions；大体积DMG/EXE与SHA-256保存到同一草稿Release，避免长期占用Actions大文件存储。草稿不会自动公开发布。

仓库使用固定SHA的官方Actions，构建记录包含实际依赖解算结果。未配置Apple Developer签名/公证证书，开发安装包不可宣称已签名或公证。各运行组件按其自身许可分发；本项目原有MIT代码和适配模块Apache-2.0许可保留。实际平台构建结果以Actions运行记录和安装后的测试报告为准。

本地changes归档不进入Git、源码包、DMG源码附件或运行环境。真实图件、矿点、转换成果也不进入安装包。
