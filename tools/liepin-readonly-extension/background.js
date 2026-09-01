const DAEMON_WS = 'ws://127.0.0.1:19826/ext';
const DAEMON_STATUS = 'http://127.0.0.1:19826/status';
const CONTACT_API = 'com.liepin.im.c.contact.get-contact-list';
const CHAT_API = 'com.liepin.im.c.chat.chat-list';
const RECORD_EVENT = 'ai-job-matcher-liepin-contact-record';
const recordStates = new Map();
let socket = null;
let keepAliveTimer = null;

function isLiepinUrl(value) {
  try { const url = new URL(value); return url.protocol === 'https:' && (url.hostname === 'liepin.com' || url.hostname.endsWith('.liepin.com')); }
  catch (_) { return false; }
}

function stateFor(tabId) {
  if (!recordStates.has(tabId)) recordStates.set(tabId, {nonce: crypto.randomUUID(), records: []});
  return recordStates.get(tabId);
}

function installReceiver(nonce) {
  if (window.__aiJobMatcherLiepinReceiver?.nonce === nonce) return;
  window.__aiJobMatcherLiepinReceiver = {nonce};
  window.addEventListener('message', event => {
    const data = event.data || {};
    if (event.source !== window || data.type !== 'ai-job-matcher-liepin-contact-record' || data.nonce !== nonce) return;
    if (!['com.liepin.im.c.contact.get-contact-list','com.liepin.im.c.chat.chat-list'].some(endpoint => String(data.url || '').includes(endpoint))) return;
    if (!Number.isInteger(data.status) || data.status < 200 || data.status >= 300) return;
    if (typeof data.body !== 'string' || data.body.length < 2 || data.body.length > 300000) return;
    chrome.runtime.sendMessage({type:'liepin-contact-record', nonce, url:data.url, body:data.body, at:Number(data.at)||Date.now()});
  });
}

function installRecorder(nonce) {
  if (window.__aiJobMatcherLiepinRecorder?.installed) { window.__aiJobMatcherLiepinRecorder.nonce = nonce; return; }
  const endpoints = ['com.liepin.im.c.contact.get-contact-list', 'com.liepin.im.c.chat.chat-list'];
  const emit = (url, status, body) => {
    if (!endpoints.some(endpoint => String(url || '').includes(endpoint)) || Number(status) < 200 || Number(status) >= 300) return;
    const text = String(body || ''); if (!text || text.length > 300000) return;
    window.postMessage({type:'ai-job-matcher-liepin-contact-record', nonce:window.__aiJobMatcherLiepinRecorder?.nonce||'', url:String(url), status:Number(status), body:text, at:Date.now()}, '*');
  };
  const originalFetch = window.fetch;
  if (typeof originalFetch === 'function') window.fetch = function (...args) {
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
    return originalFetch.apply(this,args).then(response => { if (endpoints.some(endpoint => String(url).includes(endpoint))) response.clone().text().then(text => emit(url,response.status,text)).catch(()=>{}); return response; });
  };
  const originalOpen = XMLHttpRequest.prototype.open, originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method,url,...rest) { this.__aiJobMatcherUrl=String(url||''); return originalOpen.call(this,method,url,...rest); };
  XMLHttpRequest.prototype.send = function (...args) { this.addEventListener('loadend',()=>{ if (!endpoints.some(endpoint => String(this.__aiJobMatcherUrl||'').includes(endpoint))) return; let text=''; try{text=this.responseType===''||this.responseType==='text'?this.responseText:JSON.stringify(this.response)}catch(_){} emit(this.__aiJobMatcherUrl,this.status,text); }); return originalSend.apply(this,args); };
  window.__aiJobMatcherLiepinRecorder = {nonce,installed:true};
}

async function ensureRecorder(tabId) {
  const state = stateFor(tabId);
  try {
    await chrome.scripting.executeScript({target:{tabId},world:'ISOLATED',func:installReceiver,args:[state.nonce]});
    await chrome.scripting.executeScript({target:{tabId},world:'MAIN',func:installRecorder,args:[state.nonce]});
  } catch (_) {}
  return state;
}

async function chatTab() {
  const tabs = await chrome.tabs.query({});
  const candidates = tabs.filter(tab => tab.id && isLiepinUrl(tab.url || ''));
  const tab = candidates.find(tab => tab.active) || candidates.find(tab => { try{return new URL(tab.url||'').hostname==='c.liepin.com'}catch(_){return false} }) || candidates[0];
  if (!tab) throw new Error('Liepin chat tab required: 请先登录猎聘候选人端并打开沟通面板');
  return tab;
}

async function prepareDrawer(tabId, maxThreads, refresh=false) {
  const state = await ensureRecorder(tabId), since = Date.now();
  await chrome.scripting.executeScript({target:{tabId,allFrames:true},func:async(limit,reopen)=>{
    const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
    const visible=e=>{if(!e)return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'};
    const entry=document.querySelector('.im-ui-basic-entry'); let items=[...document.querySelectorAll('.im-ui-contact-list-item')].filter(visible);
    if(!items.length&&entry){entry.click();await sleep(1000);items=[...document.querySelectorAll('.im-ui-contact-list-item')].filter(visible)}
    else if(reopen&&entry){entry.click();await sleep(350);entry.click();await sleep(1000);items=[...document.querySelectorAll('.im-ui-contact-list-item')].filter(visible)}
    if(!items.length)return;
    let scroller=items[0];while(scroller&&scroller.scrollHeight<=scroller.clientHeight+5)scroller=scroller.parentElement;
    if(scroller){scroller.scrollTop=0;await sleep(250);for(let i=0;i<10;i+=1){const before=scroller.scrollTop;scroller.scrollTop+=Math.max(1,scroller.clientHeight*.9);await sleep(500);if(scroller.scrollTop===before||document.querySelectorAll('.im-ui-contact-list-item').length>=limit)break}scroller.scrollTop=0}
  },args:[maxThreads,refresh]});
  await new Promise(resolve=>setTimeout(resolve,500)); return {state,since};
}

async function readOverview(maxThreads, passiveRecords) {
  const clean=v=>String(v||'').replace(/[\u0000-\u001f\u007f]+/g,' ').replace(/\s+/g,' ').trim();
  const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>=120&&r.height>=30&&s.display!=='none'&&s.visibility!=='hidden'};
  const pageText=document.body?.innerText||'', securityCheck=/安全验证|访问异常|请完成验证|滑块验证/.test(pageText), loginRequired=/请先登录|登录后查看|扫码登录/.test(pageText)&&!/沟通|消息|会话/.test(pageText);
  if(securityCheck||loginRequired)return {threads:[],security_check:securityCheck,login_required:loginRequired};
  const decodeExt=e=>{try{return JSON.parse(decodeURIComponent(e.getAttribute('data-tlg-ext')||''))||{}}catch(_){return{}}};
  const timePattern=/(?:^|\s)(?:[01]?\d|2[0-3]):[0-5]\d(?:\s|$)|(?:\d{1,2}月\d{1,2}日|昨天|前天)/;
  const dom=[...document.querySelectorAll('.im-ui-contact-list-item')].filter(visible).slice(0,maxThreads).map(item=>{const ext=decodeExt(item),imid=String(ext.to_imid||ext.toImId||'');if(!imid)return null;const lines=(item.innerText||'').split(/\n+/).map(clean).filter(Boolean),name=lines[0]||'',time=lines.find(line=>timePattern.test(line))||'',summary=lines.filter(line=>line!==name&&line!==time).join(' ');return {thread_id:'imid-'+encodeURIComponent(imid),recruiter_name:name,company:'',job_name:'',platform_job_id:'',job_url:'',unread_count:item.querySelector('[class*="unread"]')?1:0,last_message:summary,last_sender:/^\[(?:已读|未读)\]/.test(summary)?'me':'unknown',last_message_at:time,_imid:imid}}).filter(Boolean);
  const byImid=new Map(dom.map(item=>[item._imid,item]));
  for(const record of Array.isArray(passiveRecords)?passiveRecords:[]){if(!String(record.url||'').includes('com.liepin.im.c.contact.get-contact-list'))continue;try{const parsed=JSON.parse(record.body),items=parsed?.data?.list||parsed?.data?.data?.list||[];for(const item of items){const imid=String(item?.oppositeImId||item?.opposite_im_id||'');if(!imid)continue;const current=byImid.get(imid)||{};byImid.set(imid,{thread_id:'imid-'+encodeURIComponent(imid),recruiter_name:clean(item?.name)||current.recruiter_name||'',company:clean(item?.company)||'',job_name:'',platform_job_id:'',job_url:'',unread_count:Number(item?.unReadCnt||0)||0,last_message:current.last_message||'',last_sender:current.last_sender||'unknown',last_message_at:current.last_message_at||'',_imid:imid})}}catch(_){}}
  const threads=[...byImid.values()].slice(0,maxThreads).map(({_imid,...item})=>item);
  return {threads,login_required:false,error:threads.length?'':'未读取到猎聘会话列表，请确认沟通抽屉已打开'};
}

async function extractOverview(params) {
  const maxThreads=Math.max(1,Math.min(Number(params?.max_threads||60),100)),tab=await chatTab();let prepared=await prepareDrawer(tab.id,maxThreads,false),records=prepared.state.records.filter(item=>item.at>=prepared.since&&String(item.url||'').includes(CONTACT_API));
  if(!records.length){prepared=await prepareDrawer(tab.id,maxThreads,true);records=prepared.state.records.filter(item=>item.at>=prepared.since&&String(item.url||'').includes(CONTACT_API))}
  const results=await chrome.scripting.executeScript({target:{tabId:tab.id,allFrames:true},func:readOverview,args:[maxThreads,records]});
  return results.map(item=>item?.result).filter(Boolean).sort((a,b)=>(b.threads?.length||0)-(a.threads?.length||0))[0]||{threads:[],error:'未读取到猎聘会话列表'};
}

async function openContact(tabId,imid) {
  const results=await chrome.scripting.executeScript({target:{tabId,allFrames:true},func:async target=>{const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms)),match=item=>{try{const ext=JSON.parse(decodeURIComponent(item.getAttribute('data-tlg-ext')||''))||{};return String(ext.to_imid||ext.toImId||'')===target}catch(_){return false}};let items=[...document.querySelectorAll('.im-ui-contact-list-item')],selected=items.find(match),scroller=items[0];while(!selected&&scroller&&scroller.scrollHeight<=scroller.clientHeight+5)scroller=scroller.parentElement;if(!selected&&scroller){scroller.scrollTop=0;for(let i=0;i<12&&!selected;i+=1){items=[...document.querySelectorAll('.im-ui-contact-list-item')];selected=items.find(match);if(selected)break;const before=scroller.scrollTop;scroller.scrollTop+=Math.max(1,scroller.clientHeight*.85);await sleep(500);if(scroller.scrollTop===before)break}}if(!selected)return {opened:false,error:'未找到该会话，请重新同步列表'};selected.click();for(let i=0;i<20;i+=1){if(document.querySelector('.im-ui-msg-list-content'))break;await sleep(250)}await sleep(700);return {opened:Boolean(document.querySelector('.im-ui-msg-list-content'))}},args:[imid]});
  return results.map(item=>item?.result).find(item=>item?.opened)||results.map(item=>item?.result).find(item=>item?.error)||{opened:false};
}

async function readHistory(limit,threadId,passiveRecords) {
  const clean=v=>String(v||'').replace(/[\u0000-\u001f\u007f]+/g,' ').replace(/\s+/g,' ').trim(),stable=value=>{let h=2166136261;for(let i=0;i<value.length;i+=1)h=Math.imul(h^value.charCodeAt(i),16777619);return 'fallback-'+(h>>>0).toString(16)};
  const fromRecord=record=>{let payload={};try{payload=typeof record?.payload==='string'?JSON.parse(record.payload):(record?.payload||{})}catch(_){return null}const extType=Number(payload?.ext?.extType??1);if([200,214].includes(extType))return null;let content='',type='text';if(extType===201){const job=payload?.ext?.extBody?.bizData||{};content='[职位] '+[clean(job.jobTitle),clean(job.jobCompany),clean(job.jobSalary)].filter(Boolean).join('｜');type='job'}else{const body=payload?.bodies?.[0]||{};if(body.type==='img'){content='[图片]';type='image'}else if(body.type==='voice'){content='[语音]';type='voice'}else if(body.type==='file'){content='[文件] '+clean(body.filename);type='file'}else content=clean(body.msg)}if(!content)return null;const sender=String(record?.direction)==='0'?'me':String(record?.direction)==='1'?'recruiter':'unknown',time=Number(record?.msgTime||0);return {message_id:String(record?.msgId||'')||stable([threadId,time,sender,content].join('|')),sender,sender_name:'',message_type:type,content,sent_at:time?new Date(time).toISOString():'',_time:time}};
  const map=new Map();for(const passive of Array.isArray(passiveRecords)?passiveRecords:[]){if(!String(passive.url||'').includes('com.liepin.im.c.chat.chat-list'))continue;try{const parsed=JSON.parse(passive.body),items=parsed?.data?.list||parsed?.data?.data?.list||[];for(const record of items){const message=fromRecord(record);if(message)map.set(message.message_id,message)}}catch(_){}}
  let messages=[...map.values()].sort((a,b)=>a._time-b._time).slice(-limit).map(({_time,...message})=>message);
  if(!messages.length)messages=[...document.querySelectorAll('.im-ui-msg-list-content .im-ui-message-item')].map((node,index)=>{const body=node.querySelector('.im-ui-message-item-send,.im-ui-message-item-receive');if(!body)return null;const sender=body.classList.contains('im-ui-message-item-receive')?'recruiter':'me',content=clean(body.querySelector('.im-ui-txt')?.innerText)||clean(body.innerText),sentAt=clean(node.querySelector('[class*="time"]')?.textContent);return content?{message_id:stable([threadId,sentAt,sender,content,index].join('|')),sender,sender_name:'',message_type:'text',content,sent_at:sentAt}:null}).filter(Boolean).slice(-limit);
  return {messages,thread:{thread_id:threadId,last_message:messages.at(-1)?.content||'',last_sender:messages.at(-1)?.sender||'unknown',last_message_at:messages.at(-1)?.sent_at||''},error:messages.length?'':'未读取到聊天记录'};
}

async function extractHistory(params) {
  const threadId=String(params?.thread_id||'');if(!/^imid-[A-Za-z0-9_%~-]{1,220}$/.test(threadId))throw new Error('Invalid Liepin conversation id');const imid=decodeURIComponent(threadId.slice(5)),limit=Math.max(1,Math.min(Number(params?.limit||30),50)),tab=await chatTab(),prepared=await prepareDrawer(tab.id,100,false),since=Date.now(),opened=await openContact(tab.id,imid);if(!opened.opened)return {messages:[],error:opened.error||'猎聘会话打开失败'};await new Promise(resolve=>setTimeout(resolve,700));const records=prepared.state.records.filter(item=>item.at>=since&&String(item.url||'').includes(CHAT_API)),results=await chrome.scripting.executeScript({target:{tabId:tab.id,allFrames:true},func:readHistory,args:[limit,threadId,records]});return results.map(item=>item?.result).filter(Boolean).sort((a,b)=>(b.messages?.length||0)-(a.messages?.length||0))[0]||{messages:[],error:'未读取到聊天记录'};
}

async function handle(message) { try { const data=message.action==='extract_liepin_chat_overview'?await extractOverview(message.params||{}):message.action==='extract_liepin_chat_history'?await extractHistory(message.params||{}):null;if(!data)throw new Error('Unsupported command');return {id:message.id,ok:true,data}; } catch(error){return {id:message.id,ok:false,error:error?.message||String(error)}} }
function connect(){if(socket&&[WebSocket.OPEN,WebSocket.CONNECTING].includes(socket.readyState))return;socket=new WebSocket(DAEMON_WS);socket.onopen=()=>{socket.send(JSON.stringify({type:'hello',version:chrome.runtime.getManifest().version}));keepAliveTimer=setInterval(()=>{if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'keepalive'}))},20000)};socket.onmessage=async event=>{const response=await handle(JSON.parse(event.data));if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify(response))};socket.onclose=()=>{if(keepAliveTimer)clearInterval(keepAliveTimer);keepAliveTimer=null;socket=null};socket.onerror=()=>socket?.close()}
async function arm(){try{const tabs=await chrome.tabs.query({});await Promise.all(tabs.filter(tab=>tab.id&&isLiepinUrl(tab.url||'')).map(tab=>ensureRecorder(tab.id)))}catch(_){}}
chrome.runtime.onInstalled.addListener(()=>{connect();arm()});chrome.runtime.onStartup.addListener(()=>{connect();arm()});chrome.alarms.create('bridge-reconnect',{periodInMinutes:.5});chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name==='bridge-reconnect')connect()});chrome.tabs.onUpdated.addListener((tabId,change,tab)=>{if(change.status==='complete'&&isLiepinUrl(tab.url||''))ensureRecorder(tabId)});chrome.tabs.onRemoved.addListener(tabId=>recordStates.delete(tabId));chrome.runtime.onMessage.addListener((message,sender,sendResponse)=>{if(message?.type==='liepin-contact-record'){const tabId=sender.tab?.id;if(!tabId)return false;const state=stateFor(tabId);if(message.nonce!==state.nonce)return false;try{const parsed=JSON.parse(message.body);if(!Array.isArray(parsed?.data?.list)&&!Array.isArray(parsed?.data?.data?.list))return false}catch(_){return false}state.records.push({url:String(message.url||''),body:message.body,at:Number(message.at)||Date.now()});if(state.records.length>50)state.records.splice(0,state.records.length-50);return false}if(message?.type!=='status')return false;fetch(DAEMON_STATUS).then(response=>response.json()).then(sendResponse).catch(()=>sendResponse({ok:false,extension_connected:false}));return true});connect();arm();
