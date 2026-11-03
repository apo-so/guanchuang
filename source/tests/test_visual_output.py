import hashlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from editing.html_layout import build_gui,convert_html
from editing.visual_audit import inspect_generated
from guanchuang import import_gui

class VisualContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='GC-visual-regression-')
        cls.root=Path(cls.tmp.name)
        cls.input=Path(__file__).parent/'fixtures/visual_contract.html'
        cls.positive=cls.root/'original'
        cls.opts=(cls.input,cls.positive,'gc_contract','#paper',(),(800,480))
        cls.result=convert_html(*cls.opts)
        cls.snapshot=json.loads((cls.positive/'layout.json').read_text('utf-8'))
        cls.candidate=(cls.positive/cls.result['gui']).parents[1]
        cls.raw=(cls.positive/cls.result['gui']).read_bytes()
    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
    def test_normal_conversion_checks_default_entry(self):
        report=json.loads((self.positive/'visual-audit.json').read_text('utf-8'))
        self.assertFalse(report['errors'],report)
        self.assertLess(report['raster']['whole_window']['mean_abs_rgb'],4)
        if report['raster']['regions_to_review']:
            self.assertEqual('REVIEW_REQUIRED',report['status'])
            self.assertEqual('待复核',Path(self.result['gui']).parts[0])
            self.assertFalse((self.positive/'candidate').exists())
        else:self.assertEqual('VERIFIED_SCOPED',report['status'])
        self.assertGreaterEqual(report['counts']['text_lines'],4)
        self.assertGreaterEqual(report['counts']['texture_files'],2)
        self.assertTrue((self.positive/'source-window.png').is_file())
        self.assertTrue((self.positive/'readback-window.png').is_file())
    def test_exact_graphic_positive_control_is_publishable(self):
        srcdir=self.root/'known-geometry';srcdir.mkdir()
        file=srcdir/'positive.html'
        file.write_text('<style>*{box-sizing:border-box}body{margin:0}main{position:absolute;left:32px;top:24px;width:250px;height:120px;background:#204050;display:grid;grid-template-columns:70px 1fr;gap:9px;padding:12px}i{display:block;background:#ada472;border:2px solid #311}</style><main data-gc-window><i id="left"></i><i id="right"></i></main>','utf-8')
        out=self.root/'known-positive'
        res=convert_html(file,out,'gc_exact',None,(),(800,480))
        self.assertEqual('VERIFIED_SCOPED',res['visual_status'])
        self.assertTrue((out/'candidate/gui/gc_exact.gui').is_file())
        stats=json.loads((out/'visual-audit.json').read_text('utf-8'))['raster']['whole_window']
        self.assertEqual(0,stats['mean_abs_rgb'])
    def test_narrow_text_is_diagnosed_with_no_native_output(self):
        def narrow(scene,name):
            raw=build_gui(scene,name)
            regex=rb'(textbox = \{ name = "value_text_1" position = \{ [^}]+ \} size = \{ )\d+'
            raw,n=re.subn(regex,rb'\g<1>4',raw)
            self.assertEqual(1,n)
            return raw
        out=self.root/'bad-width'
        with patch('editing.html_layout.build_gui',side_effect=narrow):
            with self.assertRaisesRegex(ValueError,'外观校验拒绝'):
                convert_html(self.input,out,'gc_contract','#paper',(),(800,480))
        self.assertFalse((out/'candidate').exists())
        report=json.loads((out/'visual-audit.json').read_text('utf-8'))
        self.assertEqual('REJECTED',report['status'])
        self.assertIn(('TEXT_ALLOCATION','value'),[(i['code'],i['owner']) for i in report['errors']])
    def test_offset_order_text_and_texture_corruption_are_visible(self):
        regex=rb'(widget = \{ name = "badge" position = \{ )-?\d+'
        moved,n=re.subn(regex,rb'\g<1>900',self.raw)
        self.assertEqual(n,1)
        _,errs=inspect_generated(moved,'gc_contract',self.snapshot,self.candidate)
        self.assertIn('NATIVE_BOX',[i['code'] for i in errs])
        renamed=self.raw.replace(b'widget = { name = "swatch"',b'widget = { name = "wrong_owner"')
        _,errs=inspect_generated(renamed,'gc_contract',self.snapshot,self.candidate)
        self.assertIn('CHILD_ORDER',[i['code'] for i in errs])
        altered=self.raw.replace(b'japanese_manor',b'wrong_value')
        _,errs=inspect_generated(altered,'gc_contract',self.snapshot,self.candidate)
        self.assertIn('TEXT_VALUE',[i['code'] for i in errs])
        copied=self.root/'bad-texture';shutil.copytree(self.candidate,copied)
        rel=next(iter(self.snapshot['paint_fingerprints']))
        Image.new('RGBA',(1,1),'red').save(copied/rel,format='DDS')
        _,errs=inspect_generated(self.raw,'gc_contract',self.snapshot,copied)
        self.assertIn('TEXTURE_PIXELS',[i['code'] for i in errs])
    def test_unreconstructed_visuals_do_not_report_a_pass(self):
        srcdir=self.root/'shadow-input';srcdir.mkdir()
        html=srcdir/'outside.html'
        html.write_text(self.input.read_text('utf-8').replace('</style>','#swatch{box-shadow:5px 5px 8px #fff}</style>'),'utf-8')
        out=self.root/'shadow'
        res=convert_html(html,out,'gc_shadow','#paper',(),(800,480))
        self.assertEqual('REVIEW_REQUIRED',res['visual_status'])
        self.assertTrue(any('投影' in s for s in json.loads((out/'visual-audit.json').read_text('utf-8'))['review']))
    def test_bound_renderer_drift_is_caught(self):
        from editing.visual_audit import bound_audit
        case=self.root/'drift'
        import_gui(self.positive/self.result['gui'],case)
        html=case/'editor.html'
        src=html.read_text('utf-8')
        html.write_text(src.replace('</html>','<style>#gc-scene [data-name="badge"]{left:900px!important}</style></html>'),'utf-8')
        report=bound_audit(case)
        self.assertEqual('REJECTED',report['status'])
        self.assertIn(('BOUND_GUI_BOX','badge'),[(err['code'],err['owner']) for err in report['errors']])
    def test_native_to_browser_checks_visible_layout(self):
        out=self.root/'editor'
        res=import_gui(self.positive/self.result['gui'],out)
        report=json.loads((out/'visual-audit.json').read_text('utf-8'))
        self.assertEqual('VERIFIED_SCOPED',res['visual_status'],report)
        self.assertGreater(report['observed_explicit_boxes'],10)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(),report['source_sha256'])
if __name__=='__main__':unittest.main()
