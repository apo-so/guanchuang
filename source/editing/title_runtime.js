/* Source-backed title patching. Shared by the editor page and local parity tests. */
(function (root) {
  'use strict';
  const enc = new TextEncoder();
  const need = (ok, code) => { if (!ok) throw new Error(code); };
  function bytes(base64) { return Uint8Array.from(atob(base64), c => c.charCodeAt(0)); }
  function equal(a, b) { return a.length === b.length && a.every((v, i) => v === b[i]); }
  async function sha(raw) {
    const result = await root.crypto.subtle.digest('SHA-256', raw);
    return Array.from(new Uint8Array(result), b => b.toString(16).padStart(2, '0')).join('');
  }
  function literal(value) {
    need(typeof value === 'string', 'TITLE_MUST_BE_STRING');
    need(!/[\r\n\t\[\]$#]/.test(value), 'TITLE_LITERAL_SUBSET_ONLY');
    for (const ch of value) {
      const code = ch.codePointAt(0);
      need(code >= 32 && !(code >= 0xd800 && code <= 0xdfff), 'INVALID_TITLE_CODEPOINT');
    }
    return '"' + value.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
  }
  function font(value) {
    need(Number.isInteger(value) && value > 0 && value <= 4096, 'FONT_MUST_BE_POSITIVE_INTEGER_UP_TO_4096');
    return String(value);
  }
  function dimension(value) {
    need(Number.isInteger(value) && value > 0 && value <= 65536, 'SIZE_MUST_BE_POSITIVE_INTEGER_UP_TO_65536');
    return String(value);
  }
  function request(m, changes) {
    return {schema:m.schema==='guanchuang.literal-button.v1'?'guanchuang.button-edit-request.v1':'guanchuang.title-edit-request.v1', base_sha256:m.base_sha256,
      source:m.source, window:m.window, owner_id:m.owner_id, changes};
  }
  async function apply(m, req) {
    const button=m.schema==='guanchuang.literal-button.v1';
    need(m.schema==='guanchuang.literal-title.v1'||button,'MANIFEST_SCHEMA');
    need(req.schema === (button?'guanchuang.button-edit-request.v1':'guanchuang.title-edit-request.v1'), 'REQUEST_SCHEMA');
    need(req.base_sha256 === m.base_sha256, 'SOURCE_CONFLICT');
    need(['source','window','owner_id'].every(k => req[k] === m[k]), 'TARGET_CONFLICT');
    need(req.changes && typeof req.changes === 'object' && !Array.isArray(req.changes) &&
      Object.keys(req.changes).every(k => (button?['raw_text','width','height']:['raw_text','fontsize']).includes(k)), 'UNSUPPORTED_EDIT');
    const encoders = button ? {raw_text:literal,width:dimension,height:dimension} : {raw_text:literal,fontsize:font};
    const result = await patch(m,req.changes,encoders);
    return {...result, request:req};
  }
  async function patch(m, changes, encoders) {
    const original = bytes(m.source_base64);
    need(await sha(original) === m.base_sha256, 'SOURCE_CONFLICT');
    need(changes && typeof changes==='object' && !Array.isArray(changes) &&
      Object.keys(changes).every(k=>Object.hasOwn(encoders,k)&&Object.hasOwn(m.fields,k)), 'UNSUPPORTED_EDIT');
    const patches = [], values = Object.fromEntries(Object.entries(m.fields).map(([k,v])=>[k,v.value]));
    for (const [field, value] of Object.entries(changes)) {
      const token = encoders[field](value), old = m.fields[field];
      const [a,b] = old.span;
      need(Number.isSafeInteger(a) && Number.isSafeInteger(b) && a >= 0 && b > a && b <= original.length,
        'INVALID_TOKEN_SPAN');
      need(equal(original.slice(a,b), enc.encode(old.old_token)), 'OLD_TOKEN_CONFLICT');
      values[field] = value;
      if (value !== old.value) patches.push({field,span:[a,b],old_token:old.old_token,new_token:token});
    }
    patches.sort((a,b) => a.span[0] - b.span[0]);
    need(patches.every((p,i) => !i || patches[i-1].span[1] <= p.span[0]), 'OVERLAPPING_EDITS');
    let length = original.length;
    for (const p of patches) length += enc.encode(p.new_token).length - (p.span[1] - p.span[0]);
    const draft = new Uint8Array(length);
    let sourceOffset = 0, outputOffset = 0;
    for (const p of patches) {
      const unchanged = original.slice(sourceOffset,p.span[0]), replacement = enc.encode(p.new_token);
      draft.set(unchanged,outputOffset); outputOffset += unchanged.length;
      draft.set(replacement,outputOffset); outputOffset += replacement.length;
      sourceOffset = p.span[1];
    }
    draft.set(original.slice(sourceOffset),outputOffset);
    return {bytes:draft, receipt:{status:'BYTE_LOCAL_GUI_DRAFT_GENERATED',
      before_sha256:m.base_sha256,after_sha256:await sha(draft),patches,reimport_values:values,
      no_edit_byte_identical:!patches.length && equal(original,draft),untouched_bytes_verified:true,
      full_parser_reimport:'NOT_RUN_IN_BROWSER',native_render:'NOT_RUN',deployment:false}};
  }
  const api = {bytes,equal,sha,literal,font,dimension,request,apply,patch};
  root.GuanchuangTitle = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(globalThis);
