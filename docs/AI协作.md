# 用 AI 助手制作 CK3 窗口外观

观窗适合这样的分工。你确定窗口要呈现什么，AI 写出页面，观窗在本机测量、转换并检查布局，AI 再按检查报告定位问题。模型由你使用的 AI 客户端提供。

**可以直接发给助手的任务**

> 请做一个 480×260 的 CK3「行宫择址」窗口，包含标题、家族庄园和营地两个选项，以及底部的返回、确认按钮。先交一份能离线打开的 HTML。用观窗把当前状态转成名为 `gc_palace` 的原生窗口，交付源网页、观窗生成的 `.gui`、配套 DDS 和 `visual-audit.json`。如有问题，请指出具体控件，并说明应修改源网页还是转换规则。

**助手怎么调用观窗**

在已解压的 Windows 发行目录打开 PowerShell，可以用随包示例跑完整条路径。新建网页也可以替换下面的输入路径。每次转换使用新的输出目录。

```powershell
$out = Join-Path $env:TEMP ("guanchuang-ai-" + [guid]::NewGuid().ToString("N"))
.\Guanchuang.exe import ".\示例\外观草图.html" --window gc_palace --out $out
Get-Content -LiteralPath (Join-Path $out "visual-audit.json") -Encoding utf8
```

`.exe` 是 Windows 可执行程序的后缀。手动使用时，双击 `Guanchuang.exe` 会打开界面。本地 AI 助手可以用上面的命令运行同一程序。只有网页聊天时，先把 AI 制作的 HTML 和它引用的本地资源保存到电脑，再运行观窗。

也可以用 Python 调用相同功能。在仓库根目录安装依赖后执行以下命令。两种入口任选一种。

```powershell
py -3.13 -m pip install -r .\source\requirements.txt
$out = Join-Path $env:TEMP ("guanchuang-ai-" + [guid]::NewGuid().ToString("N"))
py -3.13 .\source\guanchuang.py import ".\示例\外观草图.html" --window gc_palace --out $out
```

**助手如何交付**

| `visual-audit.json` 的状态 | 下一步 |
| --- | --- |
| `VERIFIED_SCOPED` | 在 `candidate` 中取原生文件及配套贴图，随附两张对照图。 |
| `REVIEW_REQUIRED` | 从 `待复核/candidate` 取草稿，按报告逐项说明需要人工看图的控件。 |
| `REJECTED` | 交出诊断，保留失败样本。若源页面本身有误，修改 HTML 后重跑。若偏差来自转换器，修正转换规则并增加相应回归。 |

以上状态说明固定画布下的源码和浏览器外观检查结果。实际游戏显示要在 CK3 中另行验收，窗口入口和按钮事件由 Mod 作者接入。[观窗使用说明](../使用说明.md)
