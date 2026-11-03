"""Read-only single-language Mod localization, without guessing cross-file precedence."""
import re
from pathlib import Path
from editing.title import digest,require

LINE=re.compile(r'^\s*([^\s:#]+):(?:\d+)?\s*"((?:\\.|[^"\\])*)"\s*(?:#.*)?$')


def parse_localization(raw,source,language='l_simp_chinese'):
    text=raw.decode('utf-8-sig');header=next((x.strip()for x in text.splitlines()if x.strip()and not x.lstrip().startswith('#')),'')
    if header!=language+':':return {'status':'OTHER_LANGUAGE','entries':[],'issues':[]}
    result=[];issues=[]
    for number,line in enumerate(text.splitlines(),1):
        if not line.strip()or line.lstrip().startswith('#')or line.strip()==header:continue
        match=LINE.fullmatch(line)
        if not match:issues.append({'source':source,'line':number,'code':'LOCALIZATION_LINE_UNPARSED'});continue
        key,value=match.groups()
        value=re.sub(r'\\(["\\n])',lambda m:'\n'if m[1]=='n'else m[1],value)
        result.append({'key':key,'value':value,'source':source,'line':number})
    return {'status':'PARSED_SINGLE_LANGUAGE','entries':result,'issues':issues}


def build_localization(mod_root,language='l_simp_chinese'):
    mod=Path(mod_root).resolve();root=mod/'localization';sources=[];definitions={};issues=[]
    paths=sorted(p for p in root.rglob('*')if p.is_file()and p.suffix.lower()in('.yml','.yaml'))if root.exists()else[]
    for path in paths:
        raw=path.read_bytes();source=path.relative_to(mod).as_posix()
        try:parsed=parse_localization(raw,source,language)
        except UnicodeDecodeError:
            issues.append({'source':source,'code':'LOCALIZATION_NOT_UTF8'});continue
        if parsed['status']=='OTHER_LANGUAGE':continue
        sources.append({'path':str(path),'source':source,'sha256':digest(raw)});issues.extend(parsed['issues'])
        for entry in parsed['entries']:definitions.setdefault(entry['key'],[]).append(entry)
    entries={};ambiguous={}
    for key,records in definitions.items():
        values={r['value']for r in records}
        if len(values)==1:entries[key]=records[0]['value']
        else:ambiguous[key]=records
    return {'schema':'guanchuang.mod-localization.v1','language':language,'mod_root_read_only':str(mod),
       'inventory':[p.relative_to(mod).as_posix()for p in paths],'sources':sources,'entries':entries,'definitions':definitions,'ambiguous':ambiguous,'issues':issues,
       'scope':'One Mod language only; equal duplicates safe, different values ambiguous; vanilla localization not loaded'}


def verify_localization(reference):
    fresh=build_localization(reference['mod_root_read_only'],reference['language'])
    require(fresh==reference,'LOCALIZATION_SOURCE_OR_REPRESENTATION_CONFLICT')


def resolve_key(key,entries,chain=()):
    if key in chain:return {'status':'UNKNOWN','text':'〔本地化循环：'+key+'〕'}
    if key not in entries:return {'status':'UNKNOWN','text':'〔本地化未知：'+key+'〕'}
    unknown=False
    def replace(match):
        nonlocal unknown
        result=resolve_key(match[1],entries,chain+(key,));unknown|=result['status']!='KNOWN';return result['text']
    text=re.sub(r'\$([^$]+)\$',replace,entries[key])
    return {'status':'UNKNOWN'if unknown else'KNOWN','text':text}
