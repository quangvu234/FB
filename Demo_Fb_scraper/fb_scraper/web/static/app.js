import {element, renderPost} from './comments.js';

const paths = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 4 16 4 16 0V5M4 12v7c0 4 16 4 16 0v-7"/>',
  external: '<path d="M14 3h7v7m0-7L10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
  spark: '<path d="m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6L12 3Z"/>',
  document: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Z"/><path d="M14 3v6h6M8 13h8m-8 4h5"/>',
  comment: '<path d="M21 11a8 8 0 0 1-8 8H7l-5 3 2-6a8 8 0 1 1 17-5Z"/><path d="M8 10h8m-8 4h5"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 7"/>',
  scan: '<path d="M8 3H4a1 1 0 0 0-1 1v4m13-5h4a1 1 0 0 1 1 1v4M3 16v4a1 1 0 0 0 1 1h4m13-5v4a1 1 0 0 1-1 1h-4M2 12h20m-14 4V7h8v9"/>',
  play: '<path d="m8 5 11 7-11 7V5Z"/>', lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4"/>',
  radar: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="m12 12 7-7"/><circle cx="12" cy="12" r="1"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>', search: '<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>'
};
document.querySelectorAll('[data-icon]').forEach(node => {
  node.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[node.dataset.icon] || ''}</svg>`;
});
const $ = id => document.getElementById(id);
const format = number => new Intl.NumberFormat('vi-VN').format(number);
const statuses = {idle:'Sẵn sàng', running:'Đang thu thập', stopping:'Đang dừng', completed:'Hoàn tất', cancelled:'Đã dừng', failed:'Có lỗi'};
let token = '', busy = false, submitting = false, offset = 0, total = 0, toastTimer, searchTimer, postRequest = 0;
let lastFingerprint = '', lastHistory = '';

function showToast(message) {
  $('toast').textContent = message;
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 5000);
}
async function api(path, payload) {
  const options = {cache:'no-store'};
  if (payload !== undefined) Object.assign(options, {method:'POST', headers:{'Content-Type':'application/json', 'X-Scraper-Token':token}, body:JSON.stringify(payload)});
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Chưa thực hiện được thao tác.');
  return result;
}
function updateInput() {
  const lines = [...new Set($('sources').value.split('\n').map(line => line.trim()).filter(Boolean))];
  $('source-count').textContent = `${lines.length} nguồn`;
  const mode = document.querySelector('[name="mode"]:checked').value;
  $('source-hint').textContent = {auto:'Tự phân biệt từ khóa và URL', keyword:'Mỗi dòng là một từ khóa tìm bài', profile:'Nhập URL tài khoản cá nhân', page:'Nhập URL Trang / Fanpage Facebook', group:'Nhập URL nhóm Facebook công khai'}[mode];
  $('start-button').disabled = !token || busy || submitting || !lines.length;
}
function time(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('vi-VN', {hour:'2-digit', minute:'2-digit', day:'2-digit', month:'2-digit'});
}
function updateJob(job) {
  busy = Boolean(job && ['running','stopping'].includes(job.status));
  const status = job?.status || 'idle';
  const browserJob = job?.action === 'browser';
  const badge = $('job-badge');
  badge.className = `status-badge ${status}`;
  badge.replaceChildren(element('i'), document.createTextNode(browserJob && busy ? 'Đang mở Chrome' : statuses[status]));
  const titles = {idle:'Sẵn sàng cho lượt thu thập mới', running:'Đang thu thập bài viết…', stopping:'Đang dừng và lưu kết quả…', completed:'Lượt thu thập đã kết thúc', cancelled:'Đã dừng lượt thu thập', failed:'Lượt chạy gặp lỗi'};
  $('activity-title').textContent = browserJob ? (busy ? 'Đang mở Chrome để đăng nhập…' : status === 'completed' ? 'Chrome đã được mở' : 'Chưa mở được Chrome') : titles[status];
  const descriptions = {idle:'Nhập nguồn ở bên trái và nhấn bắt đầu. Kết quả sẽ xuất hiện ngay khi có bài được lưu.', running:'Bạn có thể theo dõi nhật ký bên dưới. Các bài đọc được sẽ được lưu trong quá trình chạy.', stopping:'Đang kết thúc thao tác và xuất dữ liệu đã có. Vui lòng chờ.', completed:'Xem kết quả đã lưu bên dưới. Nếu chưa có bài, kiểm tra nhật ký và phiên đăng nhập Facebook.', cancelled:'Những bài đã lưu vẫn còn trong kết quả. Bạn có thể bắt đầu lượt mới.', failed:'Xem nhật ký để biết nguyên nhân. Các bài đã lưu trước khi gặp lỗi vẫn được giữ.'};
  $('activity-description').textContent = browserJob && status === 'completed' ? 'Đăng nhập Facebook trong cửa sổ Chrome của project, sau đó quay lại đây để thu thập.' : descriptions[status];
  $('progress-label').textContent = job ? (browserJob ? 'Thiết lập phiên Facebook' : 'Nguồn đã xử lý') : 'Chưa có lượt chạy';
  $('progress-count').textContent = job && !browserJob ? `${job.completed} / ${job.total}` : '—';
  $('job-progress').max = Math.max(job?.total || 1, 1);
  $('job-progress').value = job?.completed || 0;
  $('current-source').textContent = job?.label || 'Bạn có thể nhập nhiều nguồn trong cùng một lượt.';
  const logs = $('job-logs');
  const nearBottom = logs.scrollHeight - logs.scrollTop - logs.clientHeight < 50;
  const logText = job?.logs?.join('\n') || 'Nhật ký sẽ xuất hiện tại đây…';
  if (logs.textContent !== logText) {
    logs.textContent = logText;
    if (nearBottom) logs.scrollTop = logs.scrollHeight;
  }
  $('log-dot').classList.toggle('live', busy);
  $('stop-button').hidden = !busy || browserJob;
  $('stop-button').disabled = status === 'stopping';
  $('open-browser').disabled = busy || submitting;
  $('open-browser-mobile').disabled = busy || submitting;
  updateInput();
}
function updateHistory(history) {
  const fingerprint = JSON.stringify(history.map(job => [job.id, job.status, job.completed]));
  if (fingerprint === lastHistory) return;
  lastHistory = fingerprint;
  const list = $('history-list');
  list.replaceChildren();
  if (!history.length) return list.append(element('span', 'history-empty', 'Chưa có lượt chạy.'));
  for (const job of history.slice(0, 6)) {
    const card = element('div', 'history-item');
    card.append(element('strong', '', job.action === 'browser' ? 'Mở Chrome' : `${job.total} nguồn`), element('span', `status-badge ${job.status}`, statuses[job.status]), element('time', '', time(job.started_at)));
    list.append(card);
  }
}
async function loadPosts() {
  const sequence = ++postRequest;
  const query = $('search-posts').value.trim();
  const result = await api(`/api/posts?q=${encodeURIComponent(query)}&offset=${offset}&limit=12`);
  if (sequence !== postRequest) return;
  total = result.total;
  if (!result.items.length && offset > 0 && total > 0) { offset = 0; return loadPosts(); }
  $('result-count').textContent = format(total);
  const list = $('post-list');
  list.replaceChildren();
  for (const post of result.items) {
    const row = element('button', 'post-row');
    row.type = 'button';
    row.dataset.postId = post.post_id;
    const author = element('div', 'author-cell');
    const name = element('div');
    name.append(element('strong', '', post.author || 'Chưa rõ tác giả'), element('small', '', post.posted_raw || time(post.collected_at)));
    author.append(element('span', 'avatar', (post.author || '?').trim().slice(0, 1).toUpperCase()), name);
    const source = post.source_label || ({profile:'Cá nhân', page:'Trang', group:'Nhóm Facebook'}[post.source_type]) || post.source || 'Facebook';
    const numbers = element('div', 'post-numbers');
    numbers.append(element('strong', '', `${post.top_comments?.length || 0} bình luận`), element('div', '', `${post.images?.length || 0} ảnh đính kèm`));
    row.append(author, element('span', 'post-excerpt', post.text || '(Bài viết có ảnh)'), element('span', 'source-chip', source), numbers);
    row.querySelector('.source-chip').title = post.source_ref || source;
    row.addEventListener('click', () => openPost(post.post_id));
    list.append(row);
  }
  $('empty-results').hidden = total > 0;
  $('empty-results').querySelector('h3').textContent = query ? 'Không tìm thấy bài viết phù hợp' : 'Chưa có bài viết nào';
  $('empty-results').querySelector('p').textContent = query ? 'Thử từ khóa khác hoặc xóa bộ lọc để xem tất cả.' : 'Thêm nguồn và bắt đầu lượt thu thập đầu tiên. Bài viết, bình luận và reply sẽ được lưu ở đây.';
  $('pagination').hidden = total === 0;
  $('page-label').textContent = `${offset + 1}–${Math.min(offset + 12, total)} / ${format(total)} bài viết`;
  $('previous-page').disabled = offset === 0;
  $('next-page').disabled = offset + 12 >= total;
}
async function openPost(identity) {
  try {
    const post = await api(`/api/posts/${encodeURIComponent(identity)}`);
    $('detail-title').textContent = post.author || 'Chi tiết bài viết';
    renderPost(post, $('post-detail'));
    if (!$('post-dialog').open) $('post-dialog').showModal();
  } catch (error) { showToast(error.message); }
}
async function poll() {
  try {
    const state = await api('/api/state');
    token = state.token;
    $('connection-error').hidden = true;
    for (const key of ['posts','comments','images']) $(`stat-${key}`).textContent = format(state.stats[key]);
    $('nav-count').textContent = format(state.stats.posts);
    $('browser-dot').classList.toggle('ready', state.browser_ready);
    $('browser-state').textContent = state.browser_ready ? 'Chrome sẵn sàng kết nối' : 'Chrome chưa được mở';
    updateJob(state.current);
    updateHistory(state.history);
    const fingerprint = JSON.stringify([state.stats, state.current?.id, state.current?.status]);
    if (fingerprint !== lastFingerprint || busy) { await loadPosts(); lastFingerprint = fingerprint; }
  } catch (error) {
    $('connection-error').hidden = false;
    token = '';
    updateInput();
  } finally { setTimeout(poll, 2000); }
}
$('collect-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || submitting || !$('collect-form').reportValidity()) return;
  submitting = true;
  $('form-error').hidden = true;
  updateInput();
  try {
    await api('/api/run', {sources:$('sources').value, mode:document.querySelector('[name="mode"]:checked').value, max_posts:Number($('max-posts').value), max_comments:Number($('max-comments').value), ocr:$('ocr').checked});
    const state = await api('/api/state');
    updateJob(state.current);
    updateHistory(state.history);
    showToast('Đã bắt đầu lượt thu thập.');
  } catch (error) { $('form-error').textContent = error.message; $('form-error').hidden = false; }
  finally { submitting = false; updateInput(); }
});
$('sources').addEventListener('input', updateInput);
document.querySelectorAll('[name="mode"]').forEach(input => input.addEventListener('change', updateInput));
async function openBrowser() {
  if (submitting || busy) return;
  submitting = true;
  $('open-browser').disabled = true;
  $('open-browser-mobile').disabled = true;
  try { await api('/api/browser', {}); updateJob((await api('/api/state')).current); showToast('Đang mở Chrome của project…'); }
  catch (error) { showToast(error.message); }
  finally { submitting = false; $('open-browser').disabled = busy; $('open-browser-mobile').disabled = busy; updateInput(); }
}
$('open-browser').addEventListener('click', openBrowser);
$('open-browser-mobile').addEventListener('click', openBrowser);
$('stop-button').addEventListener('click', async () => {
  $('stop-button').disabled = true;
  try { await api('/api/stop', {}); updateJob((await api('/api/state')).current); }
  catch (error) { $('stop-button').disabled = false; showToast(error.message); }
});
$('toggle-logs').addEventListener('click', () => {
  $('job-logs').hidden = !$('job-logs').hidden;
  $('toggle-logs').textContent = $('job-logs').hidden ? 'Mở nhật ký' : 'Thu gọn';
  $('toggle-logs').setAttribute('aria-expanded', String(!$('job-logs').hidden));
});
$('search-posts').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { offset = 0; loadPosts().catch(error => showToast(error.message)); }, 250); });
$('previous-page').addEventListener('click', () => { offset = Math.max(0, offset - 12); loadPosts().catch(error => showToast(error.message)); });
$('next-page').addEventListener('click', () => { offset += 12; loadPosts().catch(error => showToast(error.message)); });
$('close-dialog').addEventListener('click', () => $('post-dialog').close());
$('post-dialog').addEventListener('click', event => { if (event.target === $('post-dialog')) { const box = event.target.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) event.target.close(); } });
document.querySelectorAll('.nav-link').forEach(link => link.addEventListener('click', () => { document.querySelector('.nav-link.active')?.classList.remove('active'); link.classList.add('active'); }));
poll();
