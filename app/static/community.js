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

function insertHtmlAtCursor(html) {
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount) {
    return;
  }
  const range = selection.getRangeAt(0);
  range.deleteContents();
  const template = document.createElement('template');
  template.innerHTML = html;
  const fragment = template.content;
  range.insertNode(fragment);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
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

function renderInlineMarkup(text) {
  let html = escapeHtml(text);
  html = html.replace(/\[b\](.*?)\[\/b\]/gi, '<strong>$1</strong>');
  html = html.replace(/\[i\](.*?)\[\/i\]/gi, '<em>$1</em>');
  html = html.replace(/\[u\](.*?)\[\/u\]/gi, '<u>$1</u>');
  html = html.replace(/\[size=(\d{1,2})\](.*?)\[\/size\]/gi, (_, sizeRaw, content) => {
    const size = Math.max(12, Math.min(48, Number(sizeRaw || 16)));
    return `<span style="font-size:${size}px">${content}</span>`;
  });
  html = html.replace(/\[link=(https?:\/\/[^\]\s]+)\](.*?)\[\/link\]/gi, (_, href, content) => {
    return `<a href="${href}" target="_blank" rel="noopener noreferrer">${content}</a>`;
  });
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
    const embedUrl = parseVideoEmbedUrl(trimmed);
    if (embedUrl) {
      return `<div class="video-frame inline-video"><iframe src="${escapeHtml(embedUrl)}" title="Embedded post video preview" loading="lazy" allowfullscreen></iframe></div>`;
    }
    return `<p>${renderInlineMarkup(line)}</p>`;
  }).join('');
}

function htmlNodeToMarkup(node) {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.nodeValue || '';
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
  if (tag === 'a') {
    const href = element.getAttribute('href') || '';
    if (/^https?:\/\//i.test(href)) {
      return `[link=${href}]${inner || href}[/link]`;
    }
    return inner;
  }
  if (tag === 'span') {
    const size = Number.parseInt((element.style.fontSize || '').replace('px', ''), 10);
    if (Number.isFinite(size) && size > 0) {
      return `[size=${size}]${inner}[/size]`;
    }
  }
  if (tag === 'br') {
    return '\n';
  }
  return inner;
}

function editorToMarkup(editor) {
  const lines = [];
  Array.from(editor.childNodes).forEach((node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = (node.nodeValue || '').trim();
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
    const textMarkup = htmlNodeToMarkup(element).trim();
    lines.push(textMarkup);
  });
  return lines.join('\n').trim();
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
  if (format === 'link') {
    const href = window.prompt('Link URL (https://...)', 'https://');
    if (!href || !/^https?:\/\//i.test(href)) {
      return;
    }
    document.execCommand('createLink', false, href);
    return;
  }
  if (format === 'size') {
    const sizeRaw = window.prompt('Font size (12-48):', '18');
    if (!sizeRaw) {
      return;
    }
    const size = Math.max(12, Math.min(48, Number.parseInt(sizeRaw, 10) || 18));
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount || selection.isCollapsed) {
      return;
    }
    const range = selection.getRangeAt(0);
    const span = document.createElement('span');
    span.style.fontSize = `${size}px`;
    try {
      range.surroundContents(span);
    } catch (_) {
      const content = range.extractContents();
      span.appendChild(content);
      range.insertNode(span);
    }
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

    if (!bodyField || !imagesInput || !editor) {
      return;
    }

    syncEditorToTextarea(editor, bodyField);

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
          insertHtmlAtCursor(`<div class="video-frame inline-video"><iframe src="${escapeHtml(embedUrl)}" title="Embedded video" loading="lazy" allowfullscreen></iframe></div>`);
          syncEditorToTextarea(editor, bodyField);
        }
        return;
      }

      if (!imageFiles.length) {
        return;
      }

      event.preventDefault();
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
        insertHtmlAtCursor(`<figure class="inline-media"><img src="${blobUrl}" data-upload-image="1" alt="Pasted image"></figure>`);
      });
      syncEditorToTextarea(editor, bodyField);
    });

    // ── Simple rich text toolbar (bbcode-like tokens) ────────────────────

    if (toolbar) {
      toolbar.querySelectorAll('button[data-format]').forEach((button) => {
        button.addEventListener('click', () => {
          const format = button.dataset.format;
          if (!format) {
            return;
          }
          applyToolbarFormat(editor, format);
          syncEditorToTextarea(editor, bodyField);
        });
      });
    }

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
      syncEditorToTextarea(editor, bodyField);
    });

    closeReviewButton?.addEventListener('click', () => {
      if (reviewPanel) reviewPanel.hidden = true;
    });

    form.addEventListener('submit', () => {
      syncEditorToTextarea(editor, bodyField);
    });
  });
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
