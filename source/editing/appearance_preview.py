"""Bind an existing absolute-layout page model to literal appearance transactions."""
import json
import shutil
from pathlib import Path
from editing.title import require,digest

def _json(value):return json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')

def _intersection(a,b):
    if a is None or b is None:return None
    x=max(a[0],b[0]);y=max(a[1],b[1]);right=min(a[0]+a[2],b[0]+b[2]);bottom=min(a[1]+a[3],b[1]+b[3])
    return [x,y,right-x,bottom-y] if right>x and bottom>y else None

def build_preview(bundle,manifest,profile,base_href=None):
    bundle=Path(bundle).resolve();model_path=bundle/'assets/model.js';index=bundle/'index.html';app_path=bundle/'assets/app.js'
    text=model_path.read_text(encoding='utf-8').strip()
    require(text.startswith('window.SLTM_MODEL = '),'PREVIEW_MODEL_FORMAT_UNSUPPORTED')
    model=json.loads(text.split('=',1)[1].strip().removesuffix(';'))
    baseline=profile.get('preview_baseline_manifest',manifest)
    require(model['gui']['file']==baseline['source'] and model['gui']['sha256'].lower()==baseline['base_sha256'].lower(),'PREVIEW_SOURCE_CONFLICT')
    by={n['owner']:n for n in model['nodes']};require(len(by)==len(model['nodes']),'PREVIEW_DUPLICATE_OWNER')
    allowed={'button','icon','portrait_button','scrollarea','scrollbar','scrollwidget','textbox','widget','window'}
    done=set()
    for n in model['nodes']:
        require(n['type'] in allowed,'PREVIEW_LAYOUT_TYPE_UNSUPPORTED')
        parent=by.get(n['parent']);require(not n['parent'] or parent and parent['owner'] in done,'PREVIEW_PARENT_ORDER_UNSUPPORTED')
        local=n['local'];expected=[local[0]+(parent['rect'][0] if parent else 0),local[1]+(parent['rect'][1] if parent else 0),local[2],local[3]]
        require(expected==n['rect'],'PREVIEW_RELATIVE_LAYOUT_UNSUPPORTED')
        anchor=n.get('props',{}).get('parentanchor',{}).get('value')
        require(anchor in (None,'top|left','left|top'),'PREVIEW_ANCHOR_UNSUPPORTED')
        clip=parent['clip_children'] if parent else [0,0,model['canvas']['w'],model['canvas']['h']]
        child=_intersection(clip,n['rect']) if n['scissor'] or n['type']=='scrollarea' else clip
        require(clip==n['clip'] and child==n['clip_children'],'PREVIEW_CLIP_RULE_UNSUPPORTED');done.add(n['owner'])
    for target in baseline['targets'].values():
        n=by.get(target['name']);require(n and n['line']==target['line'] and n['file']==baseline['source'],'PREVIEW_OWNER_SOURCE_CONFLICT')
        if 'fontsize' in target['fields']:require(n.get('style',{}).get('fontsize')==target['fields']['fontsize']['value'],'PREVIEW_FONT_SOURCE_CONFLICT')
    profile['preview_baseline_manifest']=baseline
    listed={}
    for f in bundle.rglob('*'):
        if f.is_file():
            require(f.resolve().is_relative_to(bundle),'PREVIEW_ASSET_ESCAPES_BUNDLE')
            listed[f.relative_to(bundle).as_posix()]=digest(f.read_bytes())
    contract={'bundle':str(bundle),'gui_sha256':baseline['base_sha256'],'model_sha256':digest(model_path.read_bytes()),
        'index_sha256':digest(index.read_bytes()),'states':list(model['states']),
        'canvas':{'w':model['canvas']['w'],'h':model['canvas']['h']},
        'files':listed,
        'capability':'SOURCE_BOUND_ABSOLUTE_LAYOUT_PROJECTION_NOT_NATIVE_RENDER'}
    folder=Path(__file__).parent
    app=app_path.read_text(encoding='utf-8')
    literal='layer.style.backgroundImage = \'url("assets/img/\' + p.png + \'")\';'
    require(app.count(literal)==1,'PREVIEW_PAINT_HOOK_MISSING')
    app=app.replace(literal,'layer.style.backgroundImage = \'url("\' + (p.data_url || "assets/img/" + p.png) + \'")\';')
    marker='ready: () => window.__I02_READY__ === true,'
    require(app.count(marker)==1,'PREVIEW_REFRESH_HOOK_MISSING')
    app=app.replace(marker,marker+'\n    refreshAppearance: () => render(),')
    scripts='\n'.join((folder/name).read_text(encoding='utf-8') for name in ('title_runtime.js','appearance_runtime.js','appearance_preview_runtime.js'))
    hook=r'''
const appearanceBaseline=JSON.parse(JSON.stringify(window.SLTM_MODEL));
const appearanceManifest=__MANIFEST__,appearanceAssets=__ASSETS__;
let appearanceVersion=0;
document.body.classList.add('native-canvas');
window.addEventListener('message',async event=>{
 if(event.source!==parent||event.data?.type!=='guanchuang-appearance-values')return;
 const version=event.data.version;if(!Number.isSafeInteger(version)||version<appearanceVersion)return;appearanceVersion=version;
 try{
  const edits={};for(const[alias,t]of Object.entries(appearanceManifest.targets)){const values=event.data.values[alias];if(!values)throw new Error('PREVIEW_VALUES_MISSING');const changed={};for(const[k,f]of Object.entries(t.fields))if(values[k]!==f.value)changed[k]=values[k];if(Object.keys(changed).length)edits[alias]=changed}
  const result=await GuanchuangAppearance.apply(appearanceManifest,GuanchuangAppearance.request(appearanceManifest,edits));
  if(version!==appearanceVersion)return;
  if(result.receipt.after_sha256!==event.data.expected_sha256)throw new Error('PREVIEW_DRAFT_SHA_CONFLICT');
  const next=GuanchuangAppearancePreview.project(appearanceBaseline,appearanceManifest,edits,appearanceAssets),current=window.SLTM_MODEL;
  next.nodes.forEach((node,i)=>{const target=current.nodes[i];for(const k of Object.keys(target))delete target[k];Object.assign(target,node)});current.states=next.states;document.documentElement.dataset.appearanceDraftSha256=result.receipt.after_sha256;
  if(event.data.state&&window.__I02__.stateId!==event.data.state)window.__I02__.setState(event.data.state);else window.__I02__.refreshAppearance();
  const resolvedTexts={};for(const[alias,target]of Object.entries(appearanceManifest.targets)){const node=[...document.querySelectorAll('#canvas [data-owner]')].find(el=>el.dataset.owner===target.name);const text=node?.querySelector(':scope > .tx')||(node?.dataset.type==='button'?node.querySelector('.tx'):null);resolvedTexts[alias]=text?text.dataset.text:null}
  parent.postMessage({type:'guanchuang-appearance-applied',sha256:result.receipt.after_sha256,version:event.data.version,state:window.__I02__.stateId,resolved_texts:resolvedTexts},'*');
 }catch(error){parent.postMessage({type:'guanchuang-appearance-error',message:error.message,version:event.data.version},'*')}
});
parent.postMessage({type:'guanchuang-appearance-ready'},'*');
'''.replace('__MANIFEST__',_json(baseline)).replace('__ASSETS__',_json(profile['assets']))
    page=index.read_text(encoding='utf-8');require(page.count('<script src="assets/app.js"></script>')==1,'PREVIEW_SCRIPT_HOOK_MISSING')
    if base_href:
        require(base_href=='preview-bundle/','PREVIEW_BASE_PATH_UNSUPPORTED')
        contract['bundle_relative']='preview-bundle'
    page=page.replace('<head>','<head>\n<base href="'+(base_href or bundle.as_uri()+'/')+'">',1)
    page=page.replace('<script src="assets/app.js"></script>','<script>'+app+'\n'+scripts+'\n'+hook+'</script>')
    profile['preview']=contract
    return page

def verify_preview(profile,package_root=None):
    if 'preview' not in profile:return None
    relative=profile['preview'].get('bundle_relative')
    if relative:
        require(relative=='preview-bundle' and package_root is not None,'PREVIEW_PACKAGE_ROOT_REQUIRED')
        root=Path(package_root).resolve();bundle=(root/relative).resolve()
        require(bundle.is_relative_to(root),'PREVIEW_BUNDLE_ESCAPES_PACKAGE')
    else:bundle=Path(profile['preview']['bundle']).resolve()
    for name,h in profile['preview']['files'].items():
        f=(bundle/name).resolve();require(f.is_relative_to(bundle) and f.is_file() and digest(f.read_bytes())==h,'PREVIEW_BUNDLE_CHANGED')
    return bundle

def copy_preview(source,dest,profile):
    source=Path(source).resolve();dest=Path(dest).resolve();target_root=dest/'preview-bundle'
    require(not target_root.exists(),'PREVIEW_COPY_TARGET_EXISTS')
    for name,h in profile['preview']['files'].items():
        original=(source/name).resolve();target=(target_root/name).resolve()
        require(original.is_relative_to(source) and target.is_relative_to(target_root),'PREVIEW_COPY_PATH_ESCAPES')
        require(original.is_file() and digest(original.read_bytes())==h,'PREVIEW_BUNDLE_CHANGED_DURING_COPY')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,target)
        require(digest(target.read_bytes())==h,'PREVIEW_COPY_HASH_MISMATCH')
