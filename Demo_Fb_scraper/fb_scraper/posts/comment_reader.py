"""JavaScript đọc từng bình luận và quan hệ trả lời, không lấy lẫn DOM con."""
import json
from fb_scraper.posts.labels import COMMENT_LABEL_JS
from fb_scraper.common.content import COMMENT_AUTHOR_SOURCE
from fb_scraper.common.urls import POST_URL_JS


EXTRACT_COMMENTS_JS = r"""() => {
  const labelPattern = __COMMENT_LABEL__;
  const authorPattern = new RegExp(__AUTHOR_PATTERN__, 'i');
  const postLink = __POST_URL_PREDICATE__;
  const isComment = el => el.matches('[role="article"][aria-label]') &&
    labelPattern.test(el.getAttribute('aria-label') || '');
  const owner = node => {
    let el = node;
    while (el) {
      if (isComment(el)) return el;
      el = el.parentElement;
    }
    return null;
  };
  const articles = [...document.querySelectorAll('[role="article"][aria-label]')].filter(isComment);
  const own = (el, selector) => [...el.querySelectorAll(selector)].filter(node => owner(node) === el);
  const readBody = node => {
    let text = node.innerText?.trim() || '';
    for (const control of node.querySelectorAll('button, [role="button"], a')) {
      const label = control.innerText?.trim() || '';
      if (/^(?:Xem bớt|Ẩn bớt|See less)$/i.test(label)) {
        const index = text.lastIndexOf(label);
        if (index >= 0) text = text.slice(0, index) + text.slice(index + label.length);
      }
    }
    return text.trim();
  };
  const permalink = el => {
    const links = own(el, 'a[href*="comment_id"]');
    const parsed = links.map(link => {
      try {
        const url = new URL(link.href, location.href);
        const root = url.searchParams.get('comment_id');
        const reply = url.searchParams.get('reply_comment_id');
        if (!/(^|\.)facebook\.com$/.test(url.hostname) || !root) return null;
        const target = postLink(url.href) ? url : new URL(location.href);
        const params = new URLSearchParams();
        for (const key of ['story_fbid', 'id', 'fbid', 'v', 'comment_id', 'reply_comment_id']) {
          if (target.searchParams.has(key)) params.set(key, target.searchParams.get(key));
        }
        params.set('comment_id', root);
        if (reply) params.set('reply_comment_id', reply);
        return {id: reply || root, root, reply, rank:postLink(url.href) ? 0 : 1,
          url: postLink(target.href) ? target.origin + target.pathname + '?' + params : null,
          posted_raw: postLink(url.href) ? link.getAttribute('aria-label') || link.innerText?.trim() || null : null};
      } catch { return null; }
    }).filter(Boolean);
    parsed.sort((a, b) => a.rank - b.rank);
    return parsed.find(item => item.reply && item.rank === 0) || parsed[0] || null;
  };
  const records = new Map(articles.map(el => [el, permalink(el)]));
  return articles.map(el => {
    const link = records.get(el);
    const parent = owner(el.parentElement);
    const parentLink = parent ? records.get(parent) : null;
    const label = el.getAttribute('aria-label') || '';
    const replyLabel = /^\s*(?:Reply by|Trả lời (?:của|dưới tên))/i.test(label);
    // comment_id trong permalink của reply là gốc luồng, không chắc là cha trực tiếp.
    const isReply = Boolean(link?.reply || parent || replyLabel);
    const labelAuthor = label.match(authorPattern)?.[1]?.trim() || null;
    const profileUrl = a => {
      try {
        const url = new URL(a.href, location.href);
        if (!/(^|\.)facebook\.com$/.test(url.hostname)) return null;
        const path = url.pathname;
        if (/^\/groups\/[^/]+\/user\/[^/]+\/?$/.test(path)) return url.origin + path;
        if (path === '/profile.php' && url.searchParams.get('id')) return url.origin + path + '?id=' + url.searchParams.get('id');
        if (/^\/(?:people|pages)\/[^/]+\/\d+\/?$/.test(path)) return url.origin + path;
        if (/^\/[\w.\-]+\/?$/.test(path) && !/^\/(?:photo|photos|watch|reel|reels|stories|groups|search|share|login|permalink.php|story.php)\/?$/i.test(path)) return url.origin + path;
      } catch { /* Không suy ra tác giả từ link ngoài Facebook. */ }
      return null;
    };
    const profileLinks = own(el, 'a[href]').filter(a => profileUrl(a));
    const authorLink = profileLinks.find(a => labelAuthor && a.innerText?.trim() === labelAuthor) ||
      profileLinks.find(a => a.matches('h3 a, h4 a, strong a')) ||
      profileLinks.find(a => !a.closest('[data-comment-text], [data-ad-preview="message"], [data-ad-comet-preview="message"]'));
    const author = labelAuthor || authorLink?.innerText?.trim() || null;
    const bodies = own(el, '[data-ad-comet-preview="message"], [data-ad-preview="message"], [data-comment-text], div[dir="auto"], span[dir="auto"]')
      .filter(node => !node.contains(authorLink) && !node.closest('a, h3, h4, strong, [role="button"]') &&
        (!author || node.innerText?.trim() !== author) &&
        ![...node.querySelectorAll('[role="article"][aria-label]')].some(isComment));
    const outerBodies = bodies.filter(node => !bodies.some(other => other !== node && other.contains(node)));
    let text = outerBodies.map(readBody).filter(Boolean).join('\n');
    if (!text) {
      const clone = el.cloneNode(true);
      const cloneAuthor = [...clone.querySelectorAll('a')]
        .find(a => authorLink && a.getAttribute('href') === authorLink.getAttribute('href'));
      cloneAuthor?.remove();
      clone.querySelectorAll('[role="article"][aria-label], [role="button"], button, h3, h4, a[href*="comment_id"]')
        .forEach(node => node.remove());
      text = (clone.innerText || clone.textContent || '').trim();
    }
    const authorUrl = authorLink ? profileUrl(authorLink) : null;
    // Chỉ gán cha trực tiếp khi có phần tử bình luận cha trong DOM.
    const parentId = parentLink?.id || null;
    let rootId = link?.reply ? link.root : (isReply ? null : link?.id || null);
    if (!rootId && parent) {
      let ancestor = parent;
      while (ancestor) {
        const ancestorLink = records.get(ancestor);
        if (ancestorLink) rootId = ancestorLink.root;
        ancestor = owner(ancestor.parentElement);
      }
    }
    return {id: link?.id || null, label, text,
      parent_comment_id: parentId, root_comment_id: rootId,
      is_reply: isReply, author,
      author_url: authorUrl, url: link?.url || null, posted_raw: link?.posted_raw || null,
      media: own(el, 'img[src], video').filter(node => !authorLink?.contains(node))
        .map((node, position) => ({media_url:node.currentSrc || node.src || node.querySelector('source')?.src || '',
          media_type:node.tagName === 'VIDEO' ? 'video' : /\.gif(?:\?|$)/i.test(node.src) ? 'gif' : 'image',
          position, width:node.naturalWidth || node.videoWidth || 0, height:node.naturalHeight || node.videoHeight || 0}))
        .filter(item => /^https?:/.test(item.media_url) && (item.media_type === 'video' || (item.width >= 80 && item.height >= 80)))};
  });
}""".replace("__COMMENT_LABEL__", COMMENT_LABEL_JS).replace(
    "__AUTHOR_PATTERN__", json.dumps(COMMENT_AUTHOR_SOURCE),
).replace("__POST_URL_PREDICATE__", POST_URL_JS)
