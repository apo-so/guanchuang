"""Native observations select source owners, never runtime instances or GUI writes.

Ported from the independent locator and named-widget adapter. The main parser is
the sole parser; source identities and hashes always come from the caller.
"""
import hashlib
import re
from pathlib import Path
from core.syntax import parse_bytes

CONTRACT = 'guanchuang-native-source-selection-v1'
HANDOFF = 'guanchuang-native-handoff-v2'
INDEX = 'guanchuang.native-source-index.v1'


def require(condition, code):
    if not condition:
        raise ValueError(code)


def _parse(raw, source_id, expected_sha256):
    require(isinstance(source_id, str) and source_id.strip(), 'SOURCE_ID_REQUIRED')
    require(isinstance(expected_sha256, str) and re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha256), 'SOURCE_HASH_REQUIRED')
    digest = hashlib.sha256(raw).hexdigest()
    require(digest == expected_sha256.lower(), 'SOURCE_CHANGED')
    doc = parse_bytes(raw, source_id)
    require(not doc.diagnostics, 'PARSE_DIAGNOSTICS')
    return doc, digest


def _describe(doc, node):
    by_id = {n.node_id: n for n in doc.root.walk()}
    chain = []
    current = node
    while current is not None:
        chain.append(current)
        current = by_id.get(current.owner_id)
    return {'node_id': node.node_id, 'key': node.key,
            'name': node.name or node.value('name'), 'source_span': node.source_span,
            'template_scope': any(n.key in ('type', 'template') for n in chain),
            'ancestry': [n.node_id for n in reversed(chain)]}


def locate_bytes(raw, line, column=None, expected_sha256=None, source_id=None, name=None):
    doc, digest = _parse(raw, source_id, expected_sha256)
    lines = doc.text.splitlines(keepends=True)
    require(type(line) is int and 1 <= line <= len(lines), 'LINE_OUT_OF_RANGE')
    start = sum(map(len, lines[:line - 1]))
    end = start + len(lines[line - 1].rstrip('\r\n'))
    if column is not None:
        require(type(column) is int and 1 <= column and start + column - 1 < end, 'COLUMN_OUT_OF_RANGE')
    blocks = [n for n in doc.root.walk() if n is not doc.root and n.has_body]
    derived = None
    if name is not None:
        require(isinstance(name, str) and name, 'OBSERVED_NAME_REQUIRED')
        hits = [n for n in blocks if (n.name or n.value('name')) == name
                and n.source_span['start']['line'] == line]
        require(len(hits) == 1, 'NAMED_DECLARATION_NOT_UNIQUE_AT_OBSERVED_LINE')
        if column is not None:
            require(hits[0].start <= start + column - 1 < hits[0].end, 'OBSERVED_COLUMN_NAME_CONFLICT')
        leaves = hits
        derived = hits[0].source_span['start']['column']
    else:
        if column is None:
            hits = [n for n in blocks if n.start < end and n.end > start]
        else:
            hits = [n for n in blocks if n.start <= start + column - 1 < n.end]
        leaves = [n for n in hits if not any(m is not n and n.start <= m.start and m.end <= n.end for m in hits)]
    status = 'UNIQUE_SOURCE_BLOCK' if len(leaves) == 1 else ('AMBIGUOUS_SOURCE_BLOCKS' if leaves else 'NO_BLOCK')
    return {'contract': CONTRACT, 'status': status, 'source_id': source_id,
            'source_sha256': digest, 'source_integrity': doc.integrity,
            'selection': {'line': line, 'column': column, 'name': name},
            'column_derived_from_source': derived, 'column_observed_natively': False,
            'candidates': [_describe(doc, n) for n in leaves],
            'evidence_level': 'SOURCE_LOCATION_ONLY', 'runtime_instance_id': None,
            'computed_geometry': None}


def locate(path, line, column=None, expected_sha256=None, source_id=None, name=None):
    path = Path(path)
    raw = path.read_bytes()
    result = locate_bytes(raw, line, column, expected_sha256, source_id, name)
    require(path.read_bytes() == raw, 'SOURCE_CHANGED_DURING_SELECTION')
    return dict(result, source=str(path.resolve()))


def make_handoff(selection, evidence, observed_properties=None):
    require(selection.get('status') == 'UNIQUE_SOURCE_BLOCK', 'SELECTION_NOT_UNIQUE')
    require(isinstance(evidence, str) and evidence.strip(), 'OBSERVATION_EVIDENCE_REQUIRED')
    require(observed_properties is None or isinstance(observed_properties, dict), 'OBSERVED_PROPERTIES_INVALID')
    return {'contract': HANDOFF, 'source_id': selection['source_id'], 'locator': selection,
            'observation_origin': 'OPERATOR_RECORDED_NOT_AUTOMATICALLY_VERIFIED',
            'observation_evidence': evidence, 'observed_properties': observed_properties or {},
            'geometry': 'UNKNOWN'}


def source_index(raw, source_id):
    doc, digest = _parse(raw, source_id, hashlib.sha256(raw).hexdigest())
    nodes = {}
    # Build ancestry once for the index rather than reparsing each owner.
    by_id = {n.node_id: n for n in doc.root.walk()}
    for node in by_id.values():
        if node is doc.root or not node.has_body:
            continue
        ancestors = []; parent = node
        while parent is not None:
            ancestors.append(parent); parent = by_id.get(parent.owner_id)
        span = node.source_span
        nodes[node.node_id] = {'start': span['start']['byte'], 'end': span['end']['byte'],
                              'line': span['start']['line'], 'end_line': span['end']['line'],
                              'key': node.key, 'name': node.name or node.value('name'), 'source_span': span,
                              'template_scope': any(n.key in ('type', 'template') for n in ancestors)}
    return {'schema': INDEX, 'source_id': source_id, 'sha256': digest, 'nodes': nodes}


def validate_handoff(handoff, raw, source_id):
    require(handoff.get('contract') in (HANDOFF, 'guanchuang-native-handoff-v1'), 'HANDOFF_SCHEMA')
    require(handoff.get('source_id') == source_id, 'SOURCE_ID_CONFLICT')
    loc = handoff.get('locator', {})
    require(loc.get('status') == 'UNIQUE_SOURCE_BLOCK' and len(loc.get('candidates', [])) == 1, 'SELECTION_NOT_UNIQUE')
    selection = loc.get('selection', {})
    fresh = locate_bytes(raw, selection.get('line'), selection.get('column'), loc.get('source_sha256'), source_id,
                         selection.get('name') if handoff['contract'] == HANDOFF else None)
    require(fresh['status'] == 'UNIQUE_SOURCE_BLOCK', 'SELECTION_NOT_UNIQUE')
    a, b = fresh['candidates'][0], loc['candidates'][0]
    require(a['node_id'] == b.get('node_id'), 'NODE_ID_CONFLICT')
    require(a['source_span'] == b.get('source_span'), 'SOURCE_SPAN_CONFLICT')
    return a


def match_target(manifest, handoff, raw):
    require(manifest.get('schema') in ('guanchuang.explicit-appearance.v1', 'guanchuang.gui-workspace.v1'), 'WORKSPACE_SCHEMA')
    require(hashlib.sha256(raw).hexdigest() == manifest.get('base_sha256'), 'SOURCE_CONFLICT')
    node = validate_handoff(handoff, raw, manifest['source'])
    require(not node['template_scope'], 'SHARED_TEMPLATE_READ_ONLY')
    matches = [alias for alias, target in manifest['targets'].items() if target['owner_id'] == node['node_id']]
    require(len(matches) == 1, 'NODE_NOT_EDITABLE')
    return matches[0]
