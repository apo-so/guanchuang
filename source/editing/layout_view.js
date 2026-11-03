/* Fixed-layout scene, using the editor's actual bound values for every refresh. */
(() => {
  const model=JSON.parse(document.getElementById('gc-model').textContent);
  const scene=document.getElementById('gc-scene');
  const conditions=new Map(), controls=document.getElementById('gc-conditions');
  const note=document.getElementById('gc-warnings');
  note.textContent=model.warnings.join(' · ') || '此窗口使用固定位置布局。';
  function enumerate(node,depth) {
    if (depth && !['yes','no','true','false',''].includes(node.visible)) {
      const id=node.alias||node.name;
      const input=document.createElement('input');input.type='checkbox';
      input.checked=node.kind==='widget' && ![...conditions.values()].some(t=>t.checked);
      conditions.set(id,input);input.onchange=()=>window.refreshWholeLayout(values,selected);
      const label=document.createElement('label');label.append(input,document.createTextNode(node.name));controls.append(label);
    }
    node.children.forEach(n=>enumerate(n,depth+1));
  }
  enumerate(model.tree,0);
  function build(node,vals,current,root) {
    if (!root && (['no','false'].includes(node.visible) || conditions.get(node.alias||node.name)?.checked===false)) return null;
    const v=vals[node.alias]||{},el=document.createElement('div');
    el.className='gc-item';el.dataset.name=node.name;el.dataset.kind=node.kind;
    el.dataset.alias=node.alias||'';el.dataset.selected=node.alias===current?'yes':'no';
    el.style.left=(root&&!document.getElementById('gc-origin').checked?0:(v.position_x||0))+'px';
    el.style.top=(root&&!document.getElementById('gc-origin').checked?0:(v.position_y||0))+'px';
    if (v.width!==undefined) el.style.width=v.width+'px';
    if (v.height!==undefined) el.style.height=v.height+'px';
    if (v.texture && D.assets[v.texture]?.preview_png_base64)
      el.style.backgroundImage='url("data:image/png;base64,'+D.assets[v.texture].preview_png_base64+'")';
    if (node.kind==='textbox' || v.raw_text!==undefined || node.text) {
      const text=v.raw_text??model.labels[node.text]??(node.text.startsWith('[')?'〈动态文字〉':node.text);
      const flags=(v.align||'left').split('|');
      Object.assign(el.style,{display:'flex',alignItems:flags.includes('top')?'flex-start':flags.includes('bottom')?'flex-end':'center',
        justifyContent:flags.includes('right')?'flex-end':flags.includes('center')?'center':'flex-start',
        color:'rgba('+[v.color_r??0.8,v.color_g??0.8,v.color_b??0.8].map(n=>Math.round(n*255)).join(',')+','+(v.color_a??1)+')',
        fontSize:(v.fontsize||14)+'px'});
      if (v.raw_text!==undefined && /_text_\d+$/.test(node.name)) el.style.whiteSpace='pre';
      el.textContent=text;
    }
    for (const ch of node.children) {const child=build(ch,vals,current,false);if(child)el.appendChild(child);}
    if (node.alias) el.addEventListener('click',event=>{event.stopPropagation();selectNativeTarget(node.alias);});
    return el;
  }
  window.refreshWholeLayout=(vals,current)=>{
    const root=model.tree,v=vals[root.alias]||{};
    const origin=document.getElementById('gc-origin').checked;
    const w=Math.max(1,(v.width||800)+(origin?Math.max(0,v.position_x||0):0));
    const h=Math.max(1,(v.height||600)+(origin?Math.max(0,v.position_y||0):0));
    const z=Number(document.getElementById('gc-zoom').value);
    scene.style.width=w+'px';scene.style.height=h+'px';scene.style.transformOrigin='0 0';scene.style.transform='scale('+z+')';
    const sizer=document.getElementById('gc-sizer');sizer.style.width=Math.ceil(w*z)+'px';sizer.style.height=Math.ceil(h*z)+'px';
    scene.replaceChildren(build(root,vals,current,true));
  };
  for (const id of ['gc-zoom','gc-origin']) document.getElementById(id).onchange=()=>window.refreshWholeLayout(values,selected);
  window.refreshWholeLayout(values,selected);
})();
