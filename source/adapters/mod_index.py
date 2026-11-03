"""One explicitly selected Mod over a read-only vanilla GUI tree.

Same virtual path selects the Mod file. Cross-file duplicate symbols remain
ambiguous; this is not proof of a live playset's complete engine load order.
"""
from pathlib import Path

from core.contracts import fingerprint
from core.resolve import SourceIndex
from core.syntax import parse_file


class ModSourceIndex(SourceIndex):
    def __init__(self, game_root, mod_root):
        self.root = Path(game_root).resolve()
        self.roots = {'vanilla': self.root, 'mod': Path(mod_root).resolve()}
        self.asset_roots = dict(self.roots, clausewitz=self.root.parent / 'clausewitz')
        self.definitions, self.files, self.diagnostics, self.cache = {}, [], [], {}
        self.used = set()
        self.paths = {}
        self.shadowed = []
        virtual = {}
        for mount, root in self.roots.items():
            for path in sorted((root / 'gui').rglob('*.gui')):
                relative = path.relative_to(root).as_posix()
                qualified = mount + '/' + relative
                if relative in virtual:
                    self.shadowed.append({'virtual_path': relative, 'selected': qualified,
                                          'shadowed': virtual[relative][0]})
                virtual[relative] = (qualified, path)
        for relative, (qualified, path) in sorted(virtual.items()):
            self.paths[qualified] = path
            try:
                doc = parse_file(path, qualified)
            except (UnicodeError, RecursionError) as exc:
                self.diagnostics.append({'file': qualified, 'code': 'INDEX_PARSE_FAILED', 'detail': str(exc)})
                continue
            self.files.append({'path': qualified, 'virtual_path': relative, 'sha256': doc.sha256})
            self.diagnostics.extend(doc.diagnostics)
            for node in doc.root.walk():
                if node.kind == 'declaration' and node.key in ('type', 'template', 'local_template'):
                    self.definitions.setdefault(node.name, []).append(
                        {'file': qualified, 'start': node.start, 'kind': node.key, 'base': node.base})
        self.snapshot_id = fingerprint(self.files)

    def document(self, qualified):
        if qualified not in self.paths:
            raise ValueError('SOURCE_NOT_IN_MOUNT:' + qualified)
        if qualified not in self.cache:
            doc = parse_file(self.paths[qualified], qualified)
            expected = next((x['sha256'] for x in self.files if x['path'] == qualified), None)
            if expected is None or doc.sha256 != expected:
                raise ValueError('SOURCE_CHANGED_DURING_INDEX:' + qualified)
            self.cache[qualified] = doc
        self.used.add(qualified)
        return self.cache[qualified]

    def asset(self, relative):
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts or ':' in relative or '\\' in relative:
            raise ValueError('ASSET_PATH_NOT_RELATIVE')
        for mount in ('mod', 'vanilla', 'clausewitz'):
            root = self.asset_roots[mount]
            candidate = (root / path).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                return candidate, mount
        return None, None
