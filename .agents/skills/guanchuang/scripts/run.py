"""Headless skill entry point for the existing Guanchuang engine and visual audit."""
import argparse
import json
import os
import sys
import tempfile
import uuid
from importlib import metadata
from pathlib import Path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def engine_root(explicit):
    location = explicit or os.environ.get("GUANCHUANG_ROOT")
    candidates = [Path(location).expanduser().resolve()] if location else Path(__file__).resolve().parents
    for root in candidates:
        if (root / "source/guanchuang.py").is_file() and (root / "source/editing/visual_audit.py").is_file():
            return root
    raise ValueError("找不到观窗源码。请克隆 apo-so/guanchuang，再用 --repo 指定仓库根目录。")


def missing_packages(root):
    missing = []
    for line in (root / "source/requirements.txt").read_text("utf-8").splitlines():
        item = line.partition("#")[0].strip()
        if not item:
            continue
        package, separator, required = item.partition("==")
        if not separator:
            raise ValueError("当前依赖清单需要按 requirements.txt 安装。")
        try:
            installed = metadata.version(package)
        except metadata.PackageNotFoundError:
            installed = None
        if installed != required:
            missing.append(item)
    return missing


def output_dir(explicit):
    if explicit:
        dest = Path(explicit).expanduser().resolve()
    else:
        base = os.environ.get("GUANCHUANG_OUTPUTS") or Path.home() / "Documents" / "观窗工作区"
        dest = (Path(base).expanduser() / ("AI-" + uuid.uuid4().hex)).resolve()
    if os.path.lexists(dest):
        raise ValueError("输出目录已经存在，请选择一个新的目录：" + str(dest))
    return dest


def apply_fields(workspace, target, assignments, dest):
    from editing.appearance import apply_appearance, make_request
    from guanchuang import verify_export

    manifest = read_json(workspace / "manifest.json")
    targets = manifest["targets"]
    if target in targets:
        alias = target
    else:
        matches = [key for key, node in targets.items() if node["name"] == target]
        if len(matches) != 1:
            raise ValueError("请从 manifest.json 选择唯一的控件名或别名：" + target)
        alias = matches[0]

    fields = targets[alias]["fields"]
    edits = {}
    for assignment in assignments:
        key, sep, value = assignment.partition("=")
        if not sep or key not in fields or key in edits:
            raise ValueError("字段缺失、不可编辑或重复：" + key)
        if type(fields[key]["value"]) in (int, float):
            value = json.loads(value)
            if type(value) not in (int, float):
                raise ValueError("需要数值：" + key)
        edits[key] = value
    request = make_request(manifest, {alias: edits})
    draft, _, _ = apply_appearance((workspace / "original.gui").read_bytes(), manifest, request)
    with tempfile.TemporaryDirectory(prefix="guanchuang-skill-edit-") as temp:
        req, gui = Path(temp) / "request.json", Path(temp) / "edited.gui"
        req.write_text(json.dumps(request, ensure_ascii=False), "utf-8")
        gui.write_bytes(draft)
        return verify_export(workspace, req, gui, dest)


def parse_args():
    parser = argparse.ArgumentParser(description="观窗本地 AI 接口，结果以 JSON 输出")
    parser.add_argument("--repo", help="观窗仓库根目录，独立安装 skill 时可指定")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="列出原生文件中的具名窗口").add_argument("gui", type=Path)
    demo = commands.add_parser("demo", help="用随库 HTML 生成行宫窗口")
    convert = commands.add_parser("import", help="本地 HTML 转原生布局，或 .gui 转整窗编辑页")
    convert.add_argument("input", type=Path)
    convert.add_argument("--window")
    convert.add_argument("--game-root", type=Path)
    convert.add_argument("--selector", help="HTML 的窗口 CSS 选择器")
    convert.add_argument("--click", action="append", default=[], help="HTML 取样前的点击，可重复")
    convert.add_argument("--viewport", help="HTML 画布，例如 1760x990")
    edit = commands.add_parser("edit", help="修改已导入工作区中的显式字段并校验导出")
    edit.add_argument("workspace", type=Path)
    edit.add_argument("--target", required=True)
    edit.add_argument("--set", dest="assignments", action="append", required=True, metavar="字段=值")
    verify = commands.add_parser("verify", help="校验编辑页先前导出的 GUI 与请求")
    verify.add_argument("workspace", type=Path)
    verify.add_argument("--request", type=Path, required=True)
    verify.add_argument("--gui", type=Path, required=True)
    for sub in (demo, convert, edit, verify):
        sub.add_argument("--out", help="新的输出目录，可省略")
    return parser.parse_args()


def execute(args, root, dest):
    from guanchuang import import_gui, source_info, verify_export
    from editing.html_layout import convert_html

    if args.command == "list":
        _, source, doc, windows = source_info(args.gui)
        return {"status": "LISTED", "source": source, "sha256": doc.integrity["sha256"],
                "windows": [node.value("name") for node in windows]}
    if args.command == "demo":
        return convert_html(root / "示例/外观草图.html", dest, "gc_palace")
    if args.command == "edit":
        return apply_fields(args.workspace.resolve(strict=True), args.target, args.assignments, dest)
    if args.command == "verify":
        return verify_export(args.workspace, args.request, args.gui, dest)
    source = args.input.resolve(strict=True)
    if source.suffix.lower() in (".html", ".htm"):
        size = tuple(map(int, (args.viewport or "1760x990").lower().split("x")))
        return convert_html(source, dest, args.window, args.selector, args.click, size, args.game_root)
    if args.selector or args.click or args.viewport:
        raise ValueError("--selector、--click、--viewport 用于 HTML 输入。")
    return import_gui(source, dest, args.window, args.game_root)


def outcome(dest, result):
    audit_path = dest / "visual-audit.json"
    audit = read_json(audit_path)
    status = audit["status"]
    if status not in {"VERIFIED_SCOPED", "REVIEW_REQUIRED", "REJECTED"}:
        raise ValueError("未知的视觉检查状态：" + str(status))
    artifacts = {"audit": str(audit_path)}
    for key, name in (("editor", "editor.html"), ("manifest", "manifest.json"), ("receipt", "receipt.json"),
                      ("source_image", "source-window.png"), ("readback_image", "readback-window.png"),
                      ("diff", "changes.diff"), ("baseline", "baseline.gui")):
        if (dest / name).is_file():
            artifacts[key] = str(dest / name)
    gui = result.get("gui") or result.get("draft")
    if gui and status != "REJECTED":
        path = (dest / gui).resolve(strict=True)
        if not path.is_relative_to(dest):
            raise ValueError("候选不在本次输出目录。")
        artifacts["gui"] = str(path)
        if result.get("gui"):
            artifacts["candidate_root"] = str(path.parents[1])
            gfx = path.parents[1] / "gfx"
            if gfx.is_dir():
                artifacts["gfx"] = str(gfx)
    return {"status": status, "output": str(dest), "artifacts": artifacts,
            "errors": audit.get("errors", [])[:3], "review": audit.get("review", [])[:3],
            "native_render": audit.get("native_engine", "NOT_RUN")}


def main():
    args = parse_args()
    dest = None
    try:
        root = engine_root(args.repo)
        missing = missing_packages(root)
        if missing:
            return {"status": "SETUP_REQUIRED", "missing": missing,
                    "requirements": str(root / "source/requirements.txt")}
        sys.path.insert(0, str(root / "source"))
        from playwright.sync_api import Error as BrowserError
        if args.command != "list":
            dest = output_dir(args.out)
        try:
            result = execute(args, root, dest)
        except BrowserError as exc:
            return {"status": "ERROR", "message": str(exc)}
        return outcome(dest, result) if dest is not None else result
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        if dest and str(exc) == "外观校验拒绝了候选，只保留诊断：" + str(dest / "visual-audit.json"):
            return outcome(dest, {})
        return {"status": "ERROR", "message": str(exc)}


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.stdout.reconfigure(encoding="utf-8")
    report = main()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit({"LISTED": 0, "VERIFIED_SCOPED": 0, "REVIEW_REQUIRED": 3, "REJECTED": 2}.get(report["status"], 1))
