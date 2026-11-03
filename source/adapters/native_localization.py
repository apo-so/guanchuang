"""Only requested current native Chinese UI keys; explicit Mod same-path overlay."""
import re
from pathlib import Path
from adapters.localization import parse_localization
from editing.title import require,digest

def requested_keys(roots,mod_localization):
    keys=set();entries=mod_localization['entries'];queue=[]
    def visit(n):
        text=n['props'].get('text')
        if isinstance(text,str)and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',text):queue.append(text)
        for c in n['children']+n['item']:visit(c)
    for root in roots:visit(root)
    seen=set()
    while queue:
        key=queue.pop()
        if key in seen:continue
        seen.add(key)
        if key not in entries:keys.add(key);continue
        text=entries[key];queue.extend(re.findall(r'\$([^$]+)\$',text))
        keys.update('game_concept_'+c for c in re.findall(r'\[([A-Za-z_][A-Za-z0-9_]*)\|E\]',text))
    return sorted(keys)

def build_native_localization(game_root,mod_root,requested,language='l_simp_chinese'):
    game,mod=Path(game_root).resolve(),Path(mod_root).resolve();folder='simp_chinese'if language=='l_simp_chinese'else language.removeprefix('l_');base=game/'localization'/folder
    selected={p.relative_to(game).as_posix():p for p in sorted(base.rglob('*.yml'))}
    for virtual in list(selected):
        if(mod/virtual).is_file():selected[virtual]=mod/virtual
    wanted=set(requested);definitions={};sources={};issues=[]
    # Macro/Concept references discovered in selected values are looked up on the next pass.
    for attempt in range(8):
        added=set();definitions={};sources={};issues=[]
        for virtual,path in selected.items():
            raw=path.read_bytes()
            try:parsed=parse_localization(raw,virtual,language)
            except UnicodeDecodeError:issues.append({'source':virtual,'code':'NATIVE_LOC_NOT_UTF8'});continue
            found=[entry for entry in parsed['entries']if entry['key']in wanted]
            if not found:continue
            sources[virtual]={'path':str(path),'source':virtual,'sha256':digest(raw),'mount':'mod'if path.is_relative_to(mod)else'vanilla'}
            for entry in found:
                definitions.setdefault(entry['key'],[]).append(entry);added.update(re.findall(r'\$([^$]+)\$',entry['value']));added.update('game_concept_'+c for c in re.findall(r'\[([A-Za-z_][A-Za-z0-9_]*)\|E\]',entry['value']))
        if added<=wanted:break
        wanted|=added
    else:issues.append({'code':'NATIVE_LOC_REFERENCE_DEPTH_LIMIT'})
    entries={};ambiguous={}
    for key,records in definitions.items():
        values={r['value']for r in records}
        if len(values)==1:entries[key]=records[0]['value']
        else:ambiguous[key]=records
    return {'schema':'guanchuang.native-localization-subset.v1','game_root_read_only':str(game),'mod_root_read_only':str(mod),'requested':sorted(set(requested)),
       'language':language,'inventory':sorted(selected),'sources':list(sources.values()),'entries':entries,'definitions':definitions,'ambiguous':ambiguous,
       'missing':sorted(wanted-set(definitions)),'issues':issues,'scope':'Requested used native-language keys only; one explicit Mod same virtual file shadows vanilla. Different duplicate values stay ambiguous; not a live playset load-order claim.'}

def verify_native_localization(reference):
    fresh=build_native_localization(reference['game_root_read_only'],reference['mod_root_read_only'],reference['requested'],reference['language'])
    require(fresh==reference,'NATIVE_LOCALIZATION_SOURCE_OR_REPRESENTATION_CONFLICT')

def combined_entries(resources):
    mod=resources.get('localization',{});native=resources.get('native_localization',{});result=dict(native.get('entries',{}));result.update(mod.get('entries',{}))
    for key in mod.get('ambiguous',{}):result.pop(key,None)
    return result
