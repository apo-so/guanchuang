"""Exercise the public skill through its command-line interface, without a game or desktop."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents/skills/guanchuang"


class HeadlessSkill(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="guanchuang-skill-test-")
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)

    def call(self, *args, script=None, env=None):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(script or SKILL / "scripts/run.py"), *map(str, args)],
            cwd=self.work, capture_output=True, encoding="utf-8", timeout=120,
            env={**os.environ, "GUANCHUANG_OUTPUTS": str(self.work / "outputs"), **(env or {})},
        )
        try:
            report = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            self.fail(f"Skill did not return JSON: {result.stderr[-500:]}")
        return result.returncode, report

    def test_detached_skill_converts_html_and_does_not_reuse_output(self):
        installed = self.work / "assistant skills" / "guanchuang"
        shutil.copytree(SKILL, installed)
        script = installed / "scripts/run.py"
        rc, result = self.call("--repo", ROOT, "demo", script=script)
        self.assertEqual((rc, result["status"]), (0, "VERIFIED_SCOPED"), result)
        files = result["artifacts"]
        self.assertTrue(Path(files["gui"]).is_file())
        self.assertTrue(any(Path(files["gfx"]).rglob("*.dds")))
        for key in ("source_image", "readback_image", "audit"):
            self.assertTrue(Path(files[key]).is_file(), key)
        previous = Path(files["gui"]).read_bytes()
        rc, repeated = self.call("--repo", ROOT, "demo", "--out", result["output"], script=script)
        self.assertEqual((rc, repeated["status"]), (1, "ERROR"))
        self.assertNotIn("artifacts", repeated)
        self.assertEqual(Path(files["gui"]).read_bytes(), previous)

    def test_gui_edit_and_verify_leave_original_bytes_intact(self):
        gui = ROOT / "示例/gui/observatory.gui"
        original = gui.read_bytes()
        rc, names = self.call("list", gui)
        self.assertEqual((rc, names["windows"]), (0, ["gc_observatory"]))
        rc, workspace = self.call("import", gui, "--window", names["windows"][0])
        self.assertEqual((rc, workspace["status"]), (0, "VERIFIED_SCOPED"), workspace)
        self.assertTrue(Path(workspace["artifacts"]["editor"]).is_file())

        rc, edited = self.call("edit", workspace["output"], "--target", "frame", "--set", "width=680")
        self.assertEqual((rc, edited["status"]), (0, "VERIFIED_SCOPED"), edited)
        self.assertEqual(Path(edited["artifacts"]["baseline"]).read_bytes(), original)
        receipt = json.loads(Path(edited["artifacts"]["receipt"]).read_text("utf-8"))
        self.assertEqual([(p["old_token"], p["new_token"]) for p in receipt["patches"]], [("620", "680")])
        self.assertTrue(receipt["untouched_bytes_verified"])
        rc, checked = self.call("verify", workspace["output"], "--request", Path(edited["output"]) / "request.json",
                                "--gui", edited["artifacts"]["gui"])
        self.assertEqual((rc, checked["status"]), (0, "VERIFIED_SCOPED"), checked)
        self.assertEqual(Path(checked["artifacts"]["gui"]).read_bytes(), Path(edited["artifacts"]["gui"]).read_bytes())
        self.assertEqual(gui.read_bytes(), original)

    def test_review_and_rejection_keep_their_distinct_artifacts(self):
        src = self.work / "web page"
        src.mkdir()
        html = src / "window.html"
        base = '<style>*{box-sizing:border-box}body{margin:0}main{width:260px;height:120px;background:#fff}h1{margin:0;width:120px;font:20px Arial;white-space:nowrap;%s}</style><main data-gc-window><h1>WWWWWW</h1></main>'
        html.write_text(base % "box-shadow:3px 4px 5px #555", "utf-8")
        rc, review = self.call("import", html, "--window", "gc_example")
        self.assertEqual((rc, review["status"]), (3, "REVIEW_REQUIRED"), review)
        self.assertIn("待复核", Path(review["artifacts"]["gui"]).parts)
        self.assertTrue(review["review"])

        html.write_text(base % "transform:scaleX(.12);transform-origin:top left", "utf-8")
        rc, refused = self.call("import", html, "--window", "gc_example")
        self.assertEqual((rc, refused["status"]), (2, "REJECTED"), refused)
        self.assertTrue(Path(refused["artifacts"]["audit"]).is_file())
        self.assertTrue(refused["errors"])
        self.assertNotIn("gui", refused["artifacts"])
        self.assertFalse(list(Path(refused["output"]).rglob("*.gui")))


if __name__ == "__main__":
    unittest.main()
