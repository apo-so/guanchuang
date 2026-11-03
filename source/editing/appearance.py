"""Finite explicit appearance edits using the existing ordered parser/token patcher.

Inherited properties, expressions and insertion are deliberately not inferred.
Nothing in this module installs a Mod, runs a game or opens a browser.
"""
from __future__ import annotations
from bisect import bisect_left
import base64
import copy
import io
import json
import re
from pathlib import Path, PurePosixPath
from PIL import Image
from core.syntax import parse_bytes
from editing.title import (TitleEditError, digest, require, literal, font, patch_tokens,
                           source_path, _new_output)
from editing.button import dimension

SCHEMA='guanchuang.explicit-appearance.v1'
REQUEST='guanchuang.appearance-request.v1'

def coordinate(value):
    require(type(value) is int and abs(value)<=9007199254740991, 'COORDINATE_MUST_BE_SAFE_INTEGER')
    return str(value)

def component(value):
    require(type(value) in (int,float) and 0<=value<=1, 'COLOR_COMPONENT_RANGE_0_1')
    n=int(value*1000000+0.5)
    require(abs(value*1000000-n)<=0.000001, 'COLOR_COMPONENT_MAX_SIX_DECIMALS')
    if n in (0,1000000):return str(n//1000000)
    return ('0.'+str(n).zfill(6)).rstrip('0')

def alignment(value):
    require(isinstance(value,str) and value!='', 'ALIGNMENT_LITERAL_REQUIRED')
    flags=value.split('|')
    require(len(flags)==len(set(flags)) and all(x in {'left','right','center','top','bottom','nobaseline'} for x in flags), 'ALIGNMENT_FLAGS_UNSUPPORTED')
    require(sum(x in flags for x in ('left','right','center'))<=1 and sum(x in flags for x in ('top','bottom'))<=1, 'ALIGNMENT_FLAGS_CONFLICT')
    return value

def texture(value):
    require(isinstance(value,str) and '\\' not in value and ':' not in value and value.startswith('gfx/'), 'TEXTURE_RELATIVE_GFX_REQUIRED')
    p=PurePosixPath(value)
    require(not p.is_absolute() and '..' not in p.parts and p.suffix.lower() in {'.dds','.png','.tga'}, 'TEXTURE_PATH_UNSUPPORTED')
    return literal(value)

ENCODERS={'literal':literal,'font':font,'dimension':dimension,'coordinate':coordinate,
          'component':component,'align_word':alignment,'align_string':lambda v:literal(alignment(v)), 'texture':texture}

def _tokens(doc,row):
    start = bisect_left(doc.tokens, row.start, key=lambda token: token.start)
    end = bisect_left(doc.tokens, row.end, key=lambda token: token.start)
    return [t for t in doc.tokens[start:end] if t.end <= row.end and t.kind != 'TRIVIA']

def _field(doc,token,value,encoder):
    ENCODERS[encoder](value)
    return {'value':value,'span':[doc.byte_offsets[token.start],doc.byte_offsets[token.end]],
            'old_token':token.raw,'encoder':encoder}

def _scalar(doc,node,prop,encoder,parse):
    rows=node.occurrences(prop)
    require(len(rows)==1 and not rows[0].has_body, 'NOT_UNIQUE_SCALAR')
    tokens=_tokens(doc,rows[0]);require(len(tokens)==3 and tokens[1].raw=='=', 'NOT_SINGLE_LITERAL')
    token=tokens[2]
    if encoder in ('literal','texture'):require(token.kind=='STRING','STRING_LITERAL_REQUIRED')
    if encoder=='font':require(token.kind=='WORD' and token.raw.isascii() and token.raw.isdigit(),'INTEGER_LITERAL_REQUIRED')
    if encoder=='align':
        require(token.kind in ('WORD','STRING'),'ALIGN_LITERAL_REQUIRED')
        encoder='align_string' if token.kind=='STRING' else 'align_word'
    return _field(doc,token,parse(node.value(prop)),encoder)

def _vector(doc,node,prop,keys,encoder,parse):
    rows=node.occurrences(prop)
    require(len(rows)==1 and rows[0].has_body,'NOT_UNIQUE_VECTOR')
    tokens=_tokens(doc,rows[0]);n=len(keys)
    require(len(tokens)==n+4 and [t.raw for t in tokens[:3]]==[prop,'=','{'] and tokens[-1].raw=='}','STATIC_VECTOR_REQUIRED')
    result={}
    for key,token in zip(keys,tokens[3:-1]):
        require(token.kind=='WORD','STATIC_VECTOR_REQUIRED')
        if parse is int:require(re.fullmatch(r'[+-]?\d+',token.raw) is not None,'INTEGER_LITERAL_REQUIRED')
        result[key]=_field(doc,token,parse(token.raw),encoder)
    return result

def explicit_fields(doc, node):
    """Read the literal appearance fields used by both discovery and binding."""
    fields={};omitted={}
    for prop,encoder,parse in [('raw_text','literal',str),('fontsize','font',int),('align','align',str),('texture','texture',str)]:
        if not node.occurrences(prop):continue
        try:
            require(prop!='raw_text' or node.value('text') is None,'TEXT_AND_RAW_TEXT_AMBIGUOUS')
            fields[prop]=_scalar(doc,node,prop,encoder,parse)
        except (ValueError,TypeError) as exc:omitted[prop]=str(exc)
    for prop,keys,encoder,parse in [('position',('position_x','position_y'),'coordinate',int),('size',('width','height'),'dimension',int),('fontcolor',('color_r','color_g','color_b','color_a'),'component',float)]:
        if not node.occurrences(prop):continue
        try:fields.update(_vector(doc,node,prop,keys,encoder,parse))
        except (ValueError,TypeError) as exc:omitted[prop]=str(exc)
    return fields, omitted

def bind_appearance(raw,source,window,selectors,texture_choices=None):
    source_path(source);doc=parse_bytes(raw,source)
    require(not doc.diagnostics,'GUI_PARSE_DIAGNOSTICS')
    roots=[n for n in doc.root.walk() if n.key=='window' and n.value('name')==window]
    require(len(roots)==1,'WINDOW_NOT_UNIQUE');root=roots[0]
    require(isinstance(selectors,dict) and selectors,'SELECTORS_REQUIRED')
    require(all(isinstance(k,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*',k) for k in selectors),'TARGET_ALIAS_INVALID')
    parents={c.node_id:n for n in root.walk() for c in n.statements}
    targets={};owner_ids=set();textures=set()
    for alias,selector in selectors.items():
        require(isinstance(selector,dict) and len(selector)==1 and set(selector)<={'name','owner_id'},'SELECTOR_INVALID')
        key=next(iter(selector));value=selector[key]
        require(isinstance(value,str) and value,'SELECTOR_INVALID')
        nodes=[n for n in root.walk() if n.has_body and (n.node_id==value if key=='owner_id' else n.value('name')==value)]
        require(len(nodes)==1,'APPEARANCE_OWNER_NOT_UNIQUE:'+alias);node=nodes[0]
        ancestor=node
        while ancestor is not root and ancestor.key!='window':ancestor=parents[ancestor.node_id]
        require(ancestor is root,'OWNER_IN_DIFFERENT_NESTED_WINDOW')
        require(node.node_id not in owner_ids,'DUPLICATE_APPEARANCE_OWNER');owner_ids.add(node.node_id)
        fields,omitted=explicit_fields(doc,node)
        if 'texture' in fields:textures.add(fields['texture']['value'])
        require(fields,'NO_EXPLICIT_APPEARANCE_FIELDS:'+alias)
        targets[alias]={'owner_id':node.node_id,'name':node.value('name',''),'type':node.key,
            'line':node.source_span['start']['line'],'fields':fields,'omitted':omitted,
            'source_text_read_only':node.value('text')}
    spans=sorted(f['span'] for t in targets.values() for f in t['fields'].values())
    require(all(a[1]<=b[0] for a,b in zip(spans,spans[1:])),'OVERLAPPING_APPEARANCE_FIELDS')
    choices=sorted(textures if texture_choices is None else texture_choices)
    require(len(choices)==len(set(choices)) and textures<=set(choices),'TEXTURE_CHOICES_CONFLICT')
    for value in choices:texture(value)
    return {'schema':SCHEMA,'source':source,'window':window,'base_sha256':digest(raw),
        'source_base64':base64.b64encode(raw).decode(),'selectors':copy.deepcopy(selectors),'targets':targets,
        'texture_choices':choices,'integrity':doc.integrity,'parser_diagnostics':doc.diagnostics,
        'capability':'EXPLICIT_LITERAL_APPEARANCE_ONLY_NO_INHERITED_INSERTION','native_render':'NOT_RUN'}

def make_request(manifest,edits):
    return {'schema':REQUEST,'source':manifest['source'],'window':manifest['window'],
            'base_sha256':manifest['base_sha256'],'edits':edits}

def apply_appearance(raw,manifest,request):
    require(manifest.get('schema')==SCHEMA and request.get('schema')==REQUEST,'APPEARANCE_SCHEMA')
    require(digest(raw)==manifest['base_sha256']==request.get('base_sha256'),'SOURCE_CONFLICT')
    require(all(request.get(k)==manifest[k] for k in ('source','window')),'TARGET_CONFLICT')
    fresh=bind_appearance(raw,manifest['source'],manifest['window'],manifest['selectors'],manifest['texture_choices'])
    require(fresh==manifest,'MANIFEST_CONFLICT')
    edits=request.get('edits');require(isinstance(edits,dict) and set(edits)<=set(manifest['targets']),'UNSUPPORTED_TARGET')
    fields={};changes={};encoders={}
    for alias,target in manifest['targets'].items():
        selected=edits.get(alias,{})
        require(isinstance(selected,dict) and set(selected)<=set(target['fields']),'UNSUPPORTED_EDIT')
        for k,f in target['fields'].items():fields[alias+'.'+k]=f;encoders[alias+'.'+k]=ENCODERS[f['encoder']]
        for k,value in selected.items():
            require(k!='texture' or value in manifest['texture_choices'],'TEXTURE_NOT_IN_DECLARED_CHOICES')
            changes[alias+'.'+k]=value
    draft,patches,values=patch_tokens(raw,fields,changes,encoders)
    after=bind_appearance(draft,manifest['source'],manifest['window'],manifest['selectors'],manifest['texture_choices'])
    for alias,target in after['targets'].items():
        for key,f in target['fields'].items():require(f['value']==values[alias+'.'+key],'REIMPORT_VALUE_MISMATCH')
    for key in ('utf8_bom','crlf','lf_only','trailing_newline'):require(after['integrity'][key]==manifest['integrity'][key],'FILE_INTEGRITY_CHANGED:'+key)
    return draft,after,{'status':'APPEARANCE_SOURCE_ROUNDTRIP_VERIFIED','before_sha256':digest(raw),'after_sha256':digest(draft),
        'patches':patches,'no_edit_byte_identical':not patches and draft==raw,'untouched_bytes_verified':True,
        'full_parser_reimport':'PASS','reimport_values':values,'native_render':'NOT_RUN','deployment':False}

def prepare_appearance(mod_root,game_root,source,window,selectors,out,preview_bundle=None):
    mod=Path(mod_root).resolve();game=Path(game_root).resolve();relative=source_path(source)
    path=(mod/str(relative)).resolve();require(path.is_relative_to(mod) and path.is_file(),'SOURCE_OUTSIDE_MOD_OR_MISSING')
    protected=[mod,game]+([Path(preview_bundle).resolve()] if preview_bundle else [])
    dest=_new_output(out,protected);raw=path.read_bytes();m=bind_appearance(raw,source,window,selectors)
    assets={}
    for name in m['texture_choices']:
        found=None
        for root in (mod,game):
            candidate=(root/name).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():found=candidate;break
        info={'status':'FOUND' if found else 'MISSING','path':str(found) if found else None,'sha256':digest(found.read_bytes()) if found else None}
        if found:
            try:
                with Image.open(found) as im:
                    buf=io.BytesIO();im.convert('RGBA').save(buf,format='PNG');info['preview_png_base64']=base64.b64encode(buf.getvalue()).decode()
            except (OSError,ValueError):info['preview']='UNSUPPORTED_IMAGE_FORMAT'
        assets[name]=info
    profile={'mod_root_read_only':str(mod),'source_absolute_read_only':str(path),'source_sha256':digest(raw),
        'read_only_roots':[str(p) for p in protected],'assets':assets,'source_changed_by_tool':False}
    preview_page=None
    if preview_bundle:
        from editing.appearance_preview import build_preview
        preview_page=build_preview(preview_bundle,m,profile,base_href='preview-bundle/')
    from editing.appearance_viewer import write_viewer
    page=write_viewer(m,profile)
    require(path.read_bytes()==raw,'SOURCE_CHANGED_DURING_PREPARATION')
    dest.mkdir(parents=True);(dest/'original.gui').write_bytes(raw)
    for name,data in [('manifest.json',m),('source-profile.json',profile)]:
        (dest/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (dest/'editor.html').write_text(page,encoding='utf-8')
    if preview_page is not None:
        from editing.appearance_preview import copy_preview
        copy_preview(preview_bundle,dest,profile)
        (dest/'preview.html').write_text(preview_page,encoding='utf-8')
    return {'status':'EXPLICIT_APPEARANCE_EDITOR_GENERATED','editor':str(dest/'editor.html'),'source_sha256':digest(raw),'targets':list(m['targets']),'native_render':'NOT_RUN','deployment':False}

def apply_package(package,request,out,current_source=None):
    package=Path(package).resolve();m=json.loads((package/'manifest.json').read_text(encoding='utf-8'));profile=json.loads((package/'source-profile.json').read_text(encoding='utf-8'))
    mod=Path(profile['mod_root_read_only']).resolve();relative=source_path(m['source'])
    require((mod/str(relative)).resolve()==Path(profile['source_absolute_read_only']).resolve(),'PACKAGE_SOURCE_PATH_MISMATCH')
    live=Path(current_source or profile['source_absolute_read_only']).resolve();live_raw=live.read_bytes()
    require(digest(live_raw)==profile['source_sha256'],'LIVE_SOURCE_CONFLICT')
    raw=(package/'original.gui').read_bytes();req=json.loads(Path(request).read_text(encoding='utf-8')) if not isinstance(request,dict) else request
    draft,after,receipt=apply_appearance(raw,m,req)
    for name,asset in profile['assets'].items():
        if asset['status']=='FOUND':require(digest(Path(asset['path']).read_bytes())==asset['sha256'],'TEXTURE_ASSET_CHANGED')
    for edits in req['edits'].values():
        if 'texture' in edits:require(profile['assets'].get(edits['texture'],{}).get('status')=='FOUND','TEXTURE_ASSET_MISSING')
    dest=_new_output(out,[Path(p).resolve() for p in profile['read_only_roots']]+[package])
    preview_page=None
    if 'preview' in profile:
        from editing.appearance_preview import verify_preview,build_preview
        preview_source=verify_preview(profile,package)
        preview_page=build_preview(preview_source,after,profile,base_href='preview-bundle/')
    from editing.appearance_viewer import write_viewer
    page=write_viewer(after,profile)
    require(live.read_bytes()==live_raw,'LIVE_SOURCE_CHANGED_BEFORE_COMMIT')
    target=(dest/'draft'/str(relative)).resolve();require(target.is_relative_to(dest/'draft'),'DRAFT_PATH_ESCAPES_OUTPUT')
    dest.mkdir(parents=True);target.parent.mkdir(parents=True);target.write_bytes(draft);(dest/'original.gui').write_bytes(draft)
    for name,data in [('manifest.json',after),('source-profile.json',profile),('request.json',req),('receipt.json',receipt)]:
        (dest/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (dest/'editor.html').write_text(page,encoding='utf-8')
    if preview_page is not None:
        from editing.appearance_preview import copy_preview
        copy_preview(preview_source,dest,profile)
        (dest/'preview.html').write_text(preview_page,encoding='utf-8')
    return dict(receipt,output=str(dest),draft=str(target),editor=str(dest/'editor.html'))
