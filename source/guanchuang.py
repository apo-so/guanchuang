"""观窗限定首版。导入、导出和重读都使用同一份源码解析器。"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
import tempfile
from pathlib import Path

from adapters.native_selection import locate, make_handoff
from core.syntax import parse_bytes
from editing.appearance import apply_appearance, apply_package, explicit_fields, prepare_appearance
from editing.title import _new_output, digest, require

VERSION = '1.1.0-preview2'


def source_info(filename):
    path = Path(filename).resolve(strict=True)
    require(path.is_file() and path.suffix.lower() == '.gui', '请选择 .gui 文件')
    root = next((part.parent for part in path.parents if part.name.lower() == 'gui'), path.parent)
    relative = path.relative_to(root).as_posix()
    raw = path.read_bytes()
    doc = parse_bytes(raw, relative)
    require(not doc.diagnostics, 'GUI_PARSE_DIAGNOSTICS: ' + str(doc.diagnostics[:1]))
    windows = [node for node in doc.root.statements if node.key == 'window' and node.value('name')]
    return root, relative, doc, windows


def local_controls(root):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(child for child in reversed(node.statements)
                     if child.has_body and child.key != 'window' and child.kind not in ('type', 'template'))


def import_gui(filename, out, window=None, game_root=None, *, check_visual=True):
    root, source, doc, windows = source_info(filename)
    choices = [node.value('name') for node in windows]
    if window is None and len(choices) == 1:
        window = choices[0]
    selected = [node for node in windows if node.value('name') == window]
    require(len(selected) == 1, '请选择一个唯一的具名窗口。可选窗口 ' + ', '.join(choices))
    selectors = {}
    for node in local_controls(selected[0]):
        fields, _ = explicit_fields(doc, node)
        if fields:
            alias = 'frame' if node is selected[0] else f'control{len(selectors)+1}'
            selectors[alias] = {'owner_id': node.node_id}
    require(selectors, '这个窗口没有可编辑的显式外观属性。')
    game = Path(game_root).resolve(strict=True) if game_root else root
    require(game.is_dir(), '游戏资源根必须为目录。')
    dest = _new_output(out, [root, game])
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.guanchuang-', dir=dest.parent) as temp:
        staged = Path(temp)/'work'
        result = prepare_appearance(root, game, source, window, selectors, staged)
        # Discovery and binding must refer to the very same bytes.
        require(result['source_sha256'] == doc.integrity['sha256'], 'SOURCE_CHANGED_DURING_IMPORT')
        from editing.visual_audit import bound_audit, commit_new, publish_layout
        if check_visual:
            audit=publish_layout(staged,dest,bound_audit(staged))
            result['visual_status']=audit['status']
        commit_new(staged,dest)
    return dict(result, editor=str(dest/'editor.html'), window=window)


def verify_export(package, request, exported_gui, out):
    package = Path(package).resolve(strict=True)
    def read(name):
        return json.loads((package/name).read_text('utf-8-sig'))
    manifest = read('manifest.json')
    profile = read('source-profile.json')
    raw = (package/'original.gui').read_bytes()
    req = json.loads(Path(request).read_text('utf-8-sig'))
    expected, _, _ = apply_appearance(raw, manifest, req)
    actual = Path(exported_gui).read_bytes()
    require(actual == expected, 'EXPORTED_GUI_MISMATCH')
    roots = [Path(p).resolve() for p in profile['read_only_roots']]
    dest = _new_output(out, roots + [package, Path(request).resolve(), Path(exported_gui).resolve()])
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.guanchuang-', dir=dest.parent) as temp:
        staged = Path(temp)/'verified'
        result = apply_package(package, req, staged)
        require(Path(result['draft']).read_bytes() == actual, 'EXPORTED_GUI_MISMATCH')
        patch = list(difflib.diff_bytes(difflib.unified_diff, raw.splitlines(True),
                              actual.splitlines(True), b'original.gui', b'draft.gui', n=2))
        (staged/'changes.diff').write_bytes(b''.join(patch))
        (staged/'baseline.gui').write_bytes(raw)
        receipt = json.loads((staged/'receipt.json').read_text('utf-8'))
        from editing.visual_audit import bound_audit, commit_new, publish_layout
        audit=publish_layout(staged,dest,bound_audit(staged))
        receipt.update(downloaded_gui_verified=True, baseline_sha256=digest(raw),visual_status=audit['status'])
        (staged/'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        commit_new(staged,dest)
    return dict(receipt, draft=str(dest/'draft'/manifest['source']), diff=str(dest/'changes.diff'),
                baseline=str(dest/'baseline.gui'), editor=str(dest/'editor.html'))


def main(argv=None):
    args_in = sys.argv[1:] if argv is None else argv
    if not args_in:
        from release_ui import launch
        launch()
        return 0
    parser = argparse.ArgumentParser(description='观窗 · CK3 GUI 外观编辑')
    parser.add_argument('--version', action='version', version=VERSION)
    subs = parser.add_subparsers(dest='command', required=True)
    inspect = subs.add_parser('list', help='列出文件中的具名窗口')
    inspect.add_argument('file')
    imp = subs.add_parser('import', help='生成编辑工作区')
    imp.add_argument('file')
    imp.add_argument('--window')
    imp.add_argument('--game-root', help='可选的 CK3 game 资源目录')
    imp.add_argument('--out', required=True)
    imp.add_argument('--selector', help='网页窗口的 CSS 选择器，默认识别 data-gc-window、#window、main 或 body')
    imp.add_argument('--click', action='append',default=[],help='取样前依次点击网页中所选的控件，可重复')
    imp.add_argument('--viewport', default='1760x990',help='网页取样视口，例如 1760x990')
    verify = subs.add_parser('verify', help='对照编辑请求校验下载的 GUI，导出最小差分')
    for name in ('package','request','gui','out'):
        verify.add_argument('--'+name, required=True)
    link = subs.add_parser('locate', help='从原生编辑器显示的文件、行号定位源码')
    for name in ('file','source-id','sha256','evidence'):
        link.add_argument('--'+name,required=True)
    link.add_argument('--line', required=True, type=int)
    link.add_argument('--column', type=int)
    link.add_argument('--name')
    link.add_argument('--out', required=True)
    args = parser.parse_args(args_in)
    try:
        if args.command == 'list':
            _, relative, doc, windows = source_info(args.file)
            result = dict(source=relative, sha256=doc.integrity['sha256'],
                          windows=[n.value('name') for n in windows])
        elif args.command == 'import':
            if Path(args.file).suffix.lower() in ('.html','.htm'):
                from editing.html_layout import convert_html
                size=tuple(map(int,args.viewport.lower().split('x')))
                result=convert_html(args.file,args.out,args.window,args.selector,args.click,size,args.game_root)
            else:
                result = import_gui(args.file, args.out, args.window, args.game_root)
        elif args.command == 'verify':
            result = verify_export(args.package, args.request, args.gui, args.out)
        else:
            root, _, _, _ = source_info(args.file)
            target = Path(args.out).resolve()
            require(target.suffix.lower()=='.json' and not target.is_relative_to(root), 'OUTPUT_MUST_BE_NEW_EXTERNAL_JSON')
            result = make_handoff(locate(args.file,args.line,args.column,args.sha256,args.source_id,args.name),args.evidence)
            with target.open('x',encoding='utf-8') as file:
                json.dump(result,file,ensure_ascii=False,indent=2)
        if sys.stdout is not None:
            print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        if sys.stderr is not None:
            print(error,file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
