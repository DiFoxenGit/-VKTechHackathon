import assert from 'node:assert/strict';
import {loadModule} from './load-module.mjs';
globalThis.window={setTimeout,clearTimeout};
let image;
globalThis.Image=class {
 naturalWidth=1200;
 constructor(){image=this;}
 decode(){return new Promise((resolve,reject)=>{this.decoded=resolve;this.decodeFailed=reject;});}
};
const {preparePreview,isPreviewReady}=await loadModule('src/services/previewReady.ts');
let ready=false;
const pending=preparePreview('/cover?revision=1').then(()=>ready=true);
assert.equal(ready,false);
image.onload();await Promise.resolve();assert.equal(ready,false,'A load event alone must not open the editor');
image.decoded();await pending;assert.equal(ready,true);assert.equal(isPreviewReady('/cover?revision=1'),true);
assert.equal(isPreviewReady('/cover?revision=2'),false,'A different revision must be loaded again');
const failed=preparePreview('/bad');image.onerror();await assert.rejects(failed,/обложку/);assert.equal(isPreviewReady('/bad'),false);
const controller=new AbortController();const cancelled=preparePreview('/cancel',controller.signal);controller.abort();await assert.rejects(cancelled,{name:'AbortError'});assert.equal(isPreviewReady('/cancel'),false);
await assert.rejects(preparePreview('/cover?revision=1',AbortSignal.abort()),{name:'AbortError'});
console.log('PASS: cover decode gate, revision isolation, failure and cancellation');
