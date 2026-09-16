const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
function setup(text = '真实职位说明。'.repeat(30), pageText = '') {
  const operations = [];
  const listeners = new Set();
  const url = 'https://www.liepin.com/job/123.shtml';
  const ctx = vm.createContext({URL, setTimeout:(fn,delay)=>setTimeout(fn,delay===500?0:delay), clearTimeout, location:new URL(url),
    document: {title:'测试职位',body:{innerText:pageText},querySelector: selector => selector === '[data-selector="job-intro-content"]' ? {innerText:text}:null},
    waitForTabComplete: () => Object.assign(Promise.resolve(), {cancel(){}}),
    chrome: {tabs:{
      query:async()=>[{id:1,url:'https://c.liepin.com/',windowId:4}],
      create:async args=>{operations.push(['create',args]);return {id:2};},
      update:async(id,args)=>{operations.push(['update',id,args]);for(const fn of listeners) fn(id,{status:'complete'});},
      onUpdated:{addListener:fn=>listeners.add(fn),removeListener:fn=>listeners.delete(fn)},
      get:async()=>({id:2,url}), remove:async id=>operations.push(['remove',id])},
      scripting:{executeScript:async({func,args=[]})=>[{result:await func(...args)}]}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../tools/liepin-readonly-extension/liepin-detail.js'),'utf8'),ctx);
  return {ctx,operations,url};
}
test('read exact JD in private temporary tab and preserve user tab', async()=>{
  const {ctx,operations,url}=setup();
  const result=await ctx.extractLiepinDetail(url);
  assert.ok(result.description.length>=80);
  assert.equal(operations.find(o=>o[0]==='update')[1],2);
  assert.equal(operations.find(o=>o[0]==='create')[1].active,false);
  assert.deepEqual(operations.at(-1),['remove',2]);
});
test('reject arbitrary links before opening a tab',async()=>{
  const {ctx,operations}=setup();
  await assert.rejects(ctx.extractLiepinDetail('https://example.com/job/123.shtml'));
  await assert.rejects(ctx.extractLiepinDetail('https://www.liepin.com/chat'));
  assert.equal(operations.length,0);
});
test('verification text is not accepted as JD',async()=>{
  const {ctx,url}=setup('职位说明。'.repeat(30),'请完成安全验证');
  const result=await ctx.extractLiepinDetail(url);
  assert.equal(result.security_check,true);
});
test('login page is not accepted as JD',async()=>{
  const {ctx,url}=setup('职位说明。'.repeat(30),'请登录后查看完整职位');
  const result=await ctx.extractLiepinDetail(url);
  assert.equal(result.login_required,true);
});
