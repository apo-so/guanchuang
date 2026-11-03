"""Source-backed literal title editing. Originals are never serialized or overwritten."""
from __future__ import annotations

import base64
import difflib
import hashlib
import json
import math
from pathlib import Path, PurePosixPath

from core.syntax import parse_bytes


class TitleEditError(ValueError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, code):
    if not condition:
        raise TitleEditError(code)


def literal(value):
    require(isinstance(value, str), 'TITLE_MUST_BE_STRING')
    require(not any(c in value for c in '\r\n\t[]$#'), 'TITLE_LITERAL_SUBSET_ONLY')
    require(not any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value), 'INVALID_TITLE_CODEPOINT')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def font(value):
    require(type(value) is int and 0 < value <= 4096, 'FONT_MUST_BE_POSITIVE_INTEGER_UP_TO_4096')
    return str(value)


def source_path(source):
    require(isinstance(source, str) and '\\' not in source and ':' not in source,
            'SOURCE_PATH_MUST_BE_RELATIVE_GUI')
    path = PurePosixPath(source)
    require(not path.is_absolute() and '..' not in path.parts and path.suffix.lower() == '.gui',
            'SOURCE_PATH_MUST_BE_RELATIVE_GUI')
    return path


def _token(doc, owner, key, kind):
    rows = owner.occurrences(key)
    require(len(rows) == 1 and not rows[0].has_body, 'PROPERTY_NOT_UNIQUE_LITERAL:' + key)
    row = rows[0]
    tokens = [t for t in doc.tokens if row.start <= t.start and t.end <= row.end
              and t.kind != 'TRIVIA']
    require(len(tokens) == 3 and tokens[1].raw == '=' and tokens[2].kind == kind,
            'PROPERTY_NOT_EXPLICIT_LITERAL:' + key)
    token = tokens[2]
    return {'span': [doc.byte_offsets[token.start], doc.byte_offsets[token.end]],
            'old_token': token.raw, 'line': row.source_span['start']['line']}


def _pair(node, key):
    rows = node.occurrences(key)
    require(len(rows) == 1 and rows[0].has_body, 'STATIC_PAIR_REQUIRED:' + key)
    atoms = rows[0].atoms()
    require(len(atoms) == 2, 'STATIC_PAIR_REQUIRED:' + key)
    try:
        values = [float(x) for x in atoms]
    except ValueError as exc:
        raise TitleEditError('STATIC_PAIR_REQUIRED:' + key) from exc
    require(all(math.isfinite(x) for x in values), 'NONFINITE_PAIR:' + key)
    return values


def bind_title(raw, source, window, title=None, owner_id=None):
    source_path(source)
    doc = parse_bytes(raw, source)
    roots = [n for n in doc.root.statements if n.key == 'window' and n.value('name') == window]
    require(len(roots) == 1, 'WINDOW_NOT_UNIQUE')
    root = roots[0]
    # First editor deliberately supports a direct explicit title, not inherited slots.
    owners = [n for n in root.statements if n.key == 'text_single' and n.has_body
              and (n.node_id == owner_id if owner_id else n.value('raw_text') == title)]
    require(len(owners) == 1, 'TITLE_OWNER_NOT_UNIQUE')
    node = owners[0]
    require(node.value('text') is None, 'TEXT_AND_RAW_TEXT_AMBIGUOUS')
    raw_text = node.value('raw_text')
    literal(raw_text)
    try:
        size = int(node.value('fontsize'))
    except (ValueError, TypeError) as exc:
        raise TitleEditError('EXPLICIT_FONT_REQUIRED') from exc
    font(size)
    fields = {'raw_text': dict(_token(doc, node, 'raw_text', 'STRING'), value=raw_text),
              'fontsize': dict(_token(doc, node, 'fontsize', 'WORD'), value=size)}
    w, h = _pair(root, 'size')
    require(w > 0 and h > 0, 'ROOT_SIZE_NOT_POSITIVE')
    title_rect = _pair(node, 'position') + _pair(node, 'size')
    require(min(title_rect[2:]) > 0, 'TITLE_SIZE_NOT_POSITIVE')
    return {'schema': 'guanchuang.literal-title.v1', 'source': source, 'window': window,
            'base_sha256': digest(raw), 'source_base64': base64.b64encode(raw).decode('ascii'),
            'owner_id': node.node_id, 'owner_line': node.source_span['start']['line'],
            'fields': fields, 'integrity': doc.integrity,
            'preview': {'root_size': [w, h], 'root_anchor': root.value('parentanchor', 'top|left'),
                        'title_rect_local': title_rect, 'mode': 'TITLE_SCHEMATIC_NOT_NATIVE_RENDER',
                        'rest_of_GUI': 'PRESERVED_IN_SOURCE_NOT_RENDERED'},
            'parser_diagnostics': doc.diagnostics}


def make_request(manifest, changes):
    return {'schema': 'guanchuang.title-edit-request.v1',
            'base_sha256': manifest['base_sha256'], 'source': manifest['source'],
            'window': manifest['window'], 'owner_id': manifest['owner_id'], 'changes': changes}


def patch_tokens(raw, fields, changes, encoders):
    require(isinstance(changes, dict) and set(changes) <= set(encoders), 'UNSUPPORTED_EDIT')
    patches = []
    values = {k: v['value'] for k, v in fields.items()}
    for key, value in changes.items():
        token = encoders[key](value)
        field = fields[key]
        values[key] = value
        a, b = field['span']
        require(raw[a:b] == field['old_token'].encode('utf-8'), 'OLD_TOKEN_CONFLICT')
        if value != field['value']:
            patches.append({'field': key, 'span': [a, b], 'old_token': field['old_token'], 'new_token': token})
    patches.sort(key=lambda p: p['span'][0])
    require(all(a['span'][1] <= b['span'][0] for a, b in zip(patches, patches[1:])), 'OVERLAPPING_EDITS')
    cursor, pieces = 0, []
    for patch in patches:
        a, b = patch['span']
        pieces += [raw[cursor:a], patch['new_token'].encode('utf-8')]
        cursor = b
    pieces.append(raw[cursor:])
    draft = b''.join(pieces)
    old_cursor = new_cursor = 0
    for patch in patches:
        a, b = patch['span']
        section = raw[old_cursor:a]
        require(draft[new_cursor:new_cursor + len(section)] == section, 'UNTOUCHED_BYTES_CHANGED')
        new_cursor += len(section) + len(patch['new_token'].encode('utf-8'))
        old_cursor = b
    require(draft[new_cursor:] == raw[old_cursor:], 'UNTOUCHED_SUFFIX_CHANGED')
    return draft, patches, values


def apply_edits(raw, manifest, request):
    require(request.get('schema') == 'guanchuang.title-edit-request.v1', 'REQUEST_SCHEMA')
    require(digest(raw) == manifest['base_sha256'] == request.get('base_sha256'), 'SOURCE_CONFLICT')
    require(all(request.get(k) == manifest[k] for k in ('source', 'window', 'owner_id')), 'TARGET_CONFLICT')
    fresh = bind_title(raw, manifest['source'], manifest['window'], owner_id=manifest['owner_id'])
    require(fresh == manifest, 'MANIFEST_CONFLICT')
    draft, patches, values = patch_tokens(raw, manifest['fields'], request.get('changes'),
                                         {'raw_text': literal, 'fontsize': font})
    after = bind_title(draft, manifest['source'], manifest['window'], owner_id=manifest['owner_id'])
    require(all(after['fields'][k]['value'] == v for k, v in values.items()), 'REIMPORT_VALUE_MISMATCH')
    for key in ('utf8_bom', 'crlf', 'lf_only', 'trailing_newline'):
        require(after['integrity'][key] == manifest['integrity'][key], 'FILE_INTEGRITY_CHANGED:' + key)
    require(after['parser_diagnostics'] == manifest['parser_diagnostics'], 'PARSER_DIAGNOSTICS_CHANGED')
    receipt = {'status': 'SOURCE_ROUNDTRIP_VERIFIED', 'before_sha256': digest(raw),
               'after_sha256': digest(draft), 'patches': patches, 'no_edit_byte_identical': not patches and draft == raw,
               'untouched_bytes_verified': True, 'file_integrity_preserved': True,
               'reimport_values': values, 'native_render': 'NOT_RUN', 'deployment': False}
    return draft, after, receipt


def _new_output(path, protected):
    out = Path(path).resolve()
    require(not any(out.is_relative_to(p) or p.is_relative_to(out) for p in protected),
            'OUTPUT_OVERLAPS_READ_ONLY_ROOT')
    require(not out.exists(), 'OUTPUT_MUST_BE_NEW')
    return out


def prepare_editor(mod_root, source, window, title, out, game_root=None):
    mod = Path(mod_root).resolve()
    path = (mod / source).resolve()
    require(path.is_relative_to(mod) and path.is_file(), 'SOURCE_OUTSIDE_MOD_OR_MISSING')
    require(path.suffix.lower() == '.gui', 'SOURCE_NOT_GUI')
    protected = [mod] + ([Path(game_root).resolve()] if game_root else [])
    dest = _new_output(out, protected)
    raw = path.read_bytes()
    manifest = bind_title(raw, path.relative_to(mod).as_posix(), window, title)
    manifest_path = dest / 'manifest.json'
    # Hash the actual installed GUI set; source use is not a full rendering dependency closure.
    files = sorted((mod / 'gui').rglob('*.gui'))
    inputs = [{'path': p.relative_to(mod).as_posix(), 'sha256': digest(p.read_bytes())} for p in files]
    registrations = []
    for p in sorted((mod / 'gui/scripted_widgets').glob('*')):
        if p.is_file() and window in p.read_text(encoding='utf-8-sig'):
            registrations.append({'path': p.relative_to(mod).as_posix(), 'sha256': digest(p.read_bytes())})
    profile = {'mod_root_read_only': str(mod), 'source_absolute_read_only': str(path),
               'read_only_roots': [str(p) for p in protected],
               'gui_source_hashes': inputs, 'registration_references': registrations,
               'dependencies': 'PARTIAL_TITLE_EXPLICIT_PROPERTIES_ONLY', 'load_order': 'NOT_RESOLVED',
               'runtime_load': 'NOT_CLAIMED', 'source_sha256': digest(raw)}
    from editing.viewer import write_viewer
    page = write_viewer(manifest)
    dest.mkdir(parents=True)
    (dest / 'original.gui').write_bytes(raw)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (dest / 'source-profile.json').write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8')
    (dest / 'editor.html').write_text(page, encoding='utf-8')
    return {'status': 'SOURCE_TITLE_EDITOR_GENERATED', 'source_sha256': digest(raw),
            'editor': str(dest / 'editor.html'), 'manifest': str(manifest_path),
            'title': manifest['fields']['raw_text']['value'], 'native_render': 'NOT_RUN'}


def apply_package(package, request, out, current_source=None):
    package = Path(package).resolve()
    manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))
    profile = json.loads((package / 'source-profile.json').read_text(encoding='utf-8'))
    relative = source_path(manifest['source'])
    mod_root = Path(profile['mod_root_read_only']).resolve()
    require((mod_root / str(relative)).resolve() == Path(profile['source_absolute_read_only']).resolve(),
            'PACKAGE_SOURCE_PATH_MISMATCH')
    raw = (package / 'original.gui').read_bytes()
    live_path = Path(current_source or profile['source_absolute_read_only']).resolve()
    current = live_path.read_bytes()
    require(digest(current) == profile['source_sha256'], 'LIVE_SOURCE_CONFLICT')
    req = json.loads(Path(request).read_text(encoding='utf-8')) if not isinstance(request, dict) else request
    dest = _new_output(out, [Path(p).resolve() for p in profile['read_only_roots']] + [mod_root, package])
    if manifest.get('schema') == 'guanchuang.gui-workspace.v1':
        from editing.workspace import apply_workspace
        from editing.workspace_viewer import write_viewer
        draft, after, receipt = apply_workspace(raw, manifest, req)
    elif manifest.get('schema') == 'guanchuang.literal-button.v1':
        from editing.button import apply_button_edits
        from editing.button_viewer import write_viewer
        draft, after, receipt = apply_button_edits(raw, manifest, req)
    else:
        draft, after, receipt = apply_edits(raw, manifest, req)
        from editing.viewer import write_viewer
    page = write_viewer(after)
    delta = ''.join(difflib.unified_diff(raw.decode('utf-8').splitlines(True),
                                       draft.decode('utf-8').splitlines(True),
                                       fromfile=manifest['source'], tofile='draft/' + manifest['source']))
    require(live_path.read_bytes() == current, 'LIVE_SOURCE_CHANGED_BEFORE_COMMIT')
    target = (dest / 'draft' / str(relative)).resolve()
    require(target.is_relative_to(dest / 'draft'), 'DRAFT_PATH_ESCAPES_OUTPUT')
    dest.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    target.write_bytes(draft)
    (dest / 'original.gui').write_bytes(draft)
    (dest / 'manifest.json').write_text(json.dumps(after, ensure_ascii=False, indent=2), encoding='utf-8')
    (dest / 'source-profile.json').write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8')
    (dest / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    (dest / 'changes.diff').write_text(delta, encoding='utf-8')
    (dest / 'editor.html').write_text(page, encoding='utf-8')
    return dict(receipt, draft=str(target), editor=str(dest / 'editor.html'))
