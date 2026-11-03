"""One immutable GUI baseline, multiple explicit owners, one byte patch transaction."""
import base64
import json
from pathlib import Path

from editing.title import (bind_title, digest, literal, font, patch_tokens, require,
                           _new_output, source_path)
from editing.button import bind_button, build_reference, dimension, verify_reference

SCHEMA = 'guanchuang.gui-workspace.v1'
REQUEST = 'guanchuang.workspace-edit-request.v1'


def bind_workspace(raw, source, window, title=None, button=None, reference=None, title_owner=None, list_preview=None, detail_preview=None, allocation_preview=None, resources=None, map_sidebar=None, journey=None, main_preview=None, visual_stage=None):
    title_manifest = bind_title(raw, source, window, title, title_owner)
    button_manifest = bind_button(raw, source, window, button, reference)
    targets = {'title': title_manifest, 'button': button_manifest}
    # Do not allow two editable properties to claim the same original bytes.
    spans = sorted(f['span'] for m in targets.values() for f in m['fields'].values())
    require(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), 'WORKSPACE_OVERLAPPING_TARGETS')
    result = {'schema': SCHEMA, 'source': source, 'window': window,
            'base_sha256': digest(raw), 'source_base64': base64.b64encode(raw).decode(),
            'targets': targets, 'target_order': ['title', 'button'],
            'scope': 'TWO_EXPLICIT_OWNERS_NOT_FULL_WINDOW_RENDER'}
    if list_preview is not None:
        from preview.office_list import bind_office_list, validate_snapshot
        contract = bind_office_list(raw, source, window, list_preview['contract']['name'])
        for snapshot in list_preview['scenarios'].values():
            validate_snapshot(contract, snapshot)
        result['list_preview'] = dict(list_preview, contract=contract)
    if detail_preview is not None:
        from preview.detail import bind_detail, validate_profile
        contract=bind_detail(raw,source,window,detail_preview['templates'])
        for title_id,profile in detail_preview['profiles'].items():validate_profile(profile,title_id)
        result['detail_preview']=dict(detail_preview,contract=contract)
    if allocation_preview is not None:
        require(allocation_preview.get('schema')=='guanchuang.allocation-preview.v1','ALLOCATION_PREVIEW_SCHEMA')
        result['allocation_preview']=allocation_preview
    if resources is not None:result['resources']=resources
    if map_sidebar is not None:result['map_sidebar']=map_sidebar
    if journey is not None:result['journey']=journey
    if main_preview is not None:
        from preview.main_window import rebind_preview
        if resources and resources.get('native_components'):main_preview=dict(main_preview,component_contract=resources['native_components']['contract'])
        result['main_preview']=rebind_preview(raw,main_preview,result['list_preview'],result['detail_preview'])
        if resources and resources.get('text_metrics'):
            from preview.text_metrics import build_text_metrics
            result['resources']=dict(resources,text_metrics=build_text_metrics(resources['skin'],result['main_preview']))
    if visual_stage is not None:
        from preview.workspace_stage import rebind_stage
        result['visual_stage']=rebind_stage(visual_stage,result['main_preview'],result['allocation_preview'],result['map_sidebar'],result['resources'])
    return result


def rebind(raw, manifest):
    return bind_workspace(raw, manifest['source'], manifest['window'],
                          button=manifest['targets']['button']['button_name'],
                          reference=manifest['targets']['button']['reference'],
                          title_owner=manifest['targets']['title']['owner_id'], list_preview=manifest.get('list_preview'),
                          detail_preview=manifest.get('detail_preview'),allocation_preview=manifest.get('allocation_preview'),resources=manifest.get('resources'),map_sidebar=manifest.get('map_sidebar'),journey=manifest.get('journey'),main_preview=manifest.get('main_preview'),visual_stage=manifest.get('visual_stage'))


def make_request(manifest, edits):
    return {'schema': REQUEST, 'base_sha256': manifest['base_sha256'],
            'source': manifest['source'], 'window': manifest['window'], 'edits': edits}


def apply_workspace(raw, manifest, request):
    require(manifest.get('schema') == SCHEMA, 'WORKSPACE_SCHEMA')
    require(request.get('schema') == REQUEST, 'REQUEST_SCHEMA')
    require(digest(raw) == manifest['base_sha256'] == request.get('base_sha256'), 'SOURCE_CONFLICT')
    require(all(request.get(k) == manifest[k] for k in ('source', 'window')), 'TARGET_CONFLICT')
    require(rebind(raw, manifest) == manifest, 'MANIFEST_CONFLICT')
    edits = request.get('edits')
    require(isinstance(edits, dict) and set(edits) <= set(manifest['targets']), 'UNSUPPORTED_TARGET')
    fields, changes, encoders = {}, {}, {}
    for target, m in manifest['targets'].items():
        selected = edits.get(target, {})
        require(isinstance(selected, dict) and set(selected) <= set(m['fields']), 'UNSUPPORTED_EDIT')
        for field, value in m['fields'].items():
            key = target + '.' + field
            fields[key] = value
            encoders[key] = literal if field == 'raw_text' else font if field == 'fontsize' else dimension
        changes.update({target + '.' + k: v for k, v in selected.items()})
    verify_reference(manifest['targets']['button']['reference'])
    if 'list_preview' in manifest:
        from preview.office_list import verify_list_reference
        verify_list_reference(manifest['list_preview']['reference'])
    if 'detail_preview'in manifest:
        from preview.detail import verify_detail_reference
        verify_detail_reference(manifest['detail_preview']['reference'],manifest['detail_preview']['templates'])
    if 'allocation_preview'in manifest:
        from preview.allocation_scene import verify_preview
        verify_preview(manifest['allocation_preview'])
    if 'resources'in manifest:
        from adapters.localization import verify_localization
        verify_localization(manifest['resources']['localization'])
        if 'skin'in manifest['resources']:
            from preview.skin import verify_skin
            verify_skin(manifest['resources']['skin'],manifest['targets']['button']['reference'])
        if 'native_localization'in manifest['resources']:
            from adapters.native_localization import verify_native_localization
            verify_native_localization(manifest['resources']['native_localization'])
        if 'native_components'in manifest['resources']:
            from preview.components import verify_components
            verify_components(manifest['resources']['native_components'])
        if 'text_metrics'in manifest['resources']:
            from preview.text_metrics import verify_text_metrics
            verify_text_metrics(manifest['resources']['text_metrics'],manifest['resources']['skin'])
    if 'map_sidebar'in manifest:
        from preview.map_sidebar import verify_preview as verify_map
        verify_map(manifest['map_sidebar'])
    if 'journey'in manifest:
        from preview.journey import verify_journey
        verify_journey(manifest['journey'],manifest['allocation_preview'],manifest['map_sidebar'])
    if 'main_preview'in manifest:
        from preview.main_window import verify_preview as verify_main
        verify_main(raw,manifest['main_preview'],manifest['list_preview'],manifest['detail_preview'])
    if 'visual_stage'in manifest:
        from preview.workspace_stage import verify_stage
        verify_stage(manifest['visual_stage'],manifest['main_preview'],manifest['allocation_preview'],manifest['map_sidebar'],manifest['resources'])
    draft, patches, values = patch_tokens(raw, fields, changes, encoders)
    after = rebind(draft, manifest)
    for target, m in after['targets'].items():
        require(all(f['value'] == values[target + '.' + k] for k, f in m['fields'].items()),
                'REIMPORT_VALUE_MISMATCH')
        before = manifest['targets'][target]
        for k in ('utf8_bom', 'crlf', 'lf_only', 'trailing_newline'):
            require(m['integrity'][k] == before['integrity'][k], 'FILE_INTEGRITY_CHANGED:' + k)
        require(m['parser_diagnostics'] == before['parser_diagnostics'], 'PARSER_DIAGNOSTICS_CHANGED')
    require(after['targets']['button']['protected_statements'] ==
            manifest['targets']['button']['protected_statements'], 'BUTTON_LOGIC_CHANGED')
    if 'list_preview' in manifest:
        require(after['list_preview']['contract']['subtree_sha256'] == manifest['list_preview']['contract']['subtree_sha256'],
                'OFFICE_LIST_SOURCE_CHANGED')
    if 'detail_preview'in manifest:
        require(after['detail_preview']['contract']['subtree_hashes']==manifest['detail_preview']['contract']['subtree_hashes'],
                'DETAIL_SOURCE_CHANGED')
    return draft, after, {'status': 'WORKSPACE_SOURCE_ROUNDTRIP_VERIFIED',
            'before_sha256': digest(raw), 'after_sha256': digest(draft), 'patches': patches,
            'reimport_values': values, 'no_edit_byte_identical': not patches and draft == raw,
            'untouched_bytes_verified': True, 'protected_button_logic_preserved': True,
            'full_parser_reimport': 'PASS', 'native_render': 'NOT_RUN', 'deployment': False}


def prepare_workspace(mod_root, game_root, source, window, title, button, out):
    from adapters.mod_index import ModSourceIndex
    from editing.workspace_viewer import write_viewer
    source_path(source)
    mod, game = Path(mod_root).resolve(), Path(game_root).resolve()
    path = (mod / source).resolve()
    require(path.is_relative_to(mod) and path.is_file(), 'SOURCE_OUTSIDE_MOD_OR_MISSING')
    dest = _new_output(out, [mod, game, game.parent / 'clausewitz'])
    raw = path.read_bytes()
    index = ModSourceIndex(game, mod)
    reference = build_reference(index, source, window, button)
    manifest = bind_workspace(raw, source, window, title, button, reference)
    # Preserve old two-owner packages. Attach the actual named list only when it exists.
    from core.syntax import parse_bytes
    if any(n.key == 'scrollbox' and n.value('name') == 'cmm40_office_list' for n in parse_bytes(raw, source).root.walk()):
        from preview.office_list import bind_office_list, scenarios, build_list_reference, verify_list_reference
        contract = bind_office_list(raw, source, window)
        preview = {'contract': contract, 'scenarios': scenarios(contract),
                   'reference': build_list_reference(index, source, window, contract['name'])}
        verify_list_reference(preview['reference'])
        manifest = rebind(raw, dict(manifest, list_preview=preview))
        if any(n.value('name')=='cmm40_detail_pane'for n in parse_bytes(raw,source).root.walk()):
            from preview.detail import build_detail,verify_detail_reference
            detail=build_detail(index,raw,source,window,preview)
            verify_detail_reference(detail['reference'],detail['templates'])
            manifest=rebind(raw,dict(manifest,detail_preview=detail))
    if (mod/'gui/cmm26_allocation.gui').is_file():
        from preview.allocation_scene import build_preview,verify_preview
        allocation=build_preview(mod)
        verify_preview(allocation)
        manifest=rebind(raw,dict(manifest,allocation_preview=allocation))
    from adapters.localization import build_localization
    manifest=rebind(raw,dict(manifest,resources={'schema':'guanchuang.resources.v1','localization':build_localization(mod)}))
    if (mod/'gui/cmm23_situation_window.gui').is_file():
        from preview.map_sidebar import build_preview as build_map,verify_preview as verify_map
        sidebar=build_map(index,mod);verify_map(sidebar)
        manifest=rebind(raw,dict(manifest,map_sidebar=sidebar))
        if 'allocation_preview'in manifest:
            from preview.journey import build_journey,verify_journey
            journey=build_journey(manifest['allocation_preview'],sidebar,mod)
            verify_journey(journey,manifest['allocation_preview'],sidebar)
            manifest=rebind(raw,dict(manifest,journey=journey))
    if (game/'fonts/fonts.font').is_file():
        from preview.skin import build_skin
        manifest=rebind(raw,dict(manifest,resources=dict(manifest['resources'],skin=build_skin(game,mod,reference))))
    if 'detail_preview'in manifest:
        from preview.main_window import build_preview as build_main
        main=build_main(index,raw,source,window,manifest['list_preview'],manifest['detail_preview'])
        manifest=rebind(raw,dict(manifest,main_preview=main))
        from adapters.native_localization import requested_keys,build_native_localization
        native_labels=build_native_localization(game,mod,requested_keys(main['roots'],manifest['resources']['localization']))
        manifest=rebind(raw,dict(manifest,resources=dict(manifest['resources'],native_localization=native_labels)))
        capture=Path(__file__).resolve().parents[3]/'runs/R20-GAME-KEYS-COMPARE-20261024/evidence/N1-council/native.png'
        if capture.is_file():
            from preview.components import build_components
            components=build_components(index,main,capture)
            manifest=rebind(raw,dict(manifest,resources=dict(manifest['resources'],native_components=components)))
        if 'skin'in manifest['resources']:
            from preview.text_metrics import build_text_metrics
            metrics=build_text_metrics(manifest['resources']['skin'],manifest['main_preview'])
            manifest=rebind(raw,dict(manifest,resources=dict(manifest['resources'],text_metrics=metrics)))
        if 'allocation_preview'in manifest and 'map_sidebar'in manifest:
            from preview.workspace_stage import build_stage
            stage=build_stage(manifest['main_preview'],manifest['allocation_preview'],manifest['map_sidebar'],manifest['resources'],mod)
            manifest=rebind(raw,dict(manifest,visual_stage=stage))
    verify_reference(reference)
    require(path.read_bytes() == raw, 'SOURCE_CHANGED_DURING_PREPARATION')
    profile = {'mod_root_read_only': str(mod), 'source_absolute_read_only': str(path),
               'source_sha256': digest(raw),
               'read_only_roots': [str(mod), str(game), str(game.parent / 'clausewitz')],
               'dependencies': 'PARTIAL_TITLE_AND_BUTTON_STATIC_REFERENCE', 'runtime_load': 'NOT_CLAIMED'}
    page = write_viewer(manifest)
    dest.mkdir(parents=True)
    (dest / 'original.gui').write_bytes(raw)
    for name, value in [('manifest.json', manifest), ('source-profile.json', profile)]:
        (dest / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    (dest / 'editor.html').write_text(page, encoding='utf-8')
    return {'status': 'UNIFIED_GUI_WORKSPACE_GENERATED', 'editor': str(dest / 'editor.html'),
            'source_sha256': digest(raw), 'editable_targets': list(manifest['targets']),
            'native_render': 'NOT_RUN', 'deployment': False}
