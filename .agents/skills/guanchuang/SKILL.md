---
name: guanchuang
description: 用观窗把本地 HTML 窗口草图转换成 CK3 原生 GUI 和配套 DDS，或把现有 .gui 导入网页、编辑显式外观属性并校验导出。适用于有本机命令权限的 AI 助手制作和检查 CK3 窗口外观。
---

# 观窗

使用 [scripts/run.py](scripts/run.py) 执行任务。它调用仓库内的观窗转换器，保留原有视觉检查，只以命令行和 JSON 与助手交互。游戏内的注册和玩法事件由 Mod 作者接入。

推荐由 Codex 中的 GPT 调用。DeepSeek（DS）或其他模型的本地助手也使用相同入口，宿主需能读写文件并执行命令。

## 第一次调用

复用或克隆 [观窗仓库](https://github.com/apo-so/guanchuang)。在仓库根目录，用本机 Python 运行随库的行宫窗口样例。实测环境为 Windows、Python 3.13 和 Edge 或 Chrome。

```powershell
$repo = (Get-Location).Path
$runner = Join-Path $repo '.agents/skills/guanchuang/scripts/run.py'
py -3.13 $runner demo
```

读 stdout 中的 JSON。如果得到 `SETUP_REQUIRED`，由助手复用项目专用虚拟环境，或按以下方式建立观窗专用环境并重试。后续命令使用同一解释器。

```powershell
$venv = Join-Path $env:LOCALAPPDATA 'Guanchuang/skill/py313'
if (-not (Test-Path -LiteralPath $venv)) { py -3.13 -m venv $venv }
$python = Join-Path $venv 'Scripts/python.exe'
& $python -m pip install -r (Join-Path $repo 'source/requirements.txt')
& $python $runner demo
```

如果宿主将本技能单独安装到了自己的技能目录，从那里运行脚本，在子命令前加 `--repo` 指向观窗克隆，或设置 `GUANCHUANG_ROOT`。已有仓库可直接读取本文件并运行入口，宿主无需支持特定的斜杠命令。

## 按任务选命令

- **网页转原生窗口**　用 `import 页面.html --window gc_layout`。默认画布为 1760×990。只转换某个容器时加 `--selector '#window'`。不同网页状态分别取样，可重复传 `--click`。按需要指定 `--viewport 1760x990`。相对图片和字体随源网页保留在本地。
- **原生窗口转整窗网页**　用 `list 文件.gui` 查看具名窗口，再用 `import 文件.gui --window 窗口名`。可选 `--game-root` 指向 CK3 的 `game` 目录。交付 `artifacts.editor`。要编辑时，从 `artifacts.manifest` 读取控件别名、可编辑字段和原值。
- **直接调整属性**　用 `edit 工作区 --target 别名 --set 字段=值`。例如导入随库的 `示例/gui/observatory.gui` 后，用 `--target frame --set width=680` 调整外框。也可给唯一控件名，或对同一控件重复 `--set`。交付校验后的 `.gui`、最小差分和回执。
- **已有编辑页下载物**　用 `verify 工作区 --request 编辑请求.json --gui 导出文件.gui`，匹配同一份原始源码后校验。

除 `list` 外，每次都用新的输出目录。省略 `--out` 时，入口优先使用用户文档的“观窗工作区”。若它位于输入目录内，则选用系统临时目录下的 Guanchuang-outputs。实际绝对路径在 JSON 的 `output` 中。也可用 `GUANCHUANG_OUTPUTS` 自定默认根目录。把结果留在测试候选中。

## 读结果并交付

| 状态 | 退出码 | 助手如何处理 |
| --- | --- | --- |
| `VERIFIED_SCOPED` / `LISTED` | 0 | 交付实际存在的文件路径。列窗时只报告窗口列表。 |
| `REVIEW_REQUIRED` | 3 | 标为待复核，指出报告中的具体控件，并给出对照图。 |
| `REJECTED` | 2 | 提供诊断和可取得的截图。区分源网页错误与转换器偏差，保留失败样本，修正后用新目录再跑。 |
| `ERROR` / `SETUP_REQUIRED` | 1 | 根据消息处理输入、依赖或运行环境。检查未执行时不报告通过。 |

以 `artifacts` 返回的路径为准。HTML 转换交付 `.gui` 和 `candidate_root` 中同相对位置的 DDS。审计以 `artifacts.audit` 为准。报告可见外观的检查结果，CK3 实机渲染和用户亲验分开记录。
