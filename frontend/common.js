// ========== 鹰眼 common.js ==========
// 告警服务独立部署在 8090 端口，页面通过「当前主机名 + 8090」访问 API，
// 因此用文件方式（file:// 或 nginx）打开页面都能工作。

const API_BASE = 'http://' + location.hostname + ':8090';

// ---------- Toast ----------
(function () {
  const wrap = document.createElement('div');
  wrap.className = 'yz-toast-wrap';
  document.body.appendChild(wrap);

  window.showToast = function (msg, type) {
    const t = document.createElement('div');
    t.className = 'yz-toast ' + (type || 'info');
    t.textContent = msg;
    wrap.appendChild(t);
    requestAnimationFrame(() => t.classList.add('show'));
    setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 320); }, 2600);
  };
  window.alert = function (msg) { window.showToast(msg, 'info'); };
})();

// 统一 fetch 封装
async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  const resp = await fetch(API_BASE + path, { ...options, headers });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || data.code !== 200) {
    showToast(data.message || ('请求失败(' + resp.status + ')'), 'error');
    throw new Error(data.message || resp.status);
  }
  return data;
}

// 导航（鹰眼品牌色为青色系）
function renderNav(links = []) {
  const nav = document.querySelector('nav');
  nav.classList.add('yz-nav');
  const right = links.map(l => `<a class="btn btn-outline-light btn-sm me-2" href="${l.href}">${l.text}</a>`).join('');
  nav.innerHTML = '<div class="container-fluid">'
    + '<a class="navbar-brand" href="alerts.html">🦅 鹰眼 · 统一可观测平台</a>'
    + '<div>' + right + '</div>'
    + '</div>';
}

// 渲染表格
function renderTable(tableId, list, cols, opsHtml) {
  const thead = '<tr>' + cols.map(c => '<th>' + c.title + '</th>').join('')
    + (opsHtml ? '<th>操作</th>' : '') + '</tr>';
  const tbody = list.map(item =>
    '<tr>' + cols.map(c => '<td>' + (item[c.key] ?? '-') + '</td>').join('')
    + (opsHtml ? opsHtml(item) : '') + '</tr>').join('');
  document.querySelector(tableId + ' thead').innerHTML = thead;
  document.querySelector(tableId + ' tbody').innerHTML = tbody || '<tr><td colspan="99"><div class="yz-empty"><span class="emoji">📭</span>暂无数据</div></td></tr>';
}

// 告警状态/级别徽章
function statusBadge(status) {
  return status === 'firing'
    ? '<span class="badge text-bg-danger">触发中</span>'
    : '<span class="badge text-bg-success">已恢复</span>';
}
function severityBadge(sev) {
  const map = { critical: 'text-bg-danger', warning: 'text-bg-warning', info: 'text-bg-info' };
  return '<span class="badge ' + (map[sev] || 'text-bg-secondary') + '">' + (sev || '-') + '</span>';
}
