"""Ordered, source-preserving CK3 GUI reader. No source serializer or mutation."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
import hashlib
import re
from pathlib import Path


@dataclass
class Token:
    kind: str
    raw: str
    start: int
    end: int

    @property
    def value(self):
        if self.kind == 'STRING':
            return re.sub(r'\\(["\\])', r'\1', self.raw[1:-1])
        return self.raw


@dataclass
class Statement:
    kind: str
    key: str
    name: str = ''
    base: str = ''
    operator: str = ''
    scalar: str | None = None
    statements: list = field(default_factory=list)
    start: int = 0
    end: int = 0
    source: str = ''
    node_id: str = ''
    owner_id: str | None = None
    source_span: dict = field(default_factory=dict)
    has_body: bool = False

    def occurrences(self, key):
        return [node for node in self.statements if node.kind == 'assignment' and node.key == key]

    def value(self, key, default=None):
        found = self.occurrences(key)
        return found[-1].scalar if found and not found[-1].has_body else default

    def atoms(self):
        return [node.scalar for node in self.statements if node.kind == 'atom']

    def walk(self):
        yield self
        for child in self.statements:
            yield from child.walk()

    def to_dict(self):
        return {'kind': self.kind, 'key': self.key, 'name': self.name, 'base': self.base,
                'operator': self.operator, 'scalar': self.scalar, 'has_body': self.has_body,
                'node_id': self.node_id, 'owner_id': self.owner_id, 'source': self.source,
                'source_span': self.source_span, 'expansion_path': [],
                'ordered_statements': [node.to_dict() for node in self.statements]}


class Document:
    def __init__(self, data, source):
        self.raw_bytes = data
        self.text = data.decode('utf-8')
        self.source = source
        self.sha256 = hashlib.sha256(data).hexdigest()
        self.lines = [0] + [i + 1 for i, ch in enumerate(self.text) if ch == '\n']
        self.byte_offsets = [0]
        for ch in self.text:
            self.byte_offsets.append(self.byte_offsets[-1] + len(ch.encode('utf-8')))
        self.tokens = []
        self.diagnostics = []
        self.root = Statement('document', '__root__', source=source, end=len(self.text), has_body=True)

    def span(self, start, end):
        def point(offset):
            line = bisect_right(self.lines, offset) - 1
            return {'char': offset, 'byte': self.byte_offsets[offset], 'line': line + 1,
                    'column': offset - self.lines[line] + 1}
        return {'start': point(start), 'end': point(end), 'offset_convention': 'BOM_COUNTS_AS_CHARACTER; END_EXCLUSIVE'}

    def issue(self, code, start, end, message):
        self.diagnostics.append({'code': code, 'severity': 'error', 'source': self.source,
                                 'source_span': self.span(start, end), 'message': message})

    @property
    def integrity(self):
        raw = self.raw_bytes
        return {'sha256': self.sha256, 'bytes': len(raw), 'utf8_bom': raw.startswith(b'\xef\xbb\xbf'),
                'crlf': raw.count(b'\r\n'), 'lf_only': raw.count(b'\n') - raw.count(b'\r\n'),
                'trailing_newline': raw.endswith((b'\n', b'\r')), 'roundtrip': 'ORIGINAL_BYTES_RETAINED_NOT_RESERIALIZED'}

    def to_dict(self):
        return {'source': self.source, 'integrity': self.integrity, 'root': self.root.to_dict(),
                'diagnostics': self.diagnostics}


def lex(doc):
    text = doc.text
    i = 0
    while i < len(text):
        begin = i
        ch = text[i]
        if ch.isspace() or ch == '\ufeff':
            i += 1
            while i < len(text) and (text[i].isspace() or text[i] == '\ufeff'):
                i += 1
            kind = 'TRIVIA'
        elif ch == '#':
            i = text.find('\n', i)
            if i < 0:
                i = len(text)
            kind = 'TRIVIA'
        elif ch == '"':
            i += 1
            while i < len(text):
                if text[i] == '\\':
                    i = min(i + 2, len(text))
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            else:
                doc.issue('UNTERMINATED_STRING', begin, i, 'Quoted string is not closed.')
            kind = 'STRING'
        elif ch in '{}':
            i += 1
            kind = ch
        elif ch in '=<>!?':
            i += 1
            if i < len(text) and text[i] == '=':
                i += 1
            kind = 'OP'
        else:
            i += 1
            while i < len(text) and not text[i].isspace() and text[i] not in '{}"#=<>!?':
                i += 1
            kind = 'WORD'
        doc.tokens.append(Token(kind, text[begin:i], begin, i))
    return [token for token in doc.tokens if token.kind != 'TRIVIA']


def parse_bytes(data, source='<memory>'):
    doc = Document(data, source)
    tokens = lex(doc)
    cursor = 0

    def consume_body(owner):
        nonlocal cursor
        owner.has_body = True
        while cursor < len(tokens):
            if tokens[cursor].kind == '}':
                owner.end = tokens[cursor].end
                cursor += 1
                return
            owner.statements.append(statement())
        owner.end = len(doc.text)
        doc.issue('UNCLOSED_BODY', owner.start, owner.end, 'Missing closing brace.')

    def statement():
        nonlocal cursor
        first = tokens[cursor]
        cursor += 1
        key = first.value
        node = Statement('atom', key, scalar=key, start=first.start, end=first.end, source=source)
        if first.kind in ('}', '{', 'OP'):
            node.kind = 'unknown'
            doc.issue('UNEXPECTED_TOKEN', first.start, first.end, first.raw)
            if first.kind == '{':
                consume_body(node)
            return node
        # Name-first declarations; names and type bases remain separate facts.
        if key in ('type', 'types', 'Types', 'template', 'local_template', 'layer') and cursor < len(tokens):
            following = tokens[cursor]
            if following.kind in ('WORD', 'STRING'):
                node.kind, node.name, node.scalar = 'declaration', following.value, None
                cursor += 1
                if key == 'type':
                    if cursor + 1 < len(tokens) and tokens[cursor].raw == '=':
                        node.operator = '='
                        node.base = tokens[cursor + 1].value
                        cursor += 2
                    else:
                        doc.issue('TYPE_BASE_MISSING', first.start, following.end, 'Expected type Name = Base { ... }.')
                if cursor < len(tokens) and tokens[cursor].kind == '{':
                    cursor += 1
                    consume_body(node)
                else:
                    doc.issue('DECLARATION_BODY_MISSING', first.start, following.end, key)
                return node
        block_cursor = cursor
        block_operator = ''
        if key in ('block', 'blockoverride') and block_cursor < len(tokens) and tokens[block_cursor].raw == '=':
            block_operator = '='
            block_cursor += 1
        if key in ('block', 'blockoverride') and block_cursor < len(tokens) and tokens[block_cursor].kind in ('STRING', 'WORD'):
            cursor = block_cursor
            node.kind, node.name, node.scalar = key, tokens[cursor].value, None
            node.operator = block_operator
            cursor += 1
            if cursor < len(tokens) and tokens[cursor].kind == '{':
                cursor += 1
                consume_body(node)
            else:
                doc.issue('BLOCK_BODY_MISSING', node.start, node.end, key)
            return node
        if cursor < len(tokens) and tokens[cursor].kind == 'OP':
            node.kind, node.operator, node.scalar = 'assignment', tokens[cursor].raw, None
            cursor += 1
            if node.operator != '=':
                doc.issue('UNSUPPORTED_OPERATOR', node.start, tokens[cursor - 1].end, node.operator)
            if cursor >= len(tokens) or tokens[cursor].kind == '}':
                doc.issue('ASSIGNMENT_VALUE_MISSING', node.start, node.end, key)
            elif tokens[cursor].kind == '{':
                cursor += 1
                consume_body(node)
            else:
                node.scalar = tokens[cursor].value
                node.end = tokens[cursor].end
                cursor += 1
        return node

    while cursor < len(tokens):
        node = statement()
        doc.root.statements.append(node)
        if node.kind == 'atom':
            doc.issue('UNKNOWN_ROOT_ATOM', node.start, node.end, node.key)

    def assign_ids(owner, parent=None):
        owner.owner_id = parent.node_id if parent else None
        owner.source_span = doc.span(owner.start, owner.end)
        counts = {}
        for child in owner.statements:
            explicit = child.value('name', '') if child.has_body else ''
            signature = ':'.join((child.kind, child.key, child.name, child.base, explicit or ''))
            ordinal = counts.get(signature, 0)
            counts[signature] = ordinal + 1
            role = hashlib.sha256(signature.encode('utf-8')).hexdigest()[:12]
            child.node_id = owner.node_id + '/' + role + ':' + str(ordinal)
            assign_ids(child, owner)
    doc.root.node_id = 'source:' + source
    assign_ids(doc.root)
    return doc


def parse_file(path, source=None):
    path = Path(path)
    return parse_bytes(path.read_bytes(), source or path.as_posix())
