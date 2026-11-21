'use strict';
// Shared by the private server dashboard and the public static GitHub Pages UI.
// Do not store the Admin token in localStorage, cookies, URLs or build artifacts.
let adminToken = '';
let apiOrigin = '';
const $ = id => document.getElementById(id);
const say = msg => { $('message').textContent = msg; };
const make = (tag, text, css) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (css) node.className = css;
  return node;
};
const td = (tr, value, css) => tr.appendChild(make('td', value == null ? '—' : value, css));

function normalizeOrigin(input) {
  const raw = (input || '').trim();
  if (!raw) throw new Error('Chưa có địa chỉ License Server HTTPS');
  let url;
  try { url = new URL(raw); } catch (_) { throw new Error('Địa chỉ server không hợp lệ'); }
  const localDev = url.protocol === 'http:' && ['localhost','127.0.0.1'].includes(url.hostname);
  if ((url.protocol !== 'https:' && !localDev) || !url.hostname || url.username || url.password ||
      url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Chỉ sử dụng origin HTTPS, ví dụ https://ten-server.onrender.com');
  }
  return url.origin;
}

function defaultOrigin() {
  const configured = window.TDS_CONFIG && window.TDS_CONFIG.apiBaseUrl;
  // When served by FastAPI itself, /admin continues to work same-origin.
  if (configured) return configured;
  if (location.hostname.endsWith('.github.io') || location.hostname.endsWith('.pages.dev')) return '';
  return location.origin;
}

const configuredOrigin = defaultOrigin();
$('serverUrl').value = configuredOrigin;
$('serverUrl').placeholder = 'https://ten-server.onrender.com';
if (configuredOrigin) $('serverState').textContent = 'Đã cấu hình địa chỉ server';
else $('serverState').textContent = 'Chưa cấu hình server — nhập địa chỉ HTTPS để kết nối';

async function call(path, method='GET', body=undefined) {
  if (!adminToken || !apiOrigin) throw new Error('Cần kết nối Admin trước');
  const response = await fetch(apiOrigin + '/v1/admin/' + path, {
    method,
    headers: {
      'Authorization': 'Bearer ' + adminToken,
      ...(body === undefined ? {} : {'Content-Type': 'application/json'})
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache:'no-store', credentials:'omit', referrerPolicy:'no-referrer'
  });
  let result;
  try { result = await response.json(); } catch (_) { result = {}; }
  if (!response.ok) throw new Error(result.detail || 'Server trả về HTTP ' + response.status);
  return result;
}
async function refresh() { await Promise.all([loadKeys(), loadLogs()]); }
function button(label, kind, onClick) {
  const el = make('button', label, kind);
  el.type='button'; el.addEventListener('click', onClick); return el;
}
async function loadKeys() {
  const data=await call('keys');
  const root=$('keyRows'); root.replaceChildren();
  if (!data.items.length) {
    const tr=make('tr');const cell=make('td','Chưa có key');cell.colSpan=6;
    tr.appendChild(cell);root.appendChild(tr);
  }
  for (const k of data.items) {
    const tr=make('tr');
    td(tr,k.label); td(tr,'••••••'+k.key_hint);
    td(tr,k.expires_at ? k.expires_at.slice(0,10) : 'Không hết hạn');
    td(tr,k.device_count+' / '+k.max_devices);
    td(tr,k.revoked?'Đã thu hồi':'Hoạt động',k.revoked?'red':'green');
    const actions=make('td');actions.className='actions';
    actions.appendChild(button('Thiết bị','ghost',()=>doOp(()=>showDevices(k.id))));
    actions.appendChild(button('Đổi key','ghost',()=>doOp(async()=>{
      if (!confirm('Cấp key mới và vô hiệu hóa key/phiên cũ?')) return;
      const reset_devices=confirm('Xóa liên kết thiết bị cũ khi đổi key? OK: xóa, Cancel: giữ.');
      const data=await call('keys/'+k.id+'/rotate','POST',{reset_devices});
      showOnce(data.key_once);await loadKeys();
    })));
    actions.appendChild(button(k.revoked?'Khôi phục':'Thu hồi',k.revoked?'ghost':'danger',()=>doOp(async()=>{
      if (!confirm((k.revoked?'Khôi phục':'Thu hồi')+' key của '+k.label+'?')) return;
      await call('keys/'+k.id+'/'+(k.revoked?'restore':'revoke'),'POST'); await loadKeys();
    })));
    actions.appendChild(button('Xóa','danger',()=>doOp(async()=>{
      if (!confirm('XÓA VĨNH VIỄN KEY '+k.label+'?')) return;
      await call('keys/'+k.id,'DELETE'); await loadKeys();
    })));
    tr.appendChild(actions);root.appendChild(tr);
  }
}
async function showDevices(keyId) {
  const data=await call('keys/'+keyId+'/devices');
  const root=$('deviceRows');root.replaceChildren();$('devicePanel').hidden=false;
  if (!data.items.length) root.appendChild(make('p','Chưa có thiết bị kích hoạt.'));
  for (const d of data.items) {
    const line=make('div');
    line.appendChild(make('span','Thiết bị '+d.device_hint+' · gần nhất '+d.last_seen_at));
    line.appendChild(button('Gỡ thiết bị','danger',()=>doOp(async()=>{
      if (!confirm('Gỡ thiết bị này khỏi key?')) return;
      await call('keys/'+keyId+'/devices/'+d.id,'DELETE');
      await showDevices(keyId);await loadKeys();
    })));
    root.appendChild(line);
  }
}
async function loadLogs() {
  const data=await call('logs?limit=200');const root=$('logRows');root.replaceChildren();
  if (!data.items.length) {
    const tr=make('tr');const cell=make('td','Chưa có nhật ký');cell.colSpan=6;
    tr.appendChild(cell);root.appendChild(tr);
  }
  for (const k of data.items) {
    const tr=make('tr');td(tr,k.time);td(tr,k.event);
    td(tr,k.result,k.result==='allowed'?'green':'red');
    td(tr,k.ip);td(tr,k.key_id || '—');td(tr,k.device_hint || '—');root.appendChild(tr);
  }
}
function showOnce(key) {
  $('newKey').textContent=key;$('oneTime').hidden=false;
  $('oneTime').scrollIntoView({behavior:'smooth',block:'nearest'});
}
function clearSensitive() {
  adminToken='';apiOrigin='';$('adminToken').value='';
  $('oneTime').hidden=true;$('newKey').textContent='';
  $('keyRows').replaceChildren();$('logRows').replaceChildren();
  $('devicePanel').hidden=true;$('connect').disabled=false;
  $('disconnect').disabled=true;
}
async function doOp(callback) {
  try { await callback();say('Thành công · '+new Date().toLocaleTimeString('vi-VN')); }
  catch(err) { say('Lỗi: '+(err instanceof TypeError ? 'Không kết nối được server hoặc server chưa cho phép CORS từ web Admin' : err.message)); }
}
$('connect').addEventListener('click',()=>doOp(async()=>{
  const candidateOrigin=normalizeOrigin($('serverUrl').value);
  const candidateToken=$('adminToken').value.trim();
  if (!candidateToken) throw new Error('Hãy nhập Admin token');
  apiOrigin=candidateOrigin;adminToken=candidateToken;
  $('adminToken').value='';
  try { await refresh(); }
  catch(err) {clearSensitive();throw err;}
  $('connect').disabled=true;$('disconnect').disabled=false;
  $('serverState').textContent='API: '+candidateOrigin;
  say('Đã kết nối Admin · '+new Date().toLocaleTimeString('vi-VN'));
}));
$('disconnect').disabled=true;
$('disconnect').addEventListener('click',()=>{clearSensitive();say('Đã ngắt kết nối');});
$('createForm').addEventListener('submit', event=>{
  event.preventDefault();doOp(async()=>{
    const r=await call('keys','POST',{
      label:$('label').value, valid_days:Number($('days').value), max_devices:Number($('devices').value)
    });
    showOnce(r.key_once);await loadKeys();
  });
});
$('copyKey').addEventListener('click',()=>doOp(async()=>{
  await navigator.clipboard.writeText($('newKey').textContent);say('Đã sao chép key');
}));
$('refreshKeys').addEventListener('click',()=>doOp(loadKeys));
$('refreshLogs').addEventListener('click',()=>doOp(loadLogs));
$('wipeLogs').addEventListener('click',()=>doOp(async()=>{
  if (!confirm('Xóa vĩnh viễn toàn bộ lịch sử IP?')) return;
  await call('logs','DELETE');await loadLogs();
}));
