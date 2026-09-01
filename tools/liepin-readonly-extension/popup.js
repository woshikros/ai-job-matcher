chrome.runtime.sendMessage({type:'status'}, result => {
  const node = document.getElementById('status');
  const connected = Boolean(result?.extension_connected);
  node.className = connected ? 'ok' : 'bad';
  node.textContent = connected ? '已连接本机岗位面板' : '尚未连接，请先启动AI岗位面板';
});
