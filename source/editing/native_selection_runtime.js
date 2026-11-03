/* Source-bound selection only. Native observations never alter draft values. */
(function(root){
  'use strict';
  function requireValue(ok,code){if(!ok)throw new Error(code)}
  function validate(index,h,hash){
    requireValue(index?.schema==='guanchuang.native-source-index.v1','SOURCE_INDEX_REQUIRED');
    requireValue(['guanchuang-native-handoff-v1','guanchuang-native-handoff-v2'].includes(h?.contract),'HANDOFF_SCHEMA');
    requireValue(h.source_id===index.source_id,'SOURCE_ID_CONFLICT');
    const l=h.locator;
    requireValue(l?.status==='UNIQUE_SOURCE_BLOCK'&&Array.isArray(l.candidates)&&l.candidates.length===1,'SELECTION_NOT_UNIQUE');
    requireValue(/^[0-9a-f]{64}$/i.test(hash||'')&&hash.toLowerCase()===index.sha256&&hash.toLowerCase()===String(l.source_sha256).toLowerCase(),'SOURCE_CHANGED');
    const c=l.candidates[0],n=Object.hasOwn(index.nodes,c.node_id)?index.nodes[c.node_id]:null;
    requireValue(n,'NODE_ID_CONFLICT');
    for(const edge of ['start','end'])for(const field of ['byte','line','column'])
      requireValue(c.source_span?.[edge]?.[field]===n.source_span[edge][field],'SOURCE_SPAN_CONFLICT');
    const line=l.selection?.line,column=l.selection?.column,name=l.selection?.name;
    requireValue(Number.isInteger(line)&&line>=n.line&&line<=n.end_line,'LINE_OUT_OF_RANGE');
    if(column!=null){
      requireValue(Number.isInteger(column)&&column>=1,'COLUMN_OUT_OF_RANGE');
      requireValue((line!==n.line||column>=n.source_span.start.column)&&(line!==n.end_line||column<n.source_span.end.column),'COLUMN_OUT_OF_RANGE');
    }
    if(h.contract==='guanchuang-native-handoff-v2'&&name!=null)
      requireValue(name===n.name&&line===n.line,'NAMED_DECLARATION_NOT_UNIQUE_AT_OBSERVED_LINE');
    return {node_id:c.node_id,...n};
  }
  function match(m,h,hash,index){
    requireValue(['guanchuang.explicit-appearance.v1','guanchuang.gui-workspace.v1'].includes(m?.schema),'WORKSPACE_SCHEMA');
    requireValue(index?.source_id===m.source&&hash===m.base_sha256,'SOURCE_CONFLICT');
    const node=validate(index,h,hash);
    requireValue(!node.template_scope,'SHARED_TEMPLATE_READ_ONLY');
    const hits=Object.entries(m.targets||{}).filter(([,t])=>t.owner_id===node.node_id);
    requireValue(hits.length===1,'NODE_NOT_EDITABLE');return hits[0][0];
  }
  async function fileBytes(file){
    requireValue(file&&typeof file.arrayBuffer==='function','CURRENT_SOURCE_REQUIRED');
    const bytes=await file.arrayBuffer();
    requireValue(root.crypto?.subtle,'SHA256_UNAVAILABLE');
    const hash=Array.from(new Uint8Array(await root.crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
    return {bytes,hash};
  }
  async function apply(m,h,file,index,choose){
    const {hash}=await fileBytes(file),alias=match(m,h,hash,index);choose(alias);return alias;
  }
  async function inspect(index,h,file){
    const {bytes,hash}=await fileBytes(file),node=validate(index,h,hash);
    requireValue(node.start>=0&&node.end>node.start&&node.end<=bytes.byteLength,'SOURCE_SPAN_CONFLICT');
    return {...node,snippet:new TextDecoder('utf-8',{fatal:true}).decode(new Uint8Array(bytes).slice(node.start,node.end))};
  }
  const api={validate,match,apply,inspect};root.GuanchuangNativeSelection=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
