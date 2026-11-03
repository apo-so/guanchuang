/* Finite appearance transactions; reuse the existing byte patcher. No browser I/O. */
(function(root){'use strict';
 const G=root.GuanchuangTitle,need=(ok,code)=>{if(!ok)throw new Error(code)};
 function coordinate(v){need(Number.isSafeInteger(v),'COORDINATE_MUST_BE_SAFE_INTEGER');return String(v)}
 function component(v){need(typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=1,'COLOR_COMPONENT_RANGE_0_1');const n=Math.round(v*1e6);need(Math.abs(v*1e6-n)<=1e-6,'COLOR_COMPONENT_MAX_SIX_DECIMALS');return n===0||n===1e6?String(n/1e6):('0.'+String(n).padStart(6,'0')).replace(/0+$/,'')}
 function alignment(v){need(typeof v==='string'&&!!v,'ALIGNMENT_LITERAL_REQUIRED');const f=v.split('|');need(new Set(f).size===f.length&&f.every(x=>['left','right','center','top','bottom','nobaseline'].includes(x)),'ALIGNMENT_FLAGS_UNSUPPORTED');need(['left','right','center'].filter(x=>f.includes(x)).length<=1&&['top','bottom'].filter(x=>f.includes(x)).length<=1,'ALIGNMENT_FLAGS_CONFLICT');return v}
 function texture(v){need(typeof v==='string'&&!v.includes('\\')&&!v.includes(':')&&v.startsWith('gfx/'),'TEXTURE_RELATIVE_GFX_REQUIRED');need(!v.split('/').includes('..')&&/\.(dds|png|tga)$/i.test(v),'TEXTURE_PATH_UNSUPPORTED');return G.literal(v)}
 const encoders={literal:G.literal,font:G.font,dimension:G.dimension,coordinate,component,align_word:alignment,align_string:v=>G.literal(alignment(v)),texture};
 function request(m,edits){return{schema:'guanchuang.appearance-request.v1',source:m.source,window:m.window,base_sha256:m.base_sha256,edits}}
 async function apply(m,r){
  need(m.schema==='guanchuang.explicit-appearance.v1'&&r.schema==='guanchuang.appearance-request.v1','APPEARANCE_SCHEMA');
  need(r.base_sha256===m.base_sha256,'SOURCE_CONFLICT');need(r.source===m.source&&r.window===m.window,'TARGET_CONFLICT');
  need(r.edits&&typeof r.edits==='object'&&!Array.isArray(r.edits)&&Object.keys(r.edits).every(k=>Object.hasOwn(m.targets,k)),'UNSUPPORTED_TARGET');
  const fields={},changes={},encode={};
  for(const[alias,t]of Object.entries(m.targets)){
   const selected=Object.hasOwn(r.edits,alias)?r.edits[alias]:{};
   need(selected&&typeof selected==='object'&&!Array.isArray(selected)&&Object.keys(selected).every(k=>Object.hasOwn(t.fields,k)),'UNSUPPORTED_EDIT');
   for(const[k,f]of Object.entries(t.fields)){need(Object.hasOwn(encoders,f.encoder),'UNSUPPORTED_ENCODER');const key=alias+'.'+k;fields[key]=f;encode[key]=encoders[f.encoder]}
   for(const[k,v]of Object.entries(selected)){need(k!=='texture'||m.texture_choices.includes(v),'TEXTURE_NOT_IN_DECLARED_CHOICES');changes[alias+'.'+k]=v}
  }
  return{...await G.patch({...m,fields},changes,encode),request:r};
 }
 const api={request,apply,encoders};root.GuanchuangAppearance=api;
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
