const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrfToken,
    },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || 'Request failed.');
  }
  return data;
}

function wireReactionButtons() {
  document.querySelectorAll('.reaction-button[data-target-id]').forEach((button) => {
    button.addEventListener('click', async () => {
      const targetId = button.dataset.targetId;
      const targetType = button.dataset.targetType;
      const voteType = button.dataset.voteType;
      if (!targetId || !targetType || !voteType) {
        return;
      }
      button.classList.add('is-loading');
      try {
        const data = await postJson('/api/reactions', {
          target_id: targetId,
          target_type: targetType,
          vote_type: voteType,
        });
        document.querySelectorAll(`.reaction-button[data-target-id="${targetId}"][data-target-type="${targetType}"] .score-label`).forEach((node) => {
          node.textContent = String(data.score);
        });
      } catch (error) {
        window.alert(error.message);
      } finally {
        button.classList.remove('is-loading');
      }
    });
  });
}

function wireShareButtons() {
  document.querySelectorAll('.share-trigger').forEach((button) => {
    button.addEventListener('click', async () => {
      const shareUrl = button.dataset.shareUrl || window.location.href;
      const title = button.dataset.shareTitle || document.title;
      const postId = button.dataset.postId;

      if (postId) {
        postJson(`/api/posts/${postId}/share`, {}).catch(() => {});
      }

      if (navigator.share) {
        try {
          await navigator.share({ title, url: shareUrl });
          return;
        } catch (_) {
        }
      }
      try {
        await navigator.clipboard.writeText(shareUrl);
        button.textContent = 'Link copied';
        window.setTimeout(() => {
          button.textContent = 'Share';
        }, 1200);
      } catch (_) {
        window.prompt('Copy this link:', shareUrl);
      }
    });
  });
}

function renderMessage(message, ownUserId) {
  const article = document.createElement('article');
  article.className = 'chat-message';
  if (ownUserId && message.author_auth_user_id === ownUserId) {
    article.classList.add('is-own');
  }
  article.innerHTML = `<strong>${message.author_display_name || 'Member'}</strong><p>${message.body || ''}</p>`;
  return article;
}

function wireChatShells() {
  document.querySelectorAll('[data-chat-endpoint][data-chat-post-endpoint]').forEach((shell) => {
    const endpoint = shell.dataset.chatEndpoint;
    const postEndpoint = shell.dataset.chatPostEndpoint;
    const form = shell.querySelector('[data-chat-form]');
    const stream = shell.querySelector('#chatStream');
    const ownUserId = document.querySelector('.account-chip .account-name') ? document.body.dataset.userId : null;
    if (!endpoint || !postEndpoint || !form || !stream) {
      return;
    }

    let pollingHandle = null;

    const syncMessages = async () => {
      const response = await fetch(endpoint, { headers: { 'Accept': 'application/json' } });
      const data = await response.json().catch(() => ({ messages: [] }));
      if (!response.ok) {
        return;
      }
      stream.innerHTML = '';
      (data.messages || []).forEach((message) => {
        stream.appendChild(renderMessage(message, ownUserId));
      });
      stream.scrollTop = stream.scrollHeight;
    };

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const field = form.querySelector('textarea[name="body"]');
      if (!field || !field.value.trim()) {
        return;
      }
      try {
        await postJson(postEndpoint, { body: field.value.trim() });
        field.value = '';
        await syncMessages();
      } catch (error) {
        window.alert(error.message);
      }
    });

    syncMessages();
    pollingHandle = window.setInterval(syncMessages, 4000);
    window.addEventListener('beforeunload', () => {
      if (pollingHandle) {
        window.clearInterval(pollingHandle);
      }
    }, { once: true });
  });
}

function placeCaretAtEditorEnd(editor) {
  if (!editor) {
    return null;
  }
  const selection = window.getSelection();
  if (!selection) {
    return null;
  }
  const range = document.createRange();
  range.selectNodeContents(editor);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
  return range;
}

function insertHtmlAtCursor(editor, html) {
  if (!editor) {
    return null;
  }

  let selection = window.getSelection();
  let range = null;
  if (selection && selection.rangeCount) {
    const candidateRange = selection.getRangeAt(0);
    if (editor.contains(candidateRange.commonAncestorContainer)) {
      range = candidateRange;
    }
  }

  if (!range) {
    editor.focus();
    range = placeCaretAtEditorEnd(editor);
  }

  if (!range) {
    return null;
  }

  range.deleteContents();
  const template = document.createElement('template');
  template.innerHTML = html;
  const fragment = template.content;
  const insertedNodes = Array.from(fragment.childNodes);
  const lastInsertedNode = insertedNodes.at(-1) || null;
  range.insertNode(fragment);

  const nextRange = document.createRange();
  if (lastInsertedNode && lastInsertedNode.parentNode) {
    nextRange.setStartAfter(lastInsertedNode);
  } else {
    nextRange.selectNodeContents(editor);
  }
  nextRange.collapse(true);

  selection = window.getSelection();
  if (selection) {
    selection.removeAllRanges();
    selection.addRange(nextRange);
  }

  return lastInsertedNode;
}

function parseVideoEmbedUrl(rawUrl) {
  let parsed;
  try {
    parsed = new URL((rawUrl || '').trim());
  } catch (_) {
    return null;
  }
  const host = (parsed.hostname || '').replace(/^www\./, '').toLowerCase();
  const path = parsed.pathname || '';
  if (host === 'youtube.com' || host === 'm.youtube.com') {
    const videoId = parsed.searchParams.get('v');
    if (videoId) {
      return `https://www.youtube.com/embed/${videoId}`;
    }
    if (path.startsWith('/embed/')) {
      const embedId = path.split('/').filter(Boolean)[1];
      return embedId ? `https://www.youtube.com/embed/${embedId}` : null;
    }
    if (path.startsWith('/shorts/')) {
      const shortId = path.split('/').filter(Boolean)[1];
      return shortId ? `https://www.youtube.com/embed/${shortId}` : null;
    }
  }
  if (host === 'youtu.be') {
    const videoId = path.replace(/^\//, '');
    return videoId ? `https://www.youtube.com/embed/${videoId}` : null;
  }
  if (host === 'vimeo.com') {
    const videoId = path.replace(/^\//, '');
    return videoId ? `https://player.vimeo.com/video/${videoId}` : null;
  }
  if (host === 'player.vimeo.com' && path.startsWith('/video/')) {
    const videoId = path.split('/').filter(Boolean)[1];
    return videoId ? `https://player.vimeo.com/video/${videoId}` : null;
  }
  if (host === 'loom.com' && path.startsWith('/share/')) {
    const parts = path.split('/').filter(Boolean);
    const videoId = parts[1];
    return videoId ? `https://www.loom.com/embed/${videoId}` : null;
  }
  if (host === 'loom.com' && path.startsWith('/embed/')) {
    const parts = path.split('/').filter(Boolean);
    const videoId = parts[1];
    return videoId ? `https://www.loom.com/embed/${videoId}` : null;
  }
  return null;
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function normalizeMarkupColor(rawColor) {
  const value = String(rawColor || '').trim().toLowerCase();
  if (/^#[0-9a-f]{3}([0-9a-f]{3})?$/.test(value)) {
    return value;
  }
  const rgbMatch = value.match(/^rgba?\((\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3})(?:,\s*[0-9.]+)?\)$/i);
  if (rgbMatch) {
    const parts = [rgbMatch[1], rgbMatch[2], rgbMatch[3]].map((part) => {
      const bounded = Math.max(0, Math.min(255, Number.parseInt(part, 10) || 0));
      return bounded.toString(16).padStart(2, '0');
    });
    return `#${parts.join('')}`;
  }
  if (/^[a-z]{3,20}$/.test(value)) {
    return value;
  }
  return '';
}

function normalizeMarkupFont(rawFont) {
  const cleaned = String(rawFont || '').replaceAll('"', '').replaceAll("'", '').split(',')[0].trim();
  const allowedFonts = ['IBM Plex Sans', 'Space Grotesk', 'Merriweather', 'Georgia', 'Courier New'];
  const match = allowedFonts.find((font) => font.toLowerCase() === cleaned.toLowerCase());
  return match || '';
}

function renderInlineMarkup(text) {
  let html = escapeHtml(text);
  for (let index = 0; index < 6; index += 1) {
    const before = html;
    html = html.replace(/\[b\](.*?)\[\/b\]/gi, '<strong>$1</strong>');
    html = html.replace(/\[i\](.*?)\[\/i\]/gi, '<em>$1</em>');
    html = html.replace(/\[u\](.*?)\[\/u\]/gi, '<u>$1</u>');
    html = html.replace(/\[s\](.*?)\[\/s\]/gi, '<s>$1</s>');
    html = html.replace(/\[size=(\d{1,2})\](.*?)\[\/size\]/gi, (_, sizeRaw, content) => {
      const size = Math.max(12, Math.min(48, Number(sizeRaw || 16)));
      return `<span style="font-size:${size}px">${content}</span>`;
    });
    html = html.replace(/\[color=([^\]]+)\](.*?)\[\/color\]/gi, (_, colorRaw, content) => {
      const color = normalizeMarkupColor(colorRaw);
      return color ? `<span style="color:${color}">${content}</span>` : content;
    });
    html = html.replace(/\[font=([^\]]+)\](.*?)\[\/font\]/gi, (_, fontRaw, content) => {
      const font = normalizeMarkupFont(fontRaw);
      return font ? `<span style="font-family:${escapeHtml(font)}">${content}</span>` : content;
    });
    html = html.replace(/\[link=(https?:\/\/[^\]\s]+)\](.*?)\[\/link\]/gi, (_, href, content) => {
      return `<a href="${href}" target="_blank" rel="noopener noreferrer">${content}</a>`;
    });
    if (html === before) {
      break;
    }
  }
  return html;
}

function buildReviewHtml(bodyText, imageFiles) {
  const lines = String(bodyText || '').replaceAll('\r\n', '\n').split('\n');
  let imageIndex = 0;
  return lines.map((line) => {
    const trimmed = line.trim();
    if (!trimmed) {
      return '<br>';
    }
    if (/^\[\[image\]\]$/i.test(trimmed)) {
      const file = imageFiles[imageIndex];
      imageIndex += 1;
      if (!file) {
        return '';
      }
      const url = URL.createObjectURL(file);
      return `<figure class="inline-media"><img src="${url}" alt="Embedded post image preview"></figure>`;
    }
    const imageUrlMatch = trimmed.match(/^\[image=(https?:\/\/[^\]]+)\]$/i);
    if (imageUrlMatch) {
      return `<figure class="inline-media"><img src="${escapeHtml(imageUrlMatch[1])}" alt="Embedded post image preview"></figure>`;
    }
    const embedUrl = parseVideoEmbedUrl(trimmed);
    if (embedUrl) {
      return `<div class="video-frame inline-video"><iframe src="${escapeHtml(embedUrl)}" title="Embedded post video preview" loading="lazy" allowfullscreen></iframe></div>`;
    }
    return `<p>${renderInlineMarkup(line)}</p>`;
  }).join('');
}

function htmlNodeToMarkup(node) {
  if (node.nodeType === Node.TEXT_NODE) {
    return (node.nodeValue || '').replace(/\u200b/g, '');
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return '';
  }
  const element = node;
  const tag = element.tagName.toLowerCase();
  const inner = Array.from(element.childNodes).map(htmlNodeToMarkup).join('');
  if (tag === 'strong' || tag === 'b') {
    return `[b]${inner}[/b]`;
  }
  if (tag === 'em' || tag === 'i') {
    return `[i]${inner}[/i]`;
  }
  if (tag === 'u') {
    return `[u]${inner}[/u]`;
  }
  if (tag === 's' || tag === 'strike' || tag === 'del') {
    return `[s]${inner}[/s]`;
  }
  if (tag === 'a') {
    const href = element.getAttribute('href') || '';
    if (/^https?:\/\//i.test(href)) {
      return `[link=${href}]${inner || href}[/link]`;
    }
    return inner;
  }
  if (tag === 'button' && element.matches('[data-inline-image-remove]')) {
    return '';
  }
  if (tag === 'figure' && element.matches('figure.inline-media')) {
    const image = element.querySelector('img');
    if (!image) {
      return '';
    }
    if (image.dataset.uploadImage === '1') {
      return '\n[[image]]\n';
    }
    const src = image.getAttribute('src') || '';
    if (/^https?:\/\//i.test(src)) {
      return `\n[image=${src}]\n`;
    }
    return '';
  }
  if (tag === 'iframe' && element.closest('div.video-frame')) {
    const src = element.getAttribute('src') || '';
    return src ? `\n${src}\n` : '';
  }
  if (tag === 'font') {
    let output = inner;
    const face = normalizeMarkupFont(element.getAttribute('face') || '');
    const color = normalizeMarkupColor(element.getAttribute('color') || '');
    if (face) {
      output = `[font=${face}]${output}[/font]`;
    }
    if (color) {
      output = `[color=${color}]${output}[/color]`;
    }
    return output;
  }
  if (tag === 'span') {
    let output = inner;
    const size = Number.parseInt((element.style.fontSize || '').replace('px', ''), 10);
    const color = normalizeMarkupColor(element.style.color || '');
    const font = normalizeMarkupFont(element.style.fontFamily || '');
    const fontWeight = String(element.style.fontWeight || '').toLowerCase();
    const fontStyle = String(element.style.fontStyle || '').toLowerCase();
    const textDecoration = String(element.style.textDecoration || '').toLowerCase();
    const isBold = fontWeight === 'bold' || Number.parseInt(fontWeight, 10) >= 600;
    const isItalic = fontStyle === 'italic' || fontStyle === 'oblique';
    const isUnderline = textDecoration.includes('underline');
    const isStrike = textDecoration.includes('line-through');
    if (Number.isFinite(size) && size > 0) {
      output = `[size=${size}]${output}[/size]`;
    }
    if (font) {
      output = `[font=${font}]${output}[/font]`;
    }
    if (color) {
      output = `[color=${color}]${output}[/color]`;
    }
    if (isStrike) {
      output = `[s]${output}[/s]`;
    }
    if (isUnderline) {
      output = `[u]${output}[/u]`;
    }
    if (isItalic) {
      output = `[i]${output}[/i]`;
    }
    if (isBold) {
      output = `[b]${output}[/b]`;
    }
    return output;
  }
  if (tag === 'br') {
    return '\n';
  }
  return inner;
}

function editorToMarkup(editor) {
  const lines = [];
  const blockTags = new Set(['p', 'div', 'li', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'section', 'article']);
  const pushMarkupLines = (value, preserveEmpty = false) => {
    String(value || '').replaceAll('\r\n', '\n').split('\n').forEach((part) => {
      const cleaned = part.replace(/\u200b/g, '').replace(/\u00a0/g, ' ');
      const trimmed = cleaned.trim();
      if (trimmed || preserveEmpty) {
        lines.push(trimmed);
      }
    });
  };

  Array.from(editor.childNodes).forEach((node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = (node.nodeValue || '').replace(/\u200b/g, '').replace(/\u00a0/g, ' ').trim();
      if (text) {
        lines.push(text);
      }
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) {
      return;
    }
    const element = node;
    const image = element.matches('figure.inline-media') ? element.querySelector('img') : null;
    if (image) {
      if (image.dataset.uploadImage === '1') {
        lines.push('[[image]]');
      } else {
        const src = image.getAttribute('src') || '';
        if (/^https?:\/\//i.test(src)) {
          lines.push(`[image=${src}]`);
        }
      }
      return;
    }
    const iframe = element.matches('div.video-frame') ? element.querySelector('iframe') : null;
    if (iframe) {
      const src = iframe.getAttribute('src') || '';
      if (src) {
        lines.push(src);
      }
      return;
    }
    const tag = element.tagName.toLowerCase();
    if (tag === 'br') {
      lines.push('');
      return;
    }
    const textMarkup = htmlNodeToMarkup(element);
    pushMarkupLines(textMarkup, blockTags.has(tag));
  });

  while (lines.length && !lines[0]) {
    lines.shift();
  }
  while (lines.length && !lines[lines.length - 1]) {
    lines.pop();
  }
  return lines.join('\n');
}

function syncEditorToTextarea(editor, bodyField) {
  if (!editor || !bodyField) {
    return;
  }
  bodyField.value = editorToMarkup(editor);
}

function applyToolbarFormat(editor, format) {
  if (!editor || !format) {
    return;
  }

  const applyStyledSpanAtSelection = (styleName, styleValue) => {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount) {
      return;
    }
    const range = selection.getRangeAt(0);
    if (selection.isCollapsed) {
      const span = document.createElement('span');
      span.style[styleName] = styleValue;
      const textNode = document.createTextNode('\u200b');
      span.appendChild(textNode);
      range.insertNode(span);
      const nextRange = document.createRange();
      nextRange.setStart(textNode, 1);
      nextRange.collapse(true);
      selection.removeAllRanges();
      selection.addRange(nextRange);
      return;
    }
    const span = document.createElement('span');
    span.style[styleName] = styleValue;
    try {
      range.surroundContents(span);
    } catch (_) {
      const content = range.extractContents();
      span.appendChild(content);
      range.insertNode(span);
    }
  };

  editor.focus();
  if (format === 'b') {
    document.execCommand('bold');
    return;
  }
  if (format === 'i') {
    document.execCommand('italic');
    return;
  }
  if (format === 'u') {
    document.execCommand('underline');
    return;
  }
  if (format === 's') {
    document.execCommand('strikeThrough');
    return;
  }
  if (format === 'link') {
    const href = window.prompt('Link URL (https://...)', 'https://');
    if (!href || !/^https?:\/\//i.test(href)) {
      return;
    }
    document.execCommand('createLink', false, href);
    return;
  }
  if (format === 'clear') {
    document.execCommand('removeFormat');
    document.execCommand('unlink');
    return;
  }
  if (format.startsWith('font:')) {
    const font = normalizeMarkupFont(format.slice(5));
    if (!font) {
      return;
    }
    applyStyledSpanAtSelection('fontFamily', font);
    return;
  }
  if (format.startsWith('color:')) {
    const color = normalizeMarkupColor(format.slice(6));
    if (!color) {
      return;
    }
    applyStyledSpanAtSelection('color', color);
    return;
  }
  if (format.startsWith('size:')) {
    const size = Math.max(12, Math.min(48, Number.parseInt(format.slice(5), 10) || 16));
    applyStyledSpanAtSelection('fontSize', `${size}px`);
  }
}

function buildComposerToolbarHtml(includeSizeControl) {
  const sizeControl = includeSizeControl
    ? `<select class="composer-toolbar-select" data-format-size aria-label="Text size">
        <option value="">12</option>
        <option value="12">12</option>
        <option value="14">14</option>
        <option value="16">16</option>
        <option value="18">18</option>
        <option value="22">22</option>
        <option value="28">28</option>
        <option value="34">34</option>
      </select>`
    : '';

  return `
    <div class="composer-toolbar-row">
      ${sizeControl}
      <button type="button" class="ghost-button toolbar-icon-button" data-format="clear" title="Clear formatting">Tx</button>
    </div>
    <div class="composer-toolbar-row">
      <button type="button" class="ghost-button toolbar-icon-button" data-format="b" title="Bold"><strong>B</strong></button>
      <button type="button" class="ghost-button toolbar-icon-button is-italic" data-format="i" title="Italic">I</button>
      <button type="button" class="ghost-button toolbar-icon-button is-underlined" data-format="u" title="Underline">U</button>
      <button type="button" class="ghost-button toolbar-icon-button is-strike" data-format="s" title="Strikethrough">S</button>
      <div class="composer-toolbar-separator" aria-hidden="true"></div>
      <button type="button" class="ghost-button toolbar-icon-button" data-format="link" title="Insert link">&#128279;</button>
    </div>
  `;
}

function getSelectionAnchorElement(editor) {
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount) {
    return null;
  }
  const anchorNode = selection.anchorNode;
  if (!anchorNode || !editor.contains(anchorNode)) {
    return null;
  }
  return anchorNode.nodeType === Node.ELEMENT_NODE ? anchorNode : anchorNode.parentElement;
}

function closestWithinEditor(startNode, selector, editor) {
  let node = startNode instanceof Element ? startNode : startNode?.parentElement;
  while (node && node !== editor) {
    if (node.matches(selector)) {
      return node;
    }
    node = node.parentElement;
  }
  return null;
}

function isCommandActive(commandName, fallback) {
  try {
    return document.queryCommandState(commandName);
  } catch (_) {
    return fallback;
  }
}

function updateToolbarState(editor, toolbar) {
  if (!editor || !toolbar) {
    return;
  }

  const anchorElement = getSelectionAnchorElement(editor);
  const buttons = {
    b: toolbar.querySelector('button[data-format="b"]'),
    i: toolbar.querySelector('button[data-format="i"]'),
    u: toolbar.querySelector('button[data-format="u"]'),
    s: toolbar.querySelector('button[data-format="s"]'),
    link: toolbar.querySelector('button[data-format="link"]'),
  };

  Object.values(buttons).forEach((button) => {
    button?.classList.remove('is-active');
  });

  if (!anchorElement) {
    return;
  }

  const computed = window.getComputedStyle(anchorElement);
  const weight = Number.parseInt(String(computed.fontWeight || '400'), 10) || 400;
  const textDecoration = String(computed.textDecorationLine || computed.textDecoration || '').toLowerCase();

  const boldActive = isCommandActive('bold', weight >= 600);
  const italicActive = isCommandActive('italic', String(computed.fontStyle || '').toLowerCase().includes('italic'));
  const underlineActive = isCommandActive('underline', textDecoration.includes('underline'));
  const strikeActive = isCommandActive('strikeThrough', textDecoration.includes('line-through'));
  const linkActive = !!closestWithinEditor(anchorElement, 'a', editor);

  buttons.b?.classList.toggle('is-active', boldActive);
  buttons.i?.classList.toggle('is-active', italicActive);
  buttons.u?.classList.toggle('is-active', underlineActive);
  buttons.s?.classList.toggle('is-active', strikeActive);
  buttons.link?.classList.toggle('is-active', linkActive);

  const sizeSelect = toolbar.querySelector('[data-format-size]');
  if (sizeSelect) {
    const rawSize = Number.parseInt(String(computed.fontSize || '').replace('px', ''), 10);
    const normalized = Number.isFinite(rawSize) ? String(rawSize) : '12';
    const hasOption = Array.from(sizeSelect.options).some((option) => option.value === normalized);
    sizeSelect.value = hasOption ? normalized : '12';
  }

}

function wireRichComposer() {
  document.querySelectorAll('form[data-rich-composer="1"]').forEach((form) => {
    const bodyField = form.querySelector('textarea[name="body"]');
    const editor = form.querySelector('[data-rich-editor]');
    const titleField = form.querySelector('input[name="title"]');
    const imagesInput = form.querySelector('input[type="file"][name="images"]');
    const reviewButton = form.querySelector('[data-review-post]');
    const reviewPanel = form.querySelector('[data-review-panel]');
    const reviewTitle = form.querySelector('[data-review-title]');
    const reviewBody = form.querySelector('[data-review-body]');
    const closeReviewButton = form.querySelector('[data-close-review]');
    const saveDraftButton = form.querySelector('[data-save-draft]');
    const draftStatus = document.getElementById('draftStatus');
    const draftKey = form.dataset.draftKey || null;
    const toolbar = form.querySelector('[data-composer-toolbar]');
    const isFormattingSurface = (node) => {
      return node instanceof Element && !!node.closest('[data-rich-editor], [data-composer-toolbar]');
    };
    const setEditorActive = (active) => {
      form.classList.toggle('is-editor-active', !!active);
    };
    let lastSelectionRange = null;
    let toolbarFocusIntentAt = 0;
    let draggedInlineMedia = null;
    const hasStoredTextSelection = () => Boolean(lastSelectionRange && !lastSelectionRange.collapsed);

    const restoreStoredTextSelection = () => {
      if (hasStoredTextSelection()) {
        restoreEditorSelection();
      }
    };

    const rememberEditorSelection = (preferNonCollapsed = false) => {
      const selection = window.getSelection();
      if (!selection || !selection.rangeCount) {
        return;
      }
      const range = selection.getRangeAt(0);
      if (!editor.contains(range.commonAncestorContainer)) {
        return;
      }
      if (preferNonCollapsed && range.collapsed && lastSelectionRange && !lastSelectionRange.collapsed) {
        return;
      }
      lastSelectionRange = range.cloneRange();
    };

    const restoreEditorSelection = () => {
      if (!lastSelectionRange) {
        return;
      }
      const selection = window.getSelection();
      if (!selection) {
        return;
      }
      selection.removeAllRanges();
      selection.addRange(lastSelectionRange);
    };

    const refocusEditor = (restoreSelection = false) => {
      window.requestAnimationFrame(() => {
        editor.focus();
        if (restoreSelection) {
          restoreEditorSelection();
        }
      });
    };

    const clearInlineMediaSelection = () => {
      editor.querySelectorAll('figure.inline-media.is-selected').forEach((node) => {
        node.classList.remove('is-selected');
      });
    };

    const selectInlineMedia = (figure) => {
      clearInlineMediaSelection();
      if (!figure || !editor.contains(figure)) {
        return;
      }
      figure.classList.add('is-selected');
      const selection = window.getSelection();
      selection?.removeAllRanges();
    };

    const hydrateInlineMediaBlocks = () => {
      editor.querySelectorAll('figure.inline-media').forEach((figure) => {
        figure.classList.add('is-editor-image');
        figure.setAttribute('draggable', 'true');
        if (figure.dataset.editorReady === '1') {
          return;
        }
        figure.dataset.editorReady = '1';
        if (!figure.querySelector('[data-inline-image-remove]')) {
          const removeButton = document.createElement('button');
          removeButton.type = 'button';
          removeButton.className = 'inline-media-remove';
          removeButton.setAttribute('data-inline-image-remove', '1');
          removeButton.setAttribute('title', 'Remove image');
          removeButton.setAttribute('aria-label', 'Remove image');
          removeButton.setAttribute('contenteditable', 'false');
          removeButton.textContent = 'Remove';
          figure.appendChild(removeButton);
        }
      });
    };

    const removeInlineMedia = (figure) => {
      if (!figure || !editor.contains(figure)) {
        return;
      }
      figure.remove();
      clearInlineMediaSelection();
      editor.focus();
      rememberEditorSelection();
      syncEditorToTextarea(editor, bodyField);
      updateToolbarState(editor, toolbar);
    };

    if (!bodyField || !imagesInput || !editor) {
      return;
    }

    // Remove stale helper copy in comment forms if an older template is cached.
    if (!titleField) {
      form.querySelectorAll('.helper-note').forEach((note) => {
        if ((note.textContent || '').includes('parent_comment_id')) {
          note.remove();
        }
      });
    }

    if (toolbar) {
      toolbar.innerHTML = buildComposerToolbarHtml(Boolean(titleField));
    }

    syncEditorToTextarea(editor, bodyField);
    hydrateInlineMediaBlocks();
    editor.addEventListener('pointerdown', () => {
      setEditorActive(true);
    });
    editor.addEventListener('click', () => {
      editor.focus();
      rememberEditorSelection();
    });
    editor.addEventListener('keyup', rememberEditorSelection);
    editor.addEventListener('mouseup', rememberEditorSelection);
    editor.addEventListener('focus', rememberEditorSelection);
    editor.addEventListener('keyup', () => updateToolbarState(editor, toolbar));
    editor.addEventListener('mouseup', () => updateToolbarState(editor, toolbar));
    editor.addEventListener('focus', () => updateToolbarState(editor, toolbar));
    editor.addEventListener('dragstart', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      const figure = target.closest('figure.inline-media');
      if (!figure || !editor.contains(figure)) {
        return;
      }
      draggedInlineMedia = figure;
      figure.classList.add('is-dragging');
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', 'inline-media');
      }
      selectInlineMedia(figure);
    });
    editor.addEventListener('dragover', (event) => {
      if (!draggedInlineMedia) {
        return;
      }
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      const dropFigure = target.closest('figure.inline-media');
      if (!dropFigure || dropFigure === draggedInlineMedia || !editor.contains(dropFigure)) {
        return;
      }
      event.preventDefault();
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = 'move';
      }
    });
    editor.addEventListener('drop', (event) => {
      if (!draggedInlineMedia) {
        return;
      }
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      const dropFigure = target.closest('figure.inline-media');
      if (!dropFigure || dropFigure === draggedInlineMedia || !editor.contains(dropFigure)) {
        return;
      }
      event.preventDefault();
      const rect = dropFigure.getBoundingClientRect();
      const insertAfter = event.clientY > (rect.top + (rect.height / 2));
      if (insertAfter) {
        dropFigure.parentNode?.insertBefore(draggedInlineMedia, dropFigure.nextSibling);
      } else {
        dropFigure.parentNode?.insertBefore(draggedInlineMedia, dropFigure);
      }
      draggedInlineMedia.classList.remove('is-dragging');
      selectInlineMedia(draggedInlineMedia);
      draggedInlineMedia = null;
      syncEditorToTextarea(editor, bodyField);
      updateToolbarState(editor, toolbar);
    });
    editor.addEventListener('dragend', () => {
      if (draggedInlineMedia) {
        draggedInlineMedia.classList.remove('is-dragging');
      }
      draggedInlineMedia = null;
    });
    editor.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      const removeButton = target.closest('[data-inline-image-remove]');
      if (removeButton) {
        const figure = removeButton.closest('figure.inline-media');
        event.preventDefault();
        removeInlineMedia(figure);
        return;
      }
      const figure = target.closest('figure.inline-media');
      if (figure && editor.contains(figure)) {
        event.preventDefault();
        selectInlineMedia(figure);
        return;
      }
      clearInlineMediaSelection();
    });
    editor.addEventListener('keydown', (event) => {
      if (event.key !== 'Delete' && event.key !== 'Backspace') {
        return;
      }
      const selectedFigure = editor.querySelector('figure.inline-media.is-selected');
      if (!(selectedFigure instanceof HTMLElement)) {
        return;
      }
      event.preventDefault();
      removeInlineMedia(selectedFigure);
    });

    // ── Draft save / restore (localStorage) ──────────────────────────────

    if (draftKey) {
      const loadDraft = () => {
        try { return JSON.parse(localStorage.getItem(draftKey) || 'null'); } catch { return null; }
      };
      const saveDraft = () => {
        syncEditorToTextarea(editor, bodyField);
        const draft = { title: titleField?.value || '', body: bodyField.value, savedAt: Date.now() };
        localStorage.setItem(draftKey, JSON.stringify(draft));
        return draft;
      };
      const clearDraft = () => localStorage.removeItem(draftKey);
      const setStatus = (msg) => { if (draftStatus) draftStatus.textContent = msg; };

      // Offer to restore on page load
      const existing = loadDraft();
      if (existing && (existing.title || existing.body)) {
        const d = new Date(existing.savedAt);
        const label = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
          + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
        const banner = document.createElement('div');
        banner.className = 'flash flash-info draft-restore-banner';
        banner.innerHTML = `Unsaved draft from ${label}. `
          + `<button type="button" class="inline-link" data-restore-draft>Restore</button>`
          + ` · <button type="button" class="inline-link" data-discard-draft>Discard</button>`;
        form.prepend(banner);
        banner.querySelector('[data-restore-draft]').addEventListener('click', () => {
          if (titleField) titleField.value = existing.title || '';
          bodyField.value = existing.body || '';
          editor.innerHTML = buildReviewHtml(bodyField.value, []);
          hydrateInlineMediaBlocks();
          banner.remove();
        });
        banner.querySelector('[data-discard-draft]').addEventListener('click', () => {
          clearDraft();
          banner.remove();
        });
      }

      // Auto-save 5 seconds after last keystroke
      let autoTimer = null;
      const scheduleAutoSave = () => {
        syncEditorToTextarea(editor, bodyField);
        clearTimeout(autoTimer);
        autoTimer = setTimeout(() => {
          if (bodyField.value.trim() || titleField?.value.trim()) {
            const d = saveDraft();
            setStatus(`Auto-saved at ${new Date(d.savedAt).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`);
          }
        }, 5000);
      };
      editor.addEventListener('input', scheduleAutoSave);
      titleField?.addEventListener('input', scheduleAutoSave);

      // Explicit save draft button
      saveDraftButton?.addEventListener('click', () => {
        const d = saveDraft();
        setStatus(`Draft saved at ${new Date(d.savedAt).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`);
      });

      // Clear draft on publish
      form.addEventListener('submit', () => clearDraft());
    }

    // ── Clipboard image paste ─────────────────────────────────────────────

    editor.addEventListener('paste', (event) => {
      const clipboardItems = Array.from(event.clipboardData?.items || []);
      const imageFiles = [];
      const plainText = String(event.clipboardData?.getData('text/plain') || '').trim();
      clipboardItems.forEach((item, index) => {
        if (item.kind !== 'file' || !item.type.startsWith('image/')) {
          return;
        }
        const file = item.getAsFile();
        if (!file) {
          return;
        }
        const extension = (file.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
        const namedFile = new File([file], `pasted-${Date.now()}-${index}.${extension}`, { type: file.type });
        imageFiles.push(namedFile);
      });

      if (!imageFiles.length && plainText) {
        const embedUrl = parseVideoEmbedUrl(plainText);
        if (embedUrl) {
          event.preventDefault();
          insertHtmlAtCursor(editor, `<div class="video-frame inline-video"><iframe src="${escapeHtml(embedUrl)}" title="Embedded video" loading="lazy" allowfullscreen></iframe></div>`);
          syncEditorToTextarea(editor, bodyField);
        }
        return;
      }

      if (!imageFiles.length) {
        return;
      }

      event.preventDefault();
      editor.focus();
      restoreStoredTextSelection();
      const transfer = new DataTransfer();
      Array.from(imagesInput.files || []).forEach((file) => transfer.items.add(file));
      imageFiles.forEach((file) => transfer.items.add(file));
      if (transfer.files.length > 4) {
        window.alert('Only four images can be attached in this composer right now.');
        return;
      }
      imagesInput.files = transfer.files;
      imageFiles.forEach((file) => {
        const blobUrl = URL.createObjectURL(file);
        insertHtmlAtCursor(editor, `<figure class="inline-media"><img src="${blobUrl}" data-upload-image="1" alt="Pasted image"></figure>`);
      });
      hydrateInlineMediaBlocks();
      syncEditorToTextarea(editor, bodyField);
    });

    // ── Simple rich text toolbar (bbcode-like tokens) ────────────────────

    if (toolbar) {
      toolbar.addEventListener('pointerdown', (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }
        rememberEditorSelection(true);
        if (target.closest('button, select')) {
          toolbarFocusIntentAt = Date.now();
        }
      });

      toolbar.addEventListener('mousedown', (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }
        if (!target.closest('button[data-format]')) {
          return;
        }
        event.preventDefault();
        editor.focus();
        restoreStoredTextSelection();
      });

      toolbar.querySelectorAll('button[data-format]').forEach((button) => {
        button.addEventListener('click', () => {
          const format = button.dataset.format;
          if (!format) {
            return;
          }
          editor.focus();
          restoreStoredTextSelection();
          applyToolbarFormat(editor, format);
          rememberEditorSelection();
          syncEditorToTextarea(editor, bodyField);
          updateToolbarState(editor, toolbar);
          refocusEditor(false);
        });
      });

      const sizeSelect = toolbar.querySelector('[data-format-size]');
      sizeSelect?.addEventListener('focus', () => {
        rememberEditorSelection(true);
      });
      sizeSelect?.addEventListener('change', () => {
        const selectedSize = String(sizeSelect.value || '').trim();
        if (!selectedSize) {
          return;
        }
        editor.focus();
        restoreStoredTextSelection();
        applyToolbarFormat(editor, `size:${selectedSize}`);
        rememberEditorSelection();
        syncEditorToTextarea(editor, bodyField);
        sizeSelect.value = selectedSize;
        updateToolbarState(editor, toolbar);
        editor.focus();
      });

    }

    form.addEventListener('focusin', (event) => {
      const target = event.target;
      if (target instanceof Element && target.closest('[data-composer-toolbar]')) {
        const explicitToolbarClick = (Date.now() - toolbarFocusIntentAt) < 300;
        if (!explicitToolbarClick) {
          refocusEditor(false);
          return;
        }
      }
      setEditorActive(isFormattingSurface(event.target));
    });

    document.addEventListener('pointerdown', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) {
        setEditorActive(false);
        return;
      }
      const insideSurface = target.closest('[data-rich-editor], [data-composer-toolbar]');
      setEditorActive(Boolean(insideSurface && form.contains(insideSurface)));
    });

    editor.addEventListener('blur', () => {
      window.requestAnimationFrame(() => {
        setEditorActive(isFormattingSurface(document.activeElement));
      });
    });

    setEditorActive(false);

    // If browser restores focus to toolbar controls on load, hand it back to editor.
    window.requestAnimationFrame(() => {
      const activeElement = document.activeElement;
      if (
        activeElement instanceof Element
        && toolbar
        && toolbar.contains(activeElement)
        && activeElement.matches('select')
      ) {
        refocusEditor(false);
      }
    });

    // ── Review preview ────────────────────────────────────────────────────

    if (reviewButton && reviewPanel && reviewTitle && reviewBody) {
      reviewButton.addEventListener('click', () => {
        const title = (titleField?.value || '').trim();
        syncEditorToTextarea(editor, bodyField);
        reviewTitle.textContent = title || 'Untitled post';
        reviewBody.innerHTML = buildReviewHtml(bodyField.value, Array.from(imagesInput.files || []));
        reviewPanel.hidden = false;
        reviewPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      });
    }

    editor.addEventListener('input', () => {
      hydrateInlineMediaBlocks();
      rememberEditorSelection();
      syncEditorToTextarea(editor, bodyField);
      updateToolbarState(editor, toolbar);
    });

    updateToolbarState(editor, toolbar);

    closeReviewButton?.addEventListener('click', () => {
      if (reviewPanel) reviewPanel.hidden = true;
    });

    form.addEventListener('submit', () => {
      syncEditorToTextarea(editor, bodyField);
    });
  });
}

function wirePreviewBodySanitizer() {
  document.querySelectorAll('.post-body-preview').forEach((node) => {
    const source = String(node.textContent || '');
    let cleaned = source;
    cleaned = cleaned.replace(/\[\[image\]\]/gi, '');
    cleaned = cleaned.replace(/\[\/??(?:b|i|u|s)\]/gi, '');
    cleaned = cleaned.replace(/\[(?:size|color|font|link)=[^\]]+\]/gi, '');
    cleaned = cleaned.replace(/\[\/(?:size|color|font|link)\]/gi, '');
    cleaned = cleaned.replace(/\[image=[^\]]+\]/gi, '');
    node.textContent = cleaned.replace(/\s+/g, ' ').trim();
  });
}

function forceRuntimeFavicon() {
  const href = '/static/Logo.png?v=20260503t';
  const ensureLink = (relValue) => {
    let link = document.head.querySelector(`link[rel="${relValue}"]`);
    if (!link) {
      link = document.createElement('link');
      link.setAttribute('rel', relValue);
      document.head.appendChild(link);
    }
    link.setAttribute('type', 'image/png');
    link.setAttribute('href', href);
  };
  ensureLink('icon');
  ensureLink('shortcut icon');
}

function wireFeedCardClicks() {
  document.querySelectorAll('[data-post-url]').forEach((card) => {
    card.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      if (target.closest('a,button,input,textarea,form,label,[contenteditable="true"]')) {
        return;
      }
      const url = card.dataset.postUrl;
      if (url) {
        window.location.href = url;
      }
    });
  });
}

function wireMediaLightbox() {
  const lightbox = document.createElement('div');
  lightbox.className = 'media-lightbox';
  lightbox.innerHTML = '<img alt="Expanded media">';
  document.body.appendChild(lightbox);
  const lightboxImage = lightbox.querySelector('img');

  const close = () => lightbox.classList.remove('is-open');
  lightbox.addEventListener('click', close);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      close();
    }
  });

  document.querySelectorAll('.inline-media img, .media-grid img, .post-hero-image, .post-card-thumb').forEach((image) => {
    image.addEventListener('dblclick', (event) => {
      event.preventDefault();
      const src = image.getAttribute('src');
      if (!src || !lightboxImage) {
        return;
      }
      lightboxImage.setAttribute('src', src);
      lightbox.classList.add('is-open');
    });
  });
}

function wireInsightsChart() {
  document.querySelectorAll('[data-insights-chart]').forEach((container) => {
    const svg = container.querySelector('svg');
    if (!svg) {
      return;
    }
    let points;
    try {
      points = JSON.parse(container.dataset.insightsChart || '[]');
    } catch (_) {
      points = [];
    }
    if (!Array.isArray(points) || points.length === 0) {
      svg.innerHTML = '<text x="24" y="36" fill="rgba(236,244,255,0.7)">No view data yet.</text>';
      return;
    }

    const width = 960;
    const height = 320;
    const left = 54;
    const right = 24;
    const top = 20;
    const bottom = 38;
    const chartW = width - left - right;
    const chartH = height - top - bottom;
    const maxY = Math.max(1, ...points.map((p) => Number(p.value || 0)));
    const stepX = points.length > 1 ? chartW / (points.length - 1) : 0;

    const path = points.map((point, index) => {
      const x = left + (stepX * index);
      const y = top + chartH - ((Number(point.value || 0) / maxY) * chartH);
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`;
    }).join(' ');

    svg.innerHTML = `
      <line x1="${left}" y1="${top}" x2="${left}" y2="${top + chartH}" stroke="rgba(154,191,255,0.25)" />
      <line x1="${left}" y1="${top + chartH}" x2="${left + chartW}" y2="${top + chartH}" stroke="rgba(154,191,255,0.25)" />
      <path d="${path}" fill="none" stroke="#9ecbff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
      <text x="${left}" y="${height - 10}" fill="rgba(236,244,255,0.7)" font-size="11">${escapeHtml(points[0].label || '')}</text>
      <text x="${left + chartW - 80}" y="${height - 10}" fill="rgba(236,244,255,0.7)" font-size="11">${escapeHtml(points[points.length - 1].label || '')}</text>
      <text x="8" y="${top + 12}" fill="rgba(236,244,255,0.7)" font-size="11">${maxY}</text>
      <text x="14" y="${top + chartH}" fill="rgba(236,244,255,0.7)" font-size="11">0</text>
    `;
  });
}

wireReactionButtons();
wireShareButtons();
wireChatShells();
wireRichComposer();
wireFeedCardClicks();
wireMediaLightbox();
wireInsightsChart();
wirePreviewBodySanitizer();
forceRuntimeFavicon();

// ── Hamburger nav toggle ─────────────────────────
(function wireHamburger() {
  const toggle = document.getElementById('navToggle');
  const menu = document.getElementById('mobileMenu');
  if (!toggle || !menu) return;

  const syncState = (open) => {
    toggle.setAttribute('aria-expanded', String(open));
    menu.hidden = !open;
    menu.classList.toggle('is-open', open);
  };

  syncState(false);

  toggle.addEventListener('click', () => {
    const expanded = toggle.getAttribute('aria-expanded') === 'true';
    syncState(!expanded);
  });

  menu.querySelectorAll('a').forEach((link) => {
    link.addEventListener('click', () => {
      syncState(false);
    });
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      syncState(false);
    }
  });
})();
