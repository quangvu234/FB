export function element(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== null && text !== undefined) node.textContent = String(text);
  return node;
}

export function facebookLink(value, text, className = 'detail-link') {
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || !/(^|\.)facebook\.com$/.test(url.hostname)) return null;
    const link = element('a', className, text);
    link.href = url.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    return link;
  } catch { return null; }
}

function renderMedia(items, container) {
  if (!items?.length) return;
  const section = element('div', 'media-summary');
  section.append(element('strong', '', `Media (${items.length})`));
  for (const item of items) {
    const type = {image:'Ảnh', video:'Video', gif:'GIF'}[item.media_type] || 'Media';
    const row = element('div', 'media-item');
    const name = item.file_path?.split(/[\\/]/).pop();
    row.append(element('span', '', `${type} · ${name || 'Chưa tải về máy'}`));
    try {
      const url = new URL(item.media_url);
      if (['http:', 'https:'].includes(url.protocol)) {
        const link = element('a', 'detail-link', 'Mở media ↗');
        link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
        row.append(link);
      }
    } catch { /* Chỉ hiển thị đường dẫn đã có nếu không có URL media. */ }
    section.append(row);
    if (item.ocr_text) section.append(element('p', 'media-ocr', item.ocr_text));
  }
  container.append(section);
}

export function renderComments(comments, container) {
  const byId = new Map();
  comments.forEach((comment, index) => { if (comment.comment_id) byId.set(comment.comment_id, index); });
  const children = new Map();
  const roots = [];
  const visited = new Set();
  comments.forEach((comment, index) => {
    const parent = byId.get(comment.parent_comment_id);
    if (parent !== undefined && parent !== index) {
      if (!children.has(parent)) children.set(parent, []);
      children.get(parent).push(index);
    } else roots.push(index);
  });
  function branch(index, depth) {
    if (visited.has(index)) return;
    visited.add(index);
    const comment = comments[index];
    const card = element('article', 'comment');
    card.style.marginLeft = `${Math.min(depth, 5) * (innerWidth < 500 ? 10 : 20)}px`;
    card.dataset.commentId = comment.comment_key || comment.comment_id || '';
    if (comment.storage_id) card.dataset.storageId = String(comment.storage_id);
    if (comment.parent_comment_id) card.dataset.parentId = String(comment.parent_comment_id);
    card.dataset.depth = String(depth);
    const head = element('div', 'comment-head');
    const author = facebookLink(comment.author_url, comment.author || 'Chưa rõ người viết', 'comment-author');
    head.append(author || element('strong', '', comment.author || 'Chưa rõ người viết'));
    if (comment.posted_raw) head.append(element('span', '', comment.posted_raw));
    card.append(head, element('p', '', comment.text));
    renderMedia(comment.media, card);
    let relation = comment.is_reply === null ? 'Quan hệ chưa xác định · dữ liệu chưa có đủ metadata' : 'Bình luận gốc';
    if (comment.parent_comment_id) {
      const parent = comments[byId.get(comment.parent_comment_id)];
      relation = `↳ Trả lời bình luận #${parent?.comment_key || comment.parent_comment_id}`;
      if (!byId.has(comment.parent_comment_id)) relation += ' (chưa có trong dữ liệu)';
    } else if (comment.parent_comment_key) {
      relation = `↳ Trả lời bình luận #${comment.parent_comment_key} (chưa có trong dữ liệu)`;
    } else if (comment.is_reply) {
      const root = comment.root_comment_key || comment.root_comment_id;
      relation = root ? `↳ Reply trong luồng #${root} · chưa rõ cha trực tiếp` : '↳ Reply · chưa xác định bình luận cha';
    }
    const metadata = element('small', 'comment-relation', relation);
    const permalink = facebookLink(comment.url, 'Mở bình luận', '');
    if (permalink) metadata.append(document.createTextNode(' · '), permalink);
    card.append(metadata);
    container.append(card);
    for (const child of children.get(index) || []) branch(child, depth + 1);
    // Nhóm các reply chỉ biết gốc luồng; nhãn vẫn nói rõ chưa biết cha trực tiếp.
    if (comment.comment_id && comment.root_comment_id === comment.comment_id) {
      for (const orphan of roots) {
        if (orphan !== index && comments[orphan].root_comment_id === comment.comment_id && comments[orphan].is_reply) branch(orphan, depth + 1);
      }
    }
  }
  roots.sort((a, b) => Number(Boolean(comments[a].is_reply)) - Number(Boolean(comments[b].is_reply)));
  for (const root of roots) branch(root, 0);
  // Dữ liệu bên ngoài có thể có chu kỳ; vẫn hiển thị mỗi bản ghi đúng một lần.
  comments.forEach((_, index) => branch(index, 0));
}

export function renderPost(post, container) {
  container.replaceChildren();
  const meta = element('div', 'detail-meta');
  for (const text of [post.posted_raw || 'Chưa rõ thời gian đăng', `${post.likes ?? '—'} lượt cảm xúc`, `${post.comments ?? '—'} bình luận hiển thị`, `${post.shares ?? '—'} lượt chia sẻ`]) meta.append(element('span', '', text));
  const link = facebookLink(post.url, 'Mở bài viết trên Facebook ↗');
  if (link) meta.append(link);
  container.append(meta, element('div', 'detail-text', post.content || post.text || '(Bài viết không có nội dung chữ)'), element('p', 'detail-source', `Nguồn: ${post.source_label || post.source || 'Chưa xác định'}`));
  renderMedia(post.media, container);
  if (post.is_shared) container.append(element('p', 'detail-source', post.original_post_key ? `Bài chia sẻ từ #${post.original_post_key}` : 'Bài viết được chia sẻ'));
  let comments;
  if (post.comment_records) {
    const ids = new Map(post.comment_records.map(row => [row.comment_key, row.id]));
    comments = post.comment_records.map(row => ({...row, storage_id:row.id, comment_id:row.id,
      root_comment_id:ids.get(row.root_comment_key) || null,
      text:row.content || '', posted_raw:row.created_raw,
      is_reply:row.is_reply === null ? null : Boolean(row.is_reply)}));
  } else comments = (post.top_comments || []).map(comment => typeof comment === 'string' ? {text:comment, is_reply:null} : comment);
  const heading = element('div', 'thread-heading');
  heading.append(element('h3', '', `Bình luận & reply (${comments.length})`), element('small', '', 'Hiển thị theo bình luận cha'));
  container.append(heading);
  if (comments.length) renderComments(comments, container);
  else container.append(element('p', 'unknown-comments', 'Chưa thu thập bình luận cho bài viết này.'));
}
