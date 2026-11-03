"""Check actual generated GUI bytes, its textures and its rendered browser layout before release."""
import base64
import hashlib
import json
import re
import tempfile
from pathlib import Path
from PIL import Image, ImageChops, ImageStat
from core.syntax import parse_bytes

BOX_TOLERANCE=1.0
GLOBAL_MAX_CHANGED=.04
GLOBAL_MAX_MEAN=4
LOCAL_MAX_CHANGED=.15
LOCAL_MAX_MEAN=18
CHANNEL_DELTA=32
SCHEMA='guanchuang.visual-audit.v1'

def vector(node,key):
    rows=node.occurrences(key)
    if len(rows)==1:
        try:return tuple(map(int,rows[0].atoms()))
        except (ValueError,TypeError):pass
    return ()

def all_nodes(node):
    yield node
    for child in node['children']:
        yield from all_nodes(child)

def near(a,b):
    return len(a)==len(b) and max((abs(x-y) for x,y in zip(a,b)),default=0)<=BOX_TOLERANCE

def near_box(a,b):
    if not near(a,b):return False
    return near((a[0]+a[2],a[1]+a[3]),(b[0]+b[2],b[1]+b[3]))

def error_record(errors,code,owner,expected,actual):
    errors.append(dict(code=code,owner=owner,expected=expected,actual=actual))

def inspect_generated(raw,name,scene,candidate):
    doc=parse_bytes(raw,'gui/'+name+'.gui')
    errors=[]
    counts={'elements':0,'text_lines':0,'paint_layers':0,'texture_files':0}
    roots=[n for n in doc.root.statements if n.key=='window' and n.value('name')==name]
    if len(roots)!=1 or doc.diagnostics:
        return counts,[dict(code='NAMED_NATIVE_ROOT',owner=name,expected=1,actual=len(roots))]
    def walk(expected,node,parent):
        uid=expected['native_name']
        pos,size=vector(node,'position'),vector(node,'size')
        if len(pos)!=2 or len(size)!=2:
            error_record(errors,'MISSING_LITERAL_BOX',uid,expected['box'],[pos,size]);return
        absolute=(parent[0]+pos[0],parent[1]+pos[1],*size)
        want=tuple(expected['box'][k] for k in ('x','y','w','h'))
        if not near_box(absolute,want):error_record(errors,'NATIVE_BOX',uid,want,absolute)
        counts['elements']+=1
        texts=node.occurrences('textbox')
        if len(texts)!=len(expected['texts']):error_record(errors,'TEXT_LINE_COUNT',uid,len(expected['texts']),len(texts))
        for line,t in zip(expected['texts'],texts):
            counts['text_lines']+=1
            tpos,tsize=vector(t,'position'),vector(t,'size')
            if len(tpos)!=2 or len(tsize)!=2:
                error_record(errors,'TEXT_BOX',uid,line['text'],[tpos,tsize]);continue
            if t.value('raw_text')!=line['text']:error_record(errors,'TEXT_VALUE',uid,line['text'],t.value('raw_text'))
            if not near((tpos[0]+absolute[0],tpos[1]+absolute[1]),(line['x'],line['y'])):
                error_record(errors,'TEXT_POSITION',uid,[line['x'],line['y']],list(tpos))
            if tsize[0]+BOX_TOLERANCE<line['w'] or tsize[1]+BOX_TOLERANCE<line['h']:
                error_record(errors,'TEXT_ALLOCATION',uid,[line['w'],line['h']],list(tsize))
            color=list(map(float,re.findall(r'[\d.]+',line['color'])))
            if len(color) in (3,4):
                wanted=[c/255 for c in color[:3]]+[(color[3] if len(color)==4 else 1)*line['alpha']]
                rows=t.occurrences('fontcolor')
                observed=list(map(float,rows[0].atoms())) if len(rows)==1 else []
                if len(observed)!=4 or any(abs(a-b)>1/255 for a,b in zip(observed,wanted)):
                    error_record(errors,'TEXT_COLOR',uid,wanted,observed)
            if abs(int(t.value('fontsize','0'))-line['font'])>BOX_TOLERANCE:
                error_record(errors,'TEXT_SIZE',uid,line['font'],t.value('fontsize'))
        icons=node.occurrences('icon')
        expected_texture=expected.get('texture')
        if len(icons)!=(1 if expected_texture else 0):
            error_record(errors,'PAINT_COUNT',uid,int(bool(expected_texture)),len(icons))
        if expected_texture and icons:
            counts['paint_layers']+=1
            if icons[0].value('texture')!=expected_texture or vector(icons[0],'position')!=(0,0) or vector(icons[0],'size')!=size:
                error_record(errors,'PAINT_BINDING',uid,[expected_texture,size],[icons[0].value('texture'),vector(icons[0],'size')])
        children=node.occurrences('widget')
        expected_order=[ch['native_name'] for ch in expected['children']]
        actual_order=[ch.value('name') for ch in children]
        if expected_order!=actual_order:error_record(errors,'CHILD_ORDER',uid,expected_order,actual_order)
        byname={n.value('name'):n for n in children}
        for ch in expected['children']:
            if ch['native_name'] in byname:walk(ch,byname[ch['native_name']],absolute[:2])
    walk(scene['tree'],roots[0],(0,0))
    for rel,reference in scene['paint_fingerprints'].items():
        path=(candidate/rel).resolve();counts['texture_files']+=1
        if not path.is_relative_to(candidate.resolve()) or not path.is_file():
            error_record(errors,'MISSING_TEXTURE',rel,reference,None);continue
        try:
            with Image.open(path) as im:
                image=im.convert('RGBA')
                actual=[list(image.size),hashlib.sha256(image.tobytes()).hexdigest()]
        except (ValueError,OSError):
            actual=None
        if actual!=reference:error_record(errors,'TEXTURE_PIXELS',rel,reference,actual)
    return counts,errors

READ_DOM="""root => {
 const base=root.getBoundingClientRect(),out={},byAlias={};
 for (const el of root.querySelectorAll('[data-name]')) {
  const r=el.getBoundingClientRect();
  const item={box:[r.x-base.x,r.y-base.y,r.width,r.height],kind:el.dataset.kind,text:el.childNodes[0]?.nodeType===3?el.childNodes[0].textContent:null};
  if(el.dataset.kind==='textbox' && el.firstChild?.nodeType===3) {
    const range=document.createRange();range.selectNodeContents(el);
    const rects=[...range.getClientRects()].filter(b=>b.width>0&&b.height>0);
    item.lines=new Set(rects.map(b=>Math.round(b.y))).size;
    item.horizontal_overflow=Math.max(0,...rects.map(b=>Math.max(r.left-b.left,b.right-r.right)));
    item.vertical_overflow=Math.max(0,...rects.map(b=>Math.max(r.top-b.top,b.bottom-r.bottom)));
  }
  out[el.dataset.name]=item;
  if(el.dataset.alias)byAlias[el.dataset.alias]=item;
 }
 return {byName:out,byAlias};
}"""

def render_preview(editor,output,size,backdrop=None):
    from playwright.sync_api import sync_playwright
    from editing.html_layout import browser_path
    with sync_playwright() as play:
        browser=play.chromium.launch(executable_path=browser_path(),headless=True)
        try:
            page=browser.new_page(viewport={'width':max(64,size[0]),'height':max(64,size[1])},device_scale_factor=1)
            page.goto(Path(editor).as_uri(),wait_until='load',timeout=30000)
            page.wait_for_function('document.body.dataset.ready==="1" && !!document.querySelector("#gc-scene .gc-item")')
            page.evaluate('()=>document.fonts.ready')
            page.add_style_tag(content='#gc-scene .gc-item{outline:none!important}')
            fill='url("data:image/png;base64,'+base64.b64encode(backdrop.read_bytes()).decode()+'")' if backdrop else 'none'
            page.locator('#gc-scene').evaluate("""(el,fill)=>{
             document.body.append(el);Object.assign(el.style,{position:'fixed',left:'0',top:'0',margin:'0',zIndex:'2147483647',backgroundImage:fill,backgroundSize:'100% 100%',overflow:'hidden'});
            }""",fill)
            page.evaluate('async()=>{await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)}')
            actual=page.locator('#gc-scene').evaluate(READ_DOM)
            page.screenshot(path=str(output),clip=dict(x=0,y=0,width=size[0],height=size[1]),scale='css',animations='disabled')
            return actual
        finally:browser.close()

def diff_stats(diff):
    mean=sum(ImageStat.Stat(diff).mean)/3
    channels=diff.split()
    maximum=ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2])
    hist=maximum.histogram()
    fraction=sum(hist[CHANNEL_DELTA+1:])/max(1,sum(hist))
    return {'mean_abs_rgb':round(mean,3),'changed_fraction':round(fraction,4)}

def audit_html(staged,scene,gui,game_root=None):
    from guanchuang import import_gui
    candidate=staged/'candidate'
    name=gui.stem
    counts,errors=inspect_generated((candidate/gui).read_bytes(),name,scene,candidate)
    review=list(scene['warnings'])
    report={'schema':SCHEMA,'counts':counts,'errors':errors,'review':review,'native_engine':'NOT_RUN'}
    if not errors:
        with tempfile.TemporaryDirectory(dir=staged.parent,prefix='readback-') as tmp:
            edited=Path(tmp)/'editor'
            import_gui(candidate/gui,edited,name,game_root,check_visual=False)
            with Image.open(staged/'source-window.png') as reference:
                w,h=reference.size
                actual=render_preview(edited/'editor.html',staged/'readback-window.png',(w,h),staged/'backdrop.png')['byName']
                source_root=scene['tree']['box']
                for owner in all_nodes(scene['tree']):
                    uid=owner['native_name']
                    item=actual.get(uid)
                    want=[owner['box']['x']-source_root['x'],owner['box']['y']-source_root['y'],owner['box']['w'],owner['box']['h']]
                    if not item or not near_box(item['box'],want):error_record(errors,'BROWSER_BOX',uid,want,item and item['box'])
                    for i,line in enumerate(owner['texts'],1):
                        label=actual.get(line.get('native_name',uid+'_text_'+str(i))) or {}
                        if label.get('text')!=line['text'] or label.get('lines')!=1:
                            error_record(errors,'BROWSER_TEXT_LINE',uid,line['text'],[label.get('text'),label.get('lines')])
                        # A different browser/font can slightly exceed a measured text box. Record the exact owner.
                        if label.get('horizontal_overflow',0)>1.5:
                            error_record(errors,'BROWSER_TEXT_CLIPPED',uid,0,label['horizontal_overflow'])
                with Image.open(staged/'readback-window.png') as observed:
                    delta=ImageChops.difference(reference.convert('RGB'),observed.convert('RGB'))
                metrics=diff_stats(delta);local=[]
                for owner in all_nodes(scene['tree']):
                    rect=owner['box'];x=round(rect['x']-source_root['x']);y=round(rect['y']-source_root['y'])
                    box=(max(0,x),max(0,y),min(w,x+round(rect['w'])),min(h,y+round(rect['h'])))
                    if box[2]-box[0]<4 or box[3]-box[1]<4:continue
                    stats=diff_stats(delta.crop(box))
                    if stats['mean_abs_rgb']>LOCAL_MAX_MEAN and stats['changed_fraction']>LOCAL_MAX_CHANGED:
                        local.append(dict(owner=owner['native_name'],**stats))
                report['raster']={'whole_window':metrics,'regions_to_review':local,'thresholds':{'channel':CHANNEL_DELTA,'global_fraction':GLOBAL_MAX_CHANGED,'global_mean':GLOBAL_MAX_MEAN,'local_fraction':LOCAL_MAX_CHANGED,'local_mean':LOCAL_MAX_MEAN}}
                if metrics['mean_abs_rgb']>GLOBAL_MAX_MEAN or metrics['changed_fraction']>GLOBAL_MAX_CHANGED or local:
                    review.append('整窗或局部像素差超过固定复核线，见 raster')
    report['status']='REJECTED' if errors else ('REVIEW_REQUIRED' if review else 'VERIFIED_SCOPED')
    return report

def commit_new(staged,dest):
    """Atomic new output only. A scanner can briefly hold the private staging directory on Windows."""
    import time
    for delay in (0,.12,.32,.75,1.25):
        if delay:time.sleep(delay)
        if dest.exists():raise FileExistsError('输出已存在：'+str(dest))
        try:
            staged.rename(dest)
            return
        except PermissionError as exc:
            if getattr(exc,'winerror',None) not in (5,32,33) or delay==1.25:raise

def publish_layout(staged,dest,report):
    import shutil
    file='visual-audit.json'
    (staged/file).write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    if report['status']=='REJECTED':
        folder=staged.parent/'audit-failed'
        folder.mkdir()
        for item in (file,'source-window.png','readback-window.png'):
            if (staged/item).is_file():shutil.copy2(staged/item,folder/item)
        commit_new(folder,dest)
        raise ValueError('外观校验拒绝了候选，只保留诊断：'+str(dest/file))
    return report

def bound_audit(staged):
    """Compare visible absolute nodes of an existing .gui with the real emitted editor DOM."""
    import html
    from editing.layout_tree import tree_for
    manifest=json.loads((staged/'manifest.json').read_text('utf-8'))
    profile=json.loads((staged/'source-profile.json').read_text('utf-8'))
    raw=(staged/'original.gui').read_bytes()
    root=next(n for n in parse_bytes(raw,manifest['source']).root.statements if n.value('name')==manifest['window'])
    aliases={g['owner_id']:k for k,g in manifest['targets'].items()}
    _,missing=tree_for(manifest)
    review=list(missing);errors=[];expected={};unobserved=[]
    for material,asset in profile.get('assets',{}).items():
        if not asset.get('preview_png_base64'):review.append('未解析贴图 '+material)
    def walk(node,xy,conditional=False):
        pos=vector(node,'position') or (0,0)
        size=vector(node,'size')
        if len(pos)!=2:return
        coord=(xy[0]+pos[0],xy[1]+pos[1]) if node is not root else (0,0)
        conditional=conditional or (node is not root and node.value('visible','yes') not in ('yes','true'))
        name=node.value('name',node.key)
        if node.value('parentanchor') or node.value('layoutposition'):
            review.append(name+'：原生锚点需核对')
        if node.value('text','').startswith('['):
            review.append(name+'：动态文字使用布局占位')
        alias=aliases.get(node.node_id)
        if alias and len(size)==2:expected[alias]=(name,(*coord,*size),conditional)
        for child in node.statements:
            if child.has_body and (child.node_id in aliases or child.key in ('widget','container','button','icon','textbox')):
                walk(child,coord,conditional)
    walk(root,(0,0))
    width_height=vector(root,'size')
    if len(width_height)!=2 or any(x<1 or x>8192 for x in width_height):
        review.append('窗口尺寸无法建立固定像素基准')
        observed={}
    else:
        observed=render_preview(staged/'editor.html',staged/'readback-window.png',width_height)['byAlias']
        for alias,(name,want,conditional) in expected.items():
            item=observed.get(alias)
            if not item and conditional:
                unobserved.append(name);continue
            if not item or not near_box(item['box'],want):
                error_record(errors,'BOUND_GUI_BOX',name,want,item and item['box']);continue
            if item.get('horizontal_overflow',0)>1.5 and not conditional:
                review.append(name+'：原生来源文字可能超出分配宽度')
    if unobserved:review.append('条件隐藏的控件未取样：'+str(len(unobserved)))
    painted=[v for v in expected if v in observed]
    report={'schema':SCHEMA,'kind':'GUI_TO_BROWSER','status':'REJECTED' if errors else ('REVIEW_REQUIRED' if review else 'VERIFIED_SCOPED'),
            'source_sha256':hashlib.sha256(raw).hexdigest(),'observed_explicit_boxes':len(painted),
            'conditional_unobserved':unobserved,'errors':errors,'review':list(dict.fromkeys(review)),'native_engine':'NOT_RUN'}
    note={'VERIFIED_SCOPED':'当前可见固定布局已核对','REVIEW_REQUIRED':'当前布局有需复核的项目','REJECTED':'布局检查未通过'}[report['status']]
    banner='<p class="meta">自动布局检查 · '+html.escape(note)+'。<a href="visual-audit.json">查看检查记录</a></p>'
    editor=staged/'editor.html';s=editor.read_text('utf-8');editor.write_text(s.replace('<section id="gc-layout">','<section id="gc-layout">'+banner,1),'utf-8')
    return report
