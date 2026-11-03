"""Reproduce three visual failures using the public converter and a synthetic window."""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "source"))

from editing.appearance import apply_appearance, bind_appearance, make_request
from editing.html_layout import convert_html
from editing.visual_audit import all_nodes, audit_html, render_preview
from guanchuang import import_gui


def change_field(gui, control, field, value):
    raw = gui.read_bytes()
    manifest = bind_appearance(
        raw, "gui/gc_contract.gui", "gc_contract", {"target": {"name": control}}
    )
    request = make_request(manifest, {"target": {field: value}})
    changed, _, receipt = apply_appearance(raw, manifest, request)
    if len(receipt["patches"]) != 1:
        raise RuntimeError("Expected one source token to change")
    gui.write_bytes(changed)


def save_comparison(reference, observed, output):
    with Image.open(reference) as left, Image.open(observed) as right:
        left, right = left.convert("RGB"), right.convert("RGB")
        if left.size != right.size or not ImageChops.difference(left, right).getbbox():
            raise RuntimeError("The two browser screenshots should visibly differ")
        w, h = left.size
        canvas = Image.new("RGB", (2 * w + 8, h), "#777777")
        canvas.paste(left, (0, 0))
        canvas.paste(right, (w + 8, 0))
        canvas.save(output)


def run(output):
    if output.exists():
        raise FileExistsError(f"Choose a new output directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    fixture = REPO / "source/tests/fixtures/visual_contract.html"
    with tempfile.TemporaryDirectory(prefix="gc-faults-", dir=output.parent) as tmp:
        work = Path(tmp)
        base = work / "control"
        res = convert_html(fixture, base, "gc_contract", "#paper", (), (800, 480))
        gui = Path(res["gui"])
        original = (base / gui).parents[1]
        gui_relative = Path("gui/gc_contract.gui")
        scene = json.loads((base / "layout.json").read_text("utf-8"))
        swatch = next(node for node in all_nodes(scene["tree"]) if node["native_name"] == "swatch")
        checked = json.loads((base / "visual-audit.json").read_text("utf-8"))
        if checked["errors"]:
            raise RuntimeError("The unmodified fixture must have no structural errors")

        results = work / "results"
        results.mkdir()
        reports = {}
        cases = [
            ("text-width", "TEXT_ALLOCATION", "value"),
            ("wrong-texture", "TEXTURE_PIXELS", swatch["texture"]),
            ("moved-badge", "NATIVE_BOX", "badge"),
        ]
        for name, expected_code, expected_owner in cases:
            staged = work / name
            candidate = staged / "candidate"
            shutil.copytree(original, candidate)
            broken_gui = candidate / gui_relative
            if name == "text-width":
                change_field(broken_gui, "value_text_1", "width", 4)
            elif name == "wrong-texture":
                Image.new("RGBA", (1, 1), "red").save(candidate / swatch["texture"], format="DDS")
            else:
                change_field(broken_gui, "badge", "position_x", 900)

            report = audit_html(staged, scene, gui_relative)
            errors = {(item["code"], item["owner"]) for item in report["errors"]}
            if report["status"] != "REJECTED" or (expected_code, expected_owner) not in errors:
                raise RuntimeError(f"Expected {expected_code} for {expected_owner}, got {report}")

            # The normal converter stops on structural errors. Render this temporary
            # rejected copy separately to illustrate the fault, never to publish it.
            editor = import_gui(broken_gui, work / (name + "-editor"), "gc_contract", check_visual=False)
            observed = work / (name + ".png")
            reference = base / "source-window.png"
            with Image.open(reference) as im:
                size = im.size
            render_preview(editor["editor"], observed, size, base / "backdrop.png")
            save_comparison(reference, observed, results / (name + ".png"))
            reports[name] = {"status": report["status"], "errors": report["errors"]}
            print(f"{name}: {report['status']} / {expected_code}")

        (results / "results.json").write_text(
            json.dumps(reports, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        if output.exists():
            raise FileExistsError(f"Choose a new output directory: {output}")
        results.rename(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="A new diagnostics directory")
    run(parser.parse_args().out.resolve())
