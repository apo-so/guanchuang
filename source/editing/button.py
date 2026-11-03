"""Explicit named button editing with read-only type/material provenance."""
import base64
import copy
import io
import json
from pathlib import Path

from PIL import Image

from core.resolve import Resolver
from core.syntax import parse_bytes
from editing.title import (digest, literal, patch_tokens, require, source_path,
                           _new_output, _pair, _token)


def dimension(value):
    require(type(value) is int and 0 < value <= 65536, 'SIZE_MUST_BE_POSITIVE_INTEGER_UP_TO_65536')
    return str(value)


def _owner(raw, source, window, name):
    source_path(source)
    doc = parse_bytes(raw, source)
    roots = [n for n in doc.root.statements if n.key == 'window' and n.value('name') == window]
    require(len(roots) == 1, 'WINDOW_NOT_UNIQUE')
    matches = [n for n in roots[0].walk() if n.key == 'button_standard' and n.value('name') == name]
    require(len(matches) == 1, 'BUTTON_OWNER_NOT_UNIQUE')
    return doc, roots[0], matches[0]


def bind_button(raw, source, window, name, reference=None):
    doc, root, owner = _owner(raw, source, window, name)
    require(owner.value('text') is None, 'TEXT_AND_RAW_TEXT_AMBIGUOUS')
    text = owner.value('raw_text');literal(text)
    field = dict(_token(doc, owner, 'raw_text', 'STRING'), value=text)
    rows = owner.occurrences('size')
    require(len(rows) == 1 and rows[0].has_body, 'EXPLICIT_SIZE_REQUIRED')
    row = rows[0]
    tokens = [t for t in doc.tokens if row.start <= t.start and t.end <= row.end and t.kind != 'TRIVIA']
    require(len(tokens) == 6 and [t.raw for t in tokens[:3]] == ['size', '=', '{']
            and tokens[-1].raw == '}', 'SIZE_MUST_BE_TWO_LITERAL_INTEGERS')
    fields = {'raw_text': field}
    for key, token in zip(('width', 'height'), tokens[3:5]):
        require(token.kind == 'WORD' and token.raw.isascii() and token.raw.isdigit(), 'SIZE_MUST_BE_TWO_LITERAL_INTEGERS')
        value = int(token.raw);dimension(value)
        fields[key] = {'value': value, 'span': [doc.byte_offsets[token.start], doc.byte_offsets[token.end]],
                       'old_token': token.raw, 'line': row.source_span['start']['line']}
    parents = {c.node_id: n for n in root.walk() for c in n.statements}
    parent = parents[owner.node_id]
    require(parent.key == 'hbox', 'FIRST_BUTTON_EDITOR_REQUIRES_HBOX_OWNER')
    siblings = [n for n in parent.statements if n.has_body and n.key == 'button_standard']
    require(len(siblings) > 0, 'BUTTON_ROW_MISSING')
    row_info = []
    for n in siblings:
        w, h = _pair(n, 'size')
        row_info.append({'name': n.value('name', ''), 'label': n.value('raw_text', n.value('text', '')),
                         'width': w, 'height': h, 'target': n.node_id == owner.node_id})
    protected = [{'key': n.key, 'value': n.scalar, 'body': doc.text[n.start:n.end] if n.has_body else None}
                 for n in owner.statements if n.key not in ('raw_text', 'size')]
    return {'schema': 'guanchuang.literal-button.v1', 'source': source, 'window': window,
            'button_name': name, 'owner_id': owner.node_id, 'owner_line': owner.source_span['start']['line'],
            'base_sha256': doc.sha256, 'source_base64': base64.b64encode(raw).decode(), 'fields': fields,
            'integrity': doc.integrity, 'parser_diagnostics': doc.diagnostics, 'protected_statements': protected,
            'preview': {'row': row_info, 'spacing': float(parent.value('spacing', '0')),
                        'row_width': _pair(parent, 'size')[0], 'mode': 'BASE_TEXTURE_WITHOUT_NATIVE_OVERLAY_SHADER',
                        'dimensions_affect_following_siblings': True},
            'reference': copy.deepcopy(reference) if reference else None}


def build_reference(index, source, window, name):
    doc = index.document('mod/' + source)
    roots = [n for n in doc.root.statements if n.value('name') == window]
    require(len(roots) == 1, 'WINDOW_NOT_UNIQUE')
    owners = [n for n in roots[0].walk() if n.key == 'button_standard' and n.value('name') == name]
    require(len(owners) == 1, 'BUTTON_OWNER_NOT_UNIQUE')
    resolver = Resolver(index)
    expanded = resolver.expand(owners[0])
    keys = ['texture','framesize','spriteType','spriteborder','texture_density','gfxtype','effectname',
            'upframe','uphoverframe','uppressedframe','downframe','downhoverframe','downpressedframe','disableframe']
    props = {k: {'value': expanded.prop(k), 'source': expanded.prop_source(k)} for k in keys}
    texture = props['texture']['value']
    require(isinstance(texture,str)and not texture.startswith('['),'BUTTON_STYLE_UNRESOLVED')
    asset, mount = index.asset(texture)
    require(asset is not None, 'BUTTON_TEXTURE_MISSING')
    try:
        fw, fh = map(int, props['framesize']['value'])
    except (ValueError, TypeError) as exc:
        raise ValueError('FRAME_SIZE_NOT_STATIC') from exc
    with Image.open(asset) as im:
        image = im.convert('RGBA')
    require(fw > 0 and fh > 0 and image.width % fw == 0 and image.height % fh == 0,
            'TEXTURE_FRAME_GRID_MISMATCH')
    columns = image.width // fw;frames = columns * (image.height // fh)
    state_keys = {'normal':'upframe','hover':'uphoverframe','pressed':'uppressedframe',
                  'selected':'downframe','disabled':'disableframe'}
    images = {}
    for state, key in state_keys.items():
        frame = int(props[key]['value']);require(0 < frame <= frames, 'FRAME_INDEX_OUT_OF_RANGE')
        x = (frame - 1) % columns * fw;y = (frame - 1) // columns * fh
        buf = io.BytesIO();image.crop((x,y,x+fw,y+fh)).save(buf,format='PNG')
        images[state] = {'frame':frame,'png_base64':base64.b64encode(buf.getvalue()).decode()}
    # Shader/child overlays are traced but not yet composited by this base-texture preview.
    textures = {texture}
    for n in expanded.walk():
        value = n.prop('texture')
        if isinstance(value,str) and not value.startswith('['):textures.add(value)
    for edge in resolver.dependencies:
        d, error = index.definition(edge['symbol'], edge['from'])
        if not error:
            for n in d.walk():
                if n.key == 'texture' and isinstance(n.scalar,str) and not n.scalar.startswith('['):textures.add(n.scalar)
    assets=[]
    for relative in sorted(textures):
        p, role=index.asset(relative)
        assets.append({'virtual_path':relative,'mount':role,'path':str(p) if p else None,
                       'sha256':digest(p.read_bytes()) if p else None,'status':'FOUND' if p else 'MISSING'})
    shader, shader_role=index.asset('gfx/FX/pdxgui_pushbutton.shader')
    if shader:assets.append({'virtual_path':'gfx/FX/pdxgui_pushbutton.shader','mount':shader_role,
                            'path':str(shader),'sha256':digest(shader.read_bytes()),'status':'FOUND'})
    definitions=[{'path':str(index.paths[p]),'qualified':p,'sha256':index.document(p).sha256}for p in sorted(index.used)]
    return {'status':'STATIC_BUTTON_PROVENANCE_NOT_NATIVE_RENDER_ACCEPTANCE',
            'scope':'ONE_EXPLICIT_MOD_OVER_VANILLA_SAME_PATH; cross-file duplicates stay ambiguous',
            'properties':props,'type_template_dependencies':resolver.dependencies,
            'definitions':definitions,'index_files':index.files,'index_roots':{k:str(v)for k,v in index.roots.items()},
            'shadowed_files':index.shadowed,'resolver_issues':resolver.unresolved,
            'assets':assets,'base_texture':{'virtual_path':texture,'mount':mount,'sha256':digest(asset.read_bytes()),
            'size':list(image.size),'frame_size':[fw,fh],'frame_count':frames,'states':images,
                'grid_interpretation':'ROW_MAJOR_CANDIDATE_NOT_NATIVE_OBSERVED'},
            'render_limit':'Base DDS frames and candidate edge/center tiling only; native overlays, shader, font, enabled/down expressions not evaluated'}


def verify_reference(reference):
    if reference is None:return
    roots={k:Path(v)for k,v in reference['index_roots'].items()}
    selected={}
    for mount,root in roots.items():
        for p in sorted((root/'gui').rglob('*.gui')):
            virtual=p.relative_to(root).as_posix();selected[virtual]=(mount+'/'+virtual,p)
    current=[{'path':qualified,'virtual_path':rel,'sha256':digest(p.read_bytes())}
             for rel,(qualified,p)in sorted(selected.items())]
    require(current==reference['index_files'],'GUI_DEPENDENCY_CONFLICT')
    for a in reference['assets']:
        if a['path']:
            require(digest(Path(a['path']).read_bytes())==a['sha256'],'ASSET_DEPENDENCY_CONFLICT')


def apply_button_edits(raw,manifest,request):
    require(request.get('schema')=='guanchuang.button-edit-request.v1','REQUEST_SCHEMA')
    require(digest(raw)==manifest['base_sha256']==request.get('base_sha256'),'SOURCE_CONFLICT')
    require(all(request.get(k)==manifest[k]for k in ('source','window','owner_id')),'TARGET_CONFLICT')
    fresh=bind_button(raw,manifest['source'],manifest['window'],manifest['button_name'],manifest['reference'])
    require(fresh==manifest,'MANIFEST_CONFLICT')
    verify_reference(manifest['reference'])
    draft,patches,values=patch_tokens(raw,manifest['fields'],request.get('changes'),
                                     {'raw_text':literal,'width':dimension,'height':dimension})
    after=bind_button(draft,manifest['source'],manifest['window'],manifest['button_name'],manifest['reference'])
    require(all(after['fields'][k]['value']==v for k,v in values.items()),'REIMPORT_VALUE_MISMATCH')
    require(after['protected_statements']==manifest['protected_statements'],'BUTTON_LOGIC_CHANGED')
    for k in ('utf8_bom','crlf','lf_only','trailing_newline'):
        require(after['integrity'][k]==manifest['integrity'][k],'FILE_INTEGRITY_CHANGED:'+k)
    require(after['parser_diagnostics']==manifest['parser_diagnostics'],'PARSER_DIAGNOSTICS_CHANGED')
    return draft,after,{'status':'BUTTON_SOURCE_ROUNDTRIP_VERIFIED','before_sha256':digest(raw),'after_sha256':digest(draft),
        'patches':patches,'reimport_values':values,'no_edit_byte_identical':not patches and draft==raw,
        'untouched_bytes_verified':True,'protected_button_logic_preserved':True,
        'layout_effect':'Changed width moves following hbox siblings in preview; source preservation is not visual locality',
        'native_render':'NOT_RUN','deployment':False}


def prepare_button_editor(mod_root,game_root,source,window,name,out):
    from adapters.mod_index import ModSourceIndex
    from editing.button_viewer import write_viewer
    mod=Path(mod_root).resolve();game=Path(game_root).resolve();path=(mod/source).resolve()
    require(path.is_relative_to(mod)and path.is_file(),'SOURCE_OUTSIDE_MOD_OR_MISSING')
    source=path.relative_to(mod).as_posix();source_path(source)
    dest=_new_output(out,[mod,game,game.parent/'clausewitz'])
    index=ModSourceIndex(game,mod);reference=build_reference(index,source,window,name)
    raw=path.read_bytes();manifest=bind_button(raw,source,window,name,reference)
    profile={'mod_root_read_only':str(mod),'source_absolute_read_only':str(path),'source_sha256':digest(raw),
             'read_only_roots':[str(mod),str(game),str(game.parent/'clausewitz')],
             'dependencies':'PARTIAL_BUTTON_STATIC_TYPE_AND_TEXTURE_ONLY','runtime_load':'NOT_CLAIMED'}
    page=write_viewer(manifest);dest.mkdir(parents=True)
    (dest/'original.gui').write_bytes(raw)
    for filename,value in [('manifest.json',manifest),('source-profile.json',profile)]:
        (dest/filename).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    (dest/'editor.html').write_text(page,encoding='utf-8')
    return {'status':'ACTUAL_BUTTON_EDITOR_GENERATED','editor':str(dest/'editor.html'),'button':name,
            'fields':{k:v['value']for k,v in manifest['fields'].items()},'definitions':len(reference['definitions']),
            'assets':len(reference['assets']),'native_render':'NOT_RUN','deployment':False}
