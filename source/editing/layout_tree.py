"""Read a fixed-position scene from the same AST and aliases used for export."""
import base64
import json
import re
from pathlib import Path
from core.syntax import parse_bytes

CONTAINERS={'window','widget','container','button','icon','textbox','text_single','text_multi','button_standard','image'}
LAYOUTS={'hbox','vbox','flowcontainer','gridbox','scrollarea','scrollwidget','dynamicgridbox'}

def tree_for(manifest):
    doc=parse_bytes(base64.b64decode(manifest['source_base64']),manifest['source'])
    root=next(n for n in doc.root.statements if n.key=='window' and n.value('name')==manifest['window'])
    aliases={v['owner_id']:k for k,v in manifest['targets'].items()}
    warnings=[]
    def walk(node):
        fields=manifest['targets'].get(aliases.get(node.node_id),{}).get('fields',{})
        children=[]
        for ch in node.statements:
            if not ch.has_body:continue
            if ch.key in CONTAINERS or ch.node_id in aliases:
                children.append(walk(ch))
            elif ch.key in LAYOUTS or ch.kind in ('type','template') or (ch.value('name') and ch.key not in ('state','animation')):
                warnings.append(f'{ch.value("name") or ch.key}：未展开的布局或模板')
        result={'name':node.value('name',node.key),'kind':node.key,'alias':aliases.get(node.node_id),
                'text':node.value('text',''),'anchor':node.value('layoutpolicy_horizontal',''),
                'orientation':node.value('parentanchor','') or node.value('layoutposition',''),
                'visible':node.value('visible','yes'),'children':children}
        if node.value('using') or node.occurrences('using'):
            warnings.append(f'{result["name"]}：继承的外观按只读占位处理')
        if node.occurrences('size') and 'width' not in fields:
            warnings.append(f'{result["name"]}：非固定像素尺寸')
        if node.key in LAYOUTS:
            warnings.append(f'{result["name"]}：流式布局的子项未作原生分配')
        return result
    return walk(root),warnings

def local_labels(tree,profile):
    wanted=set()
    def collect(node):
        if re.fullmatch(r'[A-Za-z0-9_.-]+',node['text']):wanted.add(node['text'])
        for ch in node['children']: collect(ch)
    collect(tree)
    labels={}
    if not wanted:return labels
    for root in profile.get('read_only_roots',[])[:2]:
        loc=Path(root)/'localization/simp_chinese'
        if not loc.is_dir():continue
        for path in sorted(loc.rglob('*.yml')):
            if not path.resolve().is_relative_to(Path(root).resolve()):continue
            try:
                with path.open(encoding='utf-8-sig') as f:
                    for line in f:
                        key,sep,rest=line.partition(':')
                        key=key.strip()
                        if sep and key in wanted and key not in labels:
                            m=re.search(r'"((?:\\.|[^"\\])*)"',rest)
                            if m:labels[key]=m[1].replace(r'\n','\n').replace(r'\"','"')
            except (OSError,UnicodeError):
                continue
            if labels.keys()>=wanted:return labels
    return labels

def attach_layout(page,manifest,profile):
    tree,missing=tree_for(manifest)
    data=json.dumps({'tree':tree,'warnings':missing,'labels':local_labels(tree,profile)},ensure_ascii=False).replace('<','\\u003c')
    style="""<style>#gc-layout{padding:14px}.gc-layout-top{display:flex;gap:16px;flex-wrap:wrap;align-items:center}.gc-layout-top label{display:inline-flex;align-items:center;gap:6px;margin:3px}.gc-layout-top input,.gc-layout-top select{width:auto}.gc-pan{overflow:auto;max-height:80vh;background:#17191d}.gc-scene{position:relative;isolation:isolate}.gc-item{position:absolute;box-sizing:border-box;cursor:pointer}.gc-item[data-selected="yes"]{outline:1px dashed #e6b761;outline-offset:-1px}.gc-item[data-kind="textbox"]{display:flex;white-space:pre-wrap;line-height:1.2;overflow:hidden;user-select:none}.gc-item[data-kind="icon"]{background-size:100% 100%;background-repeat:no-repeat}.gc-scene,.gc-item{font-family:GuanchuangLayoutFont,"Microsoft YaHei",sans-serif}.gc-layout-note{font-size:13px}</style>"""
    for root in profile.get('read_only_roots',[])[:2]:
        font=Path(root)/'fonts/Noto_Sans_SC/NotoSansSC-Medium.otf'
        if font.is_file() and font.resolve().is_relative_to(Path(root).resolve()):
            font64=base64.b64encode(font.read_bytes()).decode('ascii')
            style+="<style>@font-face{font-family:GuanchuangLayoutFont;src:url(data:font/otf;base64,"+font64+")}</style>"
            break
    panel="""<section id="gc-layout"><h2>整窗布局</h2><p>点击画面上的控件，用下方属性栏调整。虚线标出当前选择。</p><div class="gc-layout-top"><label>查看比例 <select id="gc-zoom"><option value=".5">50%</option><option value=".75">75%</option><option value="1" selected>100%</option></select></label><label><input type="checkbox" id="gc-origin"> 显示窗口在画布上的位置</label></div><details id="gc-states"><summary>可见条件与布局提示</summary><div class="gc-layout-top" id="gc-conditions"></div><p id="gc-warnings" class="gc-layout-note"></p></details><div class="gc-pan"><div id="gc-sizer"><div class="gc-scene" id="gc-scene"></div></div></div></section>"""
    js=(Path(__file__).parent/'layout_view.js').read_text('utf-8')
    return page.replace('<div class="grid">',style+panel+'<div class="grid">',1).replace('</html>','<script id="gc-model" type="application/json">'+data+'</script><script>'+js+'</script></html>')
