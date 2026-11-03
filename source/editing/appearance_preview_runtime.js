/* Source-bound absolute-layout projection. Pure model transform; not native rendering. */
(function(root){'use strict';
 const clone=v=>JSON.parse(JSON.stringify(v)),need=(v,e)=>{if(!v)throw new Error(e)};
 function intersection(a,b){if(!a||!b)return null;const x=Math.max(a[0],b[0]),y=Math.max(a[1],b[1]),r=Math.min(a[0]+a[2],b[0]+b[2]),d=Math.min(a[1]+a[3],b[1]+b[3]);return r>x&&d>y?[x,y,r-x,d-y]:null}
 function project(model,manifest,edits,assets){
  need(model.gui.sha256.toLowerCase()===manifest.base_sha256.toLowerCase()&&model.gui.file===manifest.source,'PREVIEW_SOURCE_CONFLICT');
  const m=clone(model),by=new Map(m.nodes.map(n=>[n.owner,n]));need(by.size===m.nodes.length,'PREVIEW_DUPLICATE_OWNER');
  for(const[alias,fields]of Object.entries(edits)){
   const target=manifest.targets[alias];need(target,'PREVIEW_TARGET_MISSING');
   const n=by.get(target.name);need(n&&n.line===target.line,'PREVIEW_OWNER_SOURCE_CONFLICT');
   for(const field of Object.keys(fields))need(Object.hasOwn(target.fields,field),'PREVIEW_UNSUPPORTED_FIELD');
   if(Object.hasOwn(fields,'position_x'))n.local[0]=fields.position_x;
   if(Object.hasOwn(fields,'position_y'))n.local[1]=fields.position_y;
   if(Object.hasOwn(fields,'width'))n.local[2]=fields.width;
   if(Object.hasOwn(fields,'height'))n.local[3]=fields.height;
   if(Object.hasOwn(fields,'fontsize')){need(n.style&&Number.isFinite(m.case_metrics?.ratio),'PREVIEW_FONT_METRICS_MISSING');n.style.fontsize=fields.fontsize;n.style.line_height_px=Math.round(fields.fontsize*m.case_metrics.ratio)}
   if(Object.hasOwn(fields,'align')){
    need(n.style,'PREVIEW_TEXT_STYLE_MISSING');const horizontal=['left','right','center'];
    const old=n.style.align.split('|').filter(x=>!horizontal.includes(x)).sort(),fresh=fields.align.split('|').filter(x=>!horizontal.includes(x)).sort();
    need(JSON.stringify(old)===JSON.stringify(fresh),'PREVIEW_VERTICAL_ALIGNMENT_UNSUPPORTED');n.style.align=fields.align;
   }
   if(['r','g','b','a'].some(k=>Object.hasOwn(fields,'color_'+k))){
    need(n.style?.color?.rgba,'PREVIEW_COLOR_MISSING');const rgba=n.style.color.rgba;
    ['r','g','b','a'].forEach((k,i)=>{if(Object.hasOwn(fields,'color_'+k))rgba[i]=fields['color_'+k]});
    n.style.color.css='rgba('+rgba.slice(0,3).map(v=>Math.round(v*255)).join(',')+','+rgba[3]+')';
   }
   if(Object.hasOwn(fields,'raw_text')){
    need(n.style,'PREVIEW_TEXT_STYLE_MISSING');n.style.text_raw=fields.raw_text;n.text_rule='static';
    for(const state of Object.values(m.states)){const old=state.texts[n.id]||{};state.texts[n.id]={...old,segments:[{text:fields.raw_text,bold:false}]}}
   }
   if(Object.hasOwn(fields,'texture')){const a=assets[fields.texture];need(a?.preview_png_base64,'PREVIEW_TEXTURE_UNAVAILABLE');n.paint={kind:'texture',src:fields.texture,png:'',data_url:'data:image/png;base64,'+a.preview_png_base64,fit:'stretch',provenance:'SOURCE_BOUND_APPEARANCE_EDIT'}}
  }
  if(Object.keys(edits).length){
   const done=new Set();
   for(const n of m.nodes){
    const p=n.parent?by.get(n.parent):null;need(!n.parent||p&&done.has(p.owner),'PREVIEW_PARENT_ORDER_UNSUPPORTED');
    n.rect=[n.local[0]+(p?p.rect[0]:0),n.local[1]+(p?p.rect[1]:0),n.local[2],n.local[3]];
    n.clip=p?p.clip_children:[0,0,m.canvas.w,m.canvas.h];
    n.clip_children=n.scissor||n.type==='scrollarea'?intersection(n.clip,n.rect):n.clip;done.add(n.owner);
   }
  }
  return m;
 }
 const api={project,intersection};root.GuanchuangAppearancePreview=api;
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
