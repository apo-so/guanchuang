# 观窗 Guanchuang

观窗是给《十字军之王 III》Mod 作者用的 Windows 外观布局工具。你可以在浏览器里调整现有原生窗口，也可以从自己设计的本地 HTML 出发，生成原生窗口和配套的 DDS 贴图。

## 第一次使用

1. 在预发行页面下载 `Guanchuang-1.1.0-preview2-Windows-x64.zip`，完整解压后双击 `Guanchuang.exe`。[下载 Windows x64 预览版](https://github.com/apo-so/guanchuang/releases/tag/v1.1.0-preview2)
2. 选择随包的 `示例/外观草图.html`，点击「转换并打开整窗编辑页」。HTML 转换使用本机的 Edge 或 Chrome。
3. 试着移动一个控件。在编辑页下载完整 GUI 草稿和编辑请求，回到启动器点击「校验导出并生成最小差分」，就能找到可供 Mod 使用的文件。[使用说明](使用说明.md)

## 两种工作方式

| 起点 | 可以得到什么 |
| --- | --- |
| 已有 CK3 `.gui` | 选一个具名窗口，在整窗网页里调已有控件的位置、尺寸、文字或纹理。导出时保留未编辑的源码。 |
| 自己写的 HTML | 指定画布、窗口和要显示的状态，生成固定布局的 `.gui` 与配套贴图。新窗口的游戏入口和按钮行为由 Mod 作者接入。 |

每次转换都会留下 `visual-audit.json`。范围内检查通过的结果在 `candidate`，需要人工看图的草稿在 `待复核/candidate`。如果发现确定的错位、丢字或贴图错误，程序只输出诊断和对照图。

当前版本为 **1.1.0-preview2**。固定画布下的浏览器布局、导出和回读已经实测。由独立网页生成的新窗口仍待 CK3 实机复验。[本版说明](docs/预览版发布说明.md)

## 从源码运行

在仓库根目录打开 PowerShell，安装依赖后运行启动器。Windows 分发包自带 Python 运行环境。

```powershell
py -3.13 -m pip install -r source/requirements.txt
py -3.13 source/guanchuang.py
```

运行外观输出回归需要本机有 Edge 或 Chrome。测试覆盖文字裁切、控件位置、贴图损坏和渲染偏移。

```powershell
cd source
py -3.13 -m unittest discover -s tests -p test_visual_output.py -v
```

第三方组件的许可声明随包提供。[许可声明目录](licenses/)
