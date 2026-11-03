/* Capture the visible DOM after CSS, fonts, layout, and optional state changes. */
(root) => {
  const warnings = new Set();
  const rect = r => ({x:r.x, y:r.y, w:r.width, h:r.height});
  const paintProps = ['backgroundColor','backgroundImage','backgroundPosition','backgroundSize','backgroundRepeat','backgroundOrigin','backgroundClip','borderTop','borderRight','borderBottom','borderLeft','borderRadius','objectFit','objectPosition','filter','imageRendering'];
  const isClear = c => c === 'transparent' || /^rgba\([^)]*,\s*0(?:\.0+)?\)$/.test(c);
  let sequence = 0;
  function measureText(node, style, alpha) {
    const rows = [];
    const range = document.createRange();
    let offset = 0, row = null;
    for (const ch of node.nodeValue) {
      range.setStart(node,offset);
      offset += ch.length;
      range.setEnd(node,offset);
      const r = range.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      if (!row || Math.abs(row.y-r.y) > 1) {
        row = {text:'', x:r.left, y:r.top, w:r.width, h:r.height, font:parseFloat(style.fontSize), family:style.fontFamily, weight:style.fontWeight, color:style.color, alpha};
        rows.push(row);
      }
      row.w = Math.max(row.x + row.w,r.right) - Math.min(row.x,r.left);
      row.x = Math.min(row.x,r.left);
      row.text += ch;
    }
    return rows.filter(r => r.text.trim());
  }
  function visit(el, parentAlpha) {
    const style = getComputedStyle(el);
    if (['SCRIPT','STYLE','LINK','META','TEMPLATE','NOSCRIPT'].includes(el.tagName) || style.display==='none' || style.visibility==='hidden') return [];
    const alpha = parentAlpha * Number(style.opacity);
    if (alpha <= 0) return [];
    const box=rect(el.getBoundingClientRect());
    const ident=el.id || el.getAttribute('data-gc-name') || (el.classList[0] || el.localName) + '_' + (++sequence);
    const out={id:ident,tag:el.localName,box,paint:null,texts:[],children:[]};
    const hasBorder=['Top','Right','Bottom','Left'].some(side=>parseFloat(style['border'+side+'Width'])>0);
    if (box.w>0 && box.h>0 && (!isClear(style.backgroundColor) || style.backgroundImage!=='none' || hasBorder || el.tagName==='IMG')) {
      out.paint={style:Object.fromEntries(paintProps.map(k=>[k,style[k]])),alpha,image:el.tagName==='IMG'?(el.currentSrc||el.src):null};
    }
    if (el.tagName==='CANVAS' || el.tagName==='SVG' || el.tagName==='VIDEO') warnings.add(ident+'：'+el.tagName+' 媒体内容未重建');
    if (style.boxShadow!=='none' || style.textShadow!=='none') warnings.add(ident+'：投影未重建');
    if (style.transform!=='none') warnings.add(ident+'：变换以外接矩形记录');
    if (style.zIndex!=='auto' && Number(style.zIndex)!==0) warnings.add(ident+'：叠放按文档顺序，需核对 z-index');
    for (const pseudo of ['::before','::after']) {
      if (!['none','normal','""'].includes(getComputedStyle(el,pseudo).content)) warnings.add(ident+'：伪元素未重建');
    }
    if (el.scrollHeight>el.clientHeight+1 && ['auto','scroll','hidden'].includes(style.overflowY))
      warnings.add(ident+'：滚动或裁切按当前静态布局核对');
    for (const child of el.childNodes) {
      if (child.nodeType===Node.TEXT_NODE) out.texts.push(...measureText(child,style,alpha));
      else if (child.nodeType===Node.ELEMENT_NODE) out.children.push(...visit(child,alpha));
    }
    if (!box.w || !box.h) return out.children;
    if (!out.paint && !out.children.length && !out.texts.length && el!==root && !el.id) return [];
    return [out];
  }
  const tree=visit(root,1)[0];
  if (!tree) throw Error('所选窗口没有可见尺寸');
  return {tree,warnings:[...warnings],viewport:[innerWidth,innerHeight],dpr:devicePixelRatio};
}
