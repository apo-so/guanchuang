"""Read-only definition index and provenance-bearing GUI expansion.

Expansion is an explicit static model, not proof of engine override semantics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import hashlib

from core.contracts import digest, fingerprint
from core.syntax import parse_file

PRIMITIVES = {'window', 'widget', 'margin_widget', 'hbox', 'vbox', 'flowcontainer',
              'text_single', 'text_multi', 'textbox', 'button', 'button_normal', 'icon',
              'background', 'expand', 'scrollbox', 'scrollarea', 'fixedgridbox',
              'dynamicgridbox', 'gridbox', 'container', 'portrait_3d', 'pdxguiwidget',
              'editbox', 'checkbox', 'progressbar', 'progresspie', 'overlappingitembox', 'scrollwidget', 'dropDown'}
NONVISUAL = {'state', 'modify_texture', 'glow', 'pdx_tooltip', 'animation', 'item', 'active_item', 'list'}


@dataclass
class Expanded:
    id: str
    tag: str
    authored_tag: str
    origin: dict
    properties: list = field(default_factory=list)
    children: list = field(default_factory=list)
    contexts: list = field(default_factory=list)
    callbacks: list = field(default_factory=list)
    states: list = field(default_factory=list)
    expansion_path: list = field(default_factory=list)
    issues: list = field(default_factory=list)

    def _property(self, key):
        rows = [x for x in self.properties if x['key'] == key]
        # R13 native message-settings evidence: an instance's explicit size
        # survives a later using=Window_Size_MainTab. Keep the ordered source
        # trace intact and change only effective selection for this proven key.
        if key == 'size':
            explicit = [x for x in rows if x.get('precedence') == 'EXPLICIT_INSTANCE_SIZE']
            rows = explicit or rows
        return rows[-1] if rows else None

    def prop(self, key, default=None):
        row = self._property(key)
        return row['value'] if row is not None else default

    def prop_source(self, key):
        row = self._property(key)
        return row['source'] if row is not None else self.origin['file']

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def to_dict(self):
        return {'node_id': self.id, 'tag': self.tag, 'authored_tag': self.authored_tag,
                'origin': self.origin, 'properties': self.properties, 'contexts': self.contexts,
                'callbacks': self.callbacks, 'states': self.states, 'expansion_path': self.expansion_path,
                'issues': self.issues, 'children': [x.to_dict() for x in self.children]}


class SourceIndex:
    def __init__(self, game_root):
        self.root = Path(game_root).resolve()
        self.definitions = {}
        self.files = []
        self.diagnostics = []
        self.cache = {}
        self.used = set()
        # Keep just declaration locators for the whole corpus; parse used files
        # lazily later. Document/byte-prefix arrays are released after each file.
        for path in sorted((self.root / 'gui').rglob('*.gui')):
            rel = path.relative_to(self.root).as_posix()
            try:
                doc = parse_file(path, rel)
            except (UnicodeError, RecursionError) as exc:
                self.diagnostics.append({'file': rel, 'code': 'INDEX_PARSE_FAILED', 'detail': str(exc)})
                continue
            self.files.append({'path': rel, 'sha256': doc.sha256})
            for issue in doc.diagnostics:
                self.diagnostics.append(issue)
            for node in doc.root.walk():
                if node.kind == 'declaration' and node.key in ('type', 'template', 'local_template'):
                    self.definitions.setdefault(node.name, []).append({'file': rel, 'start': node.start,
                                                                      'kind': node.key, 'base': node.base})
        self.snapshot_id = fingerprint(self.files)

    def document(self, rel):
        if rel not in self.cache:
            doc = parse_file(self.root / rel, rel)
            expected = next((x['sha256'] for x in self.files if x['path'] == rel), None)
            if expected is not None and doc.sha256 != expected:
                raise ValueError('SOURCE_CHANGED_DURING_INDEX:' + rel)
            self.cache[rel] = doc
        self.used.add(rel)
        return self.cache[rel]

    def definition(self, name, origin, kind=None):
        rows = self.definitions.get(name, [])
        if kind:
            rows = [row for row in rows if row['kind'] in kind]
        locals_here = [row for row in rows if row['kind'] == 'local_template' and row['file'] == origin]
        rows = locals_here or [row for row in rows if row['kind'] != 'local_template']
        if len(rows) != 1:
            return None, 'AMBIGUOUS_DEFINITION' if rows else 'DEFINITION_NOT_FOUND'
        row = rows[0]
        doc = self.document(row['file'])
        found = [n for n in doc.root.walk() if n.start == row['start'] and n.kind == 'declaration']
        return (found[0], None) if len(found) == 1 else (None, 'DEFINITION_LOCATOR_INVALID')

    def root_widget(self, rel, name):
        doc = self.document(rel)
        nodes = [n for n in doc.root.statements if n.kind == 'assignment' and n.has_body and n.value('name') == name]
        if len(nodes) != 1:
            raise ValueError('ROOT_WIDGET_NOT_UNIQUE:' + name)
        return nodes[0]


class Resolver:
    def __init__(self, index, limit=20000, bindings=None):
        self.index = index
        self.limit = limit
        self.count = 0
        self.dependencies = []
        self.unresolved = []
        self.bindings = bindings

    def issue(self, output, code, detail):
        entry = {'code': code, 'detail': detail, 'node_id': output.id, 'source': output.origin['file']}
        output.issues.append(entry)
        self.unresolved.append(entry)

    def expand(self, node, instance='root', inherited_overrides=None, chain=()):
        self.count += 1
        origin = {'file': node.source, 'source_span': node.source_span, 'source_node_id': node.node_id}
        output = Expanded(instance, node.key, node.key, origin)
        if self.bindings is not None and node.value('visible') is not None:
            from core.state import evaluate
            visible = evaluate(node.value('visible'), self.bindings)
            if visible['status'] == 'KNOWN' and visible['value'] is False:
                output.properties.append({'key': 'visible', 'value': node.value('visible'), 'source': node.source,
                                           'source_span': node.source_span})
                output.expansion_path.append({'pruned': 'EXPLICIT_FIXTURE_FALSE', 'source_node_id': node.node_id})
                return output
        if self.count > self.limit or len(chain) > 72:
            self.issue(output, 'EXPANSION_LIMIT', 'Partial tree retained; no silent truncation.')
            return output

        def definition_body(definition, stack):
            marker = (definition.source, definition.name)
            if marker in stack:
                self.issue(output, 'DEFINITION_CYCLE', str(marker))
                return []
            rows = []
            if definition.key == 'type':
                if definition.base == definition.name:
                    output.tag = definition.base
                elif definition.base in self.index.definitions:
                    base, error = self.index.definition(definition.base, definition.source, {'type'})
                    if error:
                        self.issue(output, error, definition.base)
                    else:
                        rows.extend(definition_body(base, stack + (marker,)))
                elif definition.base in PRIMITIVES:
                    output.tag = definition.base
                else:
                    base, error = self.index.definition(definition.base, definition.source, {'type'})
                    if error:
                        self.issue(output, error, definition.base)
                    else:
                        rows.extend(definition_body(base, stack + (marker,)))
            rows.extend(definition.statements)
            output.expansion_path.append({'name': definition.name, 'kind': definition.key,
                                           'source': definition.source, 'source_span': definition.source_span})
            self.dependencies.append({'from': node.source, 'to': definition.source, 'symbol': definition.name})
            return rows

        rows = []
        if (node.key not in PRIMITIVES and node.key not in NONVISUAL) or node.key in self.index.definitions:
            definition, error = self.index.definition(node.key, node.source, {'type'})
            if error:
                self.issue(output, error, node.key)
            else:
                rows.extend(definition_body(definition, ()))
        rows.extend(node.statements)
        overrides = {row.name: row for row in rows if row.kind == 'blockoverride'}
        overrides.update(inherited_overrides or {})
        output._slot_overrides = overrides
        used_blocks = set()
        instance_sizes = {row.node_id for row in node.statements if row.kind == 'assignment' and row.key == 'size'}

        def process(statements, template_chain=()):
            for row in statements:
                if row.kind in ('block', 'blockoverride'):
                    if row.kind == 'block':
                        replacement = overrides.get(row.name)
                        used_blocks.add(row.name)
                        process(replacement.statements if replacement else row.statements, template_chain)
                    continue
                if row.kind != 'assignment':
                    if row.kind != 'declaration':
                        self.issue(output, 'UNMODELED_STATEMENT', row.key)
                    continue
                if row.key == 'using' and not row.has_body:
                    marker = (row.source, row.scalar)
                    if marker in template_chain:
                        self.issue(output, 'TEMPLATE_CYCLE', str(marker))
                        continue
                    definition, error = self.index.definition(row.scalar, row.source, {'template', 'local_template'})
                    if error:
                        self.issue(output, error, row.scalar)
                    else:
                        self.dependencies.append({'from': row.source, 'to': definition.source, 'symbol': row.scalar})
                        output.expansion_path.append({'name': definition.name, 'kind': definition.key,
                                                      'source': definition.source, 'source_span': definition.source_span})
                        process(definition.statements, template_chain + (marker,))
                    continue
                if row.has_body and row.key == 'state':
                    output.states.append({'name': row.value('name'), 'statements': [
                        {'key': r.key, 'scalar': r.scalar, 'has_body': r.has_body, 'source': r.source,
                         'source_span': r.source_span, 'source_node_id': r.node_id} for r in row.statements],
                                           'source': row.source, 'source_span': row.source_span})
                    if row.value('name') == '_show':
                        def resting(items, seen=()):
                            for prop in items:
                                if prop.key == 'using' and prop.scalar not in seen:
                                    definition, error = self.index.definition(prop.scalar, prop.source, {'template', 'local_template'})
                                    if not error:
                                        self.dependencies.append({'from': prop.source, 'to': definition.source, 'symbol': prop.scalar})
                                        resting(definition.statements, seen + (prop.scalar,))
                                elif prop.key in ('position', 'position_x', 'position_y'):
                                    output.properties.append({'key': prop.key, 'value': prop.atoms() if prop.has_body else prop.scalar,
                                                               'source': prop.source, 'source_span': prop.source_span,
                                                               'basis': 'MODELED_SETTLED_SHOW_STATE'})
                        resting(row.statements)
                    continue
                if row.has_body and row.key in NONVISUAL:
                    output.properties.append({'key': row.key, 'value': None,
                                               'body_reference': {'source_node_id': row.node_id, 'ordered_statement_count': len(row.statements)},
                                               'source': row.source, 'source_span': row.source_span})
                    continue
                if row.has_body and (row.key in PRIMITIVES or row.key in self.index.definitions):
                    ordinal = len(output.children)
                    child = self.expand(row, instance + '/' + row.key + ':' + str(ordinal), overrides, chain + (node.key,))
                    output.children.append(child)
                    continue
                value = row.atoms() if row.has_body else row.scalar
                prop = {'key': row.key, 'value': value, 'source': row.source, 'source_span': row.source_span}
                if row.key == 'size' and row.node_id in instance_sizes:
                    prop['precedence'] = 'EXPLICIT_INSTANCE_SIZE'
                if row.has_body and any(r.kind != 'atom' for r in row.statements):
                    prop['body_reference'] = {'source_node_id': row.node_id, 'ordered_statement_count': len(row.statements)}
                    self.issue(output, 'STRUCTURED_PROPERTY_UNMODELED', row.key)
                output.properties.append(prop)
                if row.key == 'datacontext':
                    output.contexts.append(prop)
                if row.key.startswith(('onclick', 'on_start', 'on_finish', 'on_edit')):
                    output.callbacks.append(prop)
        process(rows)
        # Unconsumed overrides can belong to nested component slots. The full
        # trace is retained; slot binding remains a composed model until tested.
        if overrides:
            output.expansion_path.append({'override_names_in_scope': sorted(overrides),
                                           'semantics': 'STATIC_COMPOSITION_NOT_RUNTIME_CALIBRATED'})
        return output
