"""Measure one local webpage state and reconstruct its visual elements as CK3 GUI."""
import hashlib
import io
import json
import math
import mimetypes
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from PIL import Image
from core.syntax import parse_bytes
from editing.title import _new_output, require

ORIGIN = 'http://guanchuang.invalid'
PAINT_PAGE = '/__guanchuang_visual_paint__'
PAINT_HTML = '<meta charset="utf-8"><style>*{box-sizing:border-box}html,body{margin:0;background:transparent}#tile{position:absolute;left:0;top:0;overflow:hidden}#tile img{display:block;width:100%;height:100%}</style><div id="tile"></div>'
PAINT_SCRIPT = """async ({paint,w,h}) => {
 const tile=document.getElementById('tile'); tile.replaceChildren(); tile.style.cssText='';
 Object.assign(tile.style,paint.style,{width:w+'px',height:h+'px',opacity:String(paint.alpha)});
 if (paint.image) {
   const im=new Image(); Object.assign(im.style,{objectFit:paint.style.objectFit,objectPosition:paint.style.objectPosition});
   im.src=paint.image; await im.decode();tile.appendChild(im);
 }
}"""

def browser_path():
    for name in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA', 'ProgramW6432'):
        base = os.environ.get(name)
        if base:
            for rel in ('Microsoft/Edge/Application/msedge.exe','Google/Chrome/Application/chrome.exe'):
                path = Path(base)/rel
                if path.is_file():
                    return str(path)
    return None

def serve_local(route, source):
    address = urlsplit(route.request.url)
    if address.hostname != 'guanchuang.invalid' or address.scheme != 'http':
        route.abort()
        return
    if address.path == PAINT_PAGE:
        route.fulfill(content_type='text/html; charset=utf-8', body=PAINT_HTML)
        return
    path = (source.parent/unquote(address.path).lstrip('/')).resolve()
    if not path.is_relative_to(source.parent) or not path.is_file():
        route.fulfill(status=404,body='Not found')
        return
    mime = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
    if path.suffix.lower() in ('.html','.htm'):
        mime = 'text/html; charset=utf-8'
    route.fulfill(body=path.read_bytes(),content_type=mime)

def measure(source, selector, clicks, viewport, candidate, dest, name):
    from playwright.sync_api import sync_playwright, Error as BrowserError
    warnings=[]
    js = (Path(__file__).parent/'measure_layout.js').read_text('utf-8')
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch(executable_path=browser_path(),headless=True)
            try:
                ctx = browser.new_context(viewport=dict(zip(('width','height'),viewport)),device_scale_factor=1,
                                          reduced_motion='reduce',service_workers='block',accept_downloads=False)
                ctx.route('**/*',lambda route:serve_local(route,source))
                page=ctx.new_page()
                page.goto(ORIGIN+'/'+quote(source.name),wait_until='load',timeout=15000)
                for css in clicks:
                    el=page.locator(css)
                    require(el.count()==1,'状态选择器必须唯一：'+css)
                    el.click(timeout=4000)
                page.mouse.move(0,0)
                page.evaluate('() => document.fonts.ready')
                if selector:
                    root=page.locator(selector)
                else:
                    root=next(page.locator(css) for css in ('[data-gc-window]','#window','main','body') if page.locator(css).count())
                require(root.count()==1 and root.is_visible(),'请指定一个可见且唯一的窗口 CSS 选择器')
                snapshot=root.evaluate(js)
                require(snapshot['viewport']==list(viewport) and snapshot['dpr']==1,'浏览器视口比例与请求不符')
                page.screenshot(path=str(dest/'source.png'),animations='disabled',timeout=15000)
                root.screenshot(path=str(dest/'source-window.png'),animations='disabled')
                old=root.evaluate('e=>[e.style.getPropertyValue("opacity"),e.style.getPropertyPriority("opacity")]')
                root.evaluate('e=>e.style.setProperty("opacity","0","important")')
                root.screenshot(path=str(dest/'backdrop.png'),animations='disabled')
                root.evaluate('(e,old)=>{if(old[0])e.style.setProperty("opacity",old[0],old[1]);else e.style.removeProperty("opacity")}',old)
                tile=ctx.new_page()
                tile.goto(ORIGIN+PAINT_PAGE)
                assets=candidate/'gfx'/'guanchuang'/name
                assets.mkdir(parents=True)
                cache={}
                fingerprints={}
                def save_paints(node):
                    paint=node.pop('paint')
                    if paint:
                        w,h=[max(1,round(node['box'][k])) for k in ('w','h')]
                        require(w<=8192 and h<=8192,'单层尺寸超过 8192 像素：'+node['id'])
                        key=json.dumps([w,h,paint],sort_keys=True)
                        if key not in cache:
                            tile.set_viewport_size({'width':max(32,w),'height':max(32,h)})
                            tile.evaluate(PAINT_SCRIPT,dict(paint=paint,w=w,h=h))
                            urls=re.findall(r'url\(["\']?([^"\')]+)',paint['style']['backgroundImage'])
                            if urls:
                                tile.evaluate('async urls=>{ await Promise.all(urls.map(src=>{const im=new Image();im.src=src;return im.decode()})) }',urls)
                            data=tile.locator('#tile').screenshot(omit_background=True,animations='disabled')
                            texture=assets/(hashlib.sha256(data).hexdigest()[:20]+'.dds')
                            with Image.open(io.BytesIO(data)) as im:
                                image=im.convert('RGBA')
                                image.save(texture,format='DDS')
                                rel=texture.relative_to(candidate).as_posix()
                                fingerprints[rel]=[list(image.size),hashlib.sha256(image.tobytes()).hexdigest()]
                            cache[key]=rel
                        node['texture']=cache[key]
                    for child in node['children']:
                        save_paints(child)
                save_paints(snapshot['tree'])
                snapshot['warnings']+=warnings
                snapshot['texture_count']=len(set(cache.values()))
                snapshot['paint_fingerprints']=fingerprints
                return snapshot
            finally:
                browser.close()
    except BrowserError as exc:
        raise ValueError('浏览器布局读取失败：'+str(exc).split('Call log:')[0]) from exc

def quoted(value):
    return '"'+value.replace('\\','\\\\').replace('"','\\"')+'"'

def pixel(value):
    return math.floor(value+0.5)

def bounds(box):
    x,y=pixel(box['x']),pixel(box['y'])
    return x,y,max(1,pixel(box['x']+box['w'])-x),max(1,pixel(box['y']+box['h'])-y)

def rgba(text,alpha):
    parts=re.findall(r'[\d.]+',text)
    require(text.startswith('rgb') and len(parts) in (3,4),'暂不支持网页颜色 '+text)
    vals=[float(v)/255 for v in parts[:3]]
    vals.append(alpha*(float(parts[3]) if len(parts)==4 else 1))
    return ' '.join(('%0.6f'%min(1,max(0,v))).rstrip('0').rstrip('.') for v in vals)

def build_gui(snapshot,name):
    lines=[]
    used=set()
    counts=Counter()
    def identity(value):
        stem=re.sub(r'[^A-Za-z0-9_-]+','_',value).strip('_') or 'item'
        uid=stem
        while uid in used:
            counts[stem]+=1
            uid=f'{stem}_{counts[stem]}'
        used.add(uid)
        return uid
    def emit(node, parent_xy, depth):
        x,y,w,h=bounds(node['box'])
        tag='window' if depth==0 else 'widget'
        uid=identity(name if depth==0 else node['id'])
        node['native_name']=uid
        pad='    '*depth
        lines.append(f'{pad}{tag} = {{ name = {quoted(uid)} position = {{ {x-parent_xy[0]} {y-parent_xy[1]} }} size = {{ {w} {h} }}')
        if node.get('texture'):
            skin=identity(uid+'_skin')
            lines.append(f'{pad}    icon = {{ name = {quoted(skin)} position = {{ 0 0 }} size = {{ {w} {h} }} texture = {quoted(node["texture"])} alwaystransparent = yes }}')
        for i,row in enumerate(node['texts'],1):
            tx,ty,tw,th=bounds(row)
            tw=max(tw+2,x+w-tx)  # Preserve a measured line even if engine glyph advances differ slightly.
            label=identity(uid+'_text_'+str(i))
            row['native_name']=label
            # Each visible line remains an individually editable native textbox.
            lines.append(f'{pad}    textbox = {{ name = {quoted(label)} position = {{ {tx-x} {ty-y} }} size = {{ {tw} {th} }} raw_text = {quoted(row["text"])} fontsize = {max(1,pixel(row["font"]))} font = StandardGameFont fontcolor = {{ {rgba(row["color"],row["alpha"])} }} align = left|nobaseline autoresize = no alwaystransparent = yes }}')
        for child in node['children']:
            emit(child,(x,y),depth+1)
        lines.append(pad+'}')
    emit(snapshot['tree'],(0,0),0)
    raw=('\n'.join(lines)+'\n').encode('utf-8')
    doc=parse_bytes(raw,'gui/'+name+'.gui')
    require(not doc.diagnostics and doc.root.statements[0].value('name')==name,'重建文件未通过 GUI 解析')
    return raw

def convert_html(file,out,name=None,selector=None,clicks=(),viewport=(1760,990),game_root=None):
    source=Path(file).resolve(strict=True)
    require(source.is_file() and source.suffix.lower() in ('.html','.htm'),'请选择本地 HTML')
    name=name or 'gc_'+(re.sub(r'[^A-Za-z0-9_]+','_',source.stem).strip('_') or 'layout')
    require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,99}',name) is not None,'窗口名需使用 ASCII 字母、数字和下划线')
    require(len(viewport)==2 and all(isinstance(v,int) and 32<=v<=8192 for v in viewport),'画布尺寸有效范围 32–8192')
    dest=_new_output(out,[source.parent])
    dest.parent.mkdir(parents=True,exist_ok=True)
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(dir=dest.parent,prefix='.guanchuang-layout-') as tmp:
        staged=Path(tmp)/'result'
        candidate=staged/'candidate'
        (candidate/'gui').mkdir(parents=True)
        snapshot=measure(source,selector,clicks,viewport,candidate,staged,name)
        raw=build_gui(snapshot,name)
        gui=Path('gui')/(name+'.gui')
        (candidate/gui).write_bytes(raw)
        require(hashlib.sha256(source.read_bytes()).hexdigest()==before,'转换期间源网页变化')
        (staged/'layout.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),'utf-8')
        from editing.visual_audit import audit_html, commit_new, publish_layout
        audit=publish_layout(staged,dest,audit_html(staged,snapshot,gui,game_root))
        relative_gui=Path('candidate')/gui
        if audit['status']=='REVIEW_REQUIRED':
            review=staged/'待复核'
            review.mkdir()
            commit_new(candidate,review/'candidate')
            relative_gui=Path('待复核')/relative_gui
        receipt=dict(status='HTML_VISUAL_LAYOUT_'+audit['status'],source=str(source),source_sha256=before,
                     visual_status=audit['status'],visual_audit='visual-audit.json',
                     gui=relative_gui.as_posix(),gui_sha256=hashlib.sha256(raw).hexdigest(),
                     selector=selector,clicks=list(clicks),viewport=list(viewport),native_render='NOT_RUN',
                     limits=snapshot['warnings'],textures=snapshot['texture_count'])
        (staged/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
        commit_new(staged,dest)
    return dict(receipt,output=str(dest))
