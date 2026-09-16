// Normal page navigation only. No cookies, platform API calls or chat actions.
function waitForTabComplete(tabId, timeoutMs = 15000, settleMs = 500) {
  let cancel = () => {};
  const pending = new Promise((resolve, reject) => {
    const cleanup = () => { clearTimeout(timer); chrome.tabs.onUpdated.removeListener(listener); };
    const timer = setTimeout(() => { cleanup(); reject(new Error('Liepin page navigation timed out')); }, timeoutMs);
    function listener(id, info) {
      if (id === tabId && info.status === 'complete') { cleanup(); setTimeout(resolve, settleMs); }
    }
    cancel = () => { cleanup(); resolve(); };
    chrome.tabs.onUpdated.addListener(listener);
  });
  pending.cancel = () => cancel();
  return pending;
}
function readLiepinDetail() {
  const text = document.body?.innerText || '';
  return {
    url: location.href, title: document.title || '',
    description: (document.querySelector('[data-selector="job-intro-content"]')?.innerText || '').trim(),
    update_text: (document.querySelector('.update-time')?.innerText || ''),
    login_required: /登录.{0,6}查看.{0,6}职位|登录查看完整|登录后查看|请先登录/.test(text)
      || /passport|login/.test(location.hostname + location.pathname),
    security_check: /请完成安全验证|人机验证|访问过于频繁|访问受限|访问异常/.test(text)
      || /verify|captcha|security/.test(location.pathname),
  };
}

async function extractLiepinDetail(url) {
  const target = new URL(url);
  if (target.protocol !== 'https:' || target.hostname !== 'www.liepin.com'
      || !/^\/(job|a)\/\d+\.shtml$/.test(target.pathname)) {
    throw new Error('Only Liepin job detail pages are allowed');
  }
  const tabs = await chrome.tabs.query({});
  const anchor = tabs.find(tab => {
    try { const u = new URL(tab.url || ''); return u.protocol === 'https:' && ['www.liepin.com','c.liepin.com'].includes(u.hostname); }
    catch (_) { return false; }
  });
  if (!anchor) throw new Error('请先在Chrome中打开并登录猎聘，详情备用读取需要正常猎聘页面');
  const tab = await chrome.tabs.create({url:'about:blank', active:false, windowId:anchor.windowId});
  let loaded;
  try {
    loaded = waitForTabComplete(tab.id, 15000, 500);
    await chrome.tabs.update(tab.id, {url, active:false});
    await loaded;
    for (let attempt=0; attempt<8; attempt++) {
      const current = await chrome.tabs.get(tab.id);
      const actual = new URL(current.url || 'about:blank');
      if (actual.origin !== target.origin || actual.pathname !== target.pathname) {
        return {url:current.url, description:'', login_required:/login|passport/.test(current.url || ''),
          security_check:/verify|captcha|security/.test(current.url || '')};
      }
      const results = await chrome.scripting.executeScript({target:{tabId:tab.id}, func:readLiepinDetail});
      const result = results[0]?.result || {};
      if (result.security_check || result.login_required || result.description?.length >=80 || attempt===7) return result;
      await new Promise(resolve => setTimeout(resolve, 500));
    }
  } finally {
    if (loaded?.cancel) loaded.cancel();
    try { await chrome.tabs.remove(tab.id); } catch (_) {}
  }
}
