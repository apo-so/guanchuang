# 观窗 Guanchuang

观窗是一款 **AI 辅助工具**，用来在 Windows 上制作《十字军之王 III》（CK3）的原生窗口外观。你向助手描述窗口，助手把设计写成本地 HTML，观窗将它转换为原生 `.gui` 和配套的 DDS 贴图，并指出需要复核的控件。你也可以导入已有的原生窗口，在网页中调整外观后写回游戏文件。

## 使用方式

观窗程序、`guanchuang` skill 和示例都在这个仓库。让本地 AI 助手使用技能，取 `main` 分支即可。自己操作 Windows 界面时，可以从同一仓库的 Releases 下载程序。

### 把这条发给本地 AI 助手

**推荐在 Codex 里用 GPT** 执行这条指令。DeepSeek（DS）等其他助手只要能读写本地文件并运行终端命令，也可以使用同一个 skill。

> 请在本地工作区克隆或复用 https://github.com/apo-so/guanchuang 的 `main` 分支，读取 `.agents/skills/guanchuang/SKILL.md`，按其中的 Python 入口自行准备依赖并运行 `demo`，把随库「行宫择址」HTML 转成 CK3 原生窗口，返回 `.gui`、DDS 目录、对照截图和 `visual-audit.json` 的本地路径与检查结论。全程由你调用观窗，不用我手动打开 EXE。

### 助手如何运行

在克隆的仓库根目录打开 PowerShell。用 Python 3.13 运行随库示例，网页由本机的 Edge 或 Chrome 在后台测量。

```powershell
$runner = '.\.agents\skills\guanchuang\scripts\run.py'
py -3.13 $runner demo
```

如果返回 `SETUP_REQUIRED`，让助手按技能里的“第一次调用”建立专用 Python 环境、安装随库依赖，再用该环境运行命令。[技能与依赖说明](.agents/skills/guanchuang/SKILL.md)

示例命令可以直接运行。处理自己的窗口时，把文件路径和窗口名换成实际值。

| 想做什么 | 在同一 PowerShell 窗口运行 |
| --- | --- |
| 将 HTML 草图转成原生窗口与贴图 | `py -3.13 $runner import ".\示例\外观草图.html" --window gc_palace` |
| 将已有原生窗口打开成可编辑网页 | `py -3.13 $runner import ".\示例\gui\observatory.gui" --window gc_observatory` |

命令返回 JSON。`output` 是这次的新目录，`artifacts` 列出实际文件的绝对路径。生成原生窗口时看 `gui` 和 `gfx`，导入原生窗口时看 `editor`。两种情况都可以从 `audit` 打开检查报告。

HTML 转换结果为 `VERIFIED_SCOPED` 时可取范围内已通过的候选。`REVIEW_REQUIRED` 的草稿在 `待复核/candidate`，要查看报告指出的具体控件。`REJECTED` 只交付诊断及可取得的截图。[编辑和交付示例](docs/AI协作.md)

### 自己用 Windows 界面

完整解压 Windows x64 ZIP，双击 `Guanchuang.exe`，选择 `示例/外观草图.html`，点击「转换并打开整窗编辑页」。修改完成后下载完整 GUI 与编辑请求，再回到启动器点击「校验导出并生成最小差分」。[下载 Windows 预览版](https://github.com/apo-so/guanchuang/releases/tag/v1.1.0-preview2) · [使用说明](使用说明.md)

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
