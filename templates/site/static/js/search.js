/* ==========================================================================
   LexiPress · search.js
   Cmd/Ctrl+K 命令面板：异步加载 search-index.json，模糊匹配标题/来源/标签/生词。
   支持 ↑↓ 选择、Enter 跳转、Esc 关闭。
   ========================================================================== */
(function () {
  'use strict';

  var LP = window.LEXIPRESS = window.LEXIPRESS || {};
  var baseUrl = LP.baseUrl || '';

  var palette = document.querySelector('[data-role="palette"]');
  if (!palette) return;

  var input = document.getElementById('palette-input');
  var resultsEl = document.querySelector('[data-role="palette-results"]');
  var overlay = document.querySelector('[data-role="overlay"][data-target="palette"]');

  var indexCache = null;
  var indexPromise = null;
  var activeIndex = -1;
  var currentResults = [];

  /* ----------------------------------------------------------------------
     加载索引
     ---------------------------------------------------------------------- */
  function loadIndex() {
    if (indexCache) return Promise.resolve(indexCache);
    if (indexPromise) return indexPromise;
    indexPromise = fetch(baseUrl + '/search-index.json', { cache: 'no-cache' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        indexCache = Array.isArray(data) ? data : [];
        return indexCache;
      })
      .catch(function () {
        indexCache = [];
        return indexCache;
      });
    return indexPromise;
  }

  /* ----------------------------------------------------------------------
     模糊匹配打分
     ---------------------------------------------------------------------- */
  function scoreItem(item, query) {
    if (!query) return 1;
    var q = query.toLowerCase();
    var title = String(item.title || '').toLowerCase();
    var source = String(item.source || '').toLowerCase();
    var tags = (item.tags || []).join(' ').toLowerCase();
    var vocab = (item.vocab || []).join(' ').toLowerCase();
    var excerpt = String(item.excerpt || '').toLowerCase();

    var score = 0;
    if (title === q) score += 120;
    if (title.indexOf(q) === 0) score += 80;
    else if (title.indexOf(q) > 0) score += 50;
    if (source.indexOf(q) >= 0) score += 24;
    if (tags.indexOf(q) >= 0) score += 18;
    if (vocab.indexOf(q) >= 0) score += 14;
    if (excerpt.indexOf(q) >= 0) score += 8;

    // 子序列模糊匹配（如 "arc att" → "The Architecture of Attention"）
    if (!score && isSubsequence(q, title)) score += 10;
    return score;
  }

  function isSubsequence(needle, haystack) {
    var i = 0;
    var j = 0;
    while (i < needle.length && j < haystack.length) {
      if (needle[i] === haystack[j]) i++;
      j++;
    }
    return i === needle.length;
  }

  /* ----------------------------------------------------------------------
     渲染
     ---------------------------------------------------------------------- */
  function render(list) {
    currentResults = list;
    activeIndex = list.length ? 0 : -1;
    resultsEl.innerHTML = '';

    if (!list.length) {
      var empty = document.createElement('li');
      empty.className = 'palette__empty';
      empty.textContent = '没有匹配的文章，换个关键词试试。';
      resultsEl.appendChild(empty);
      return;
    }

    list.forEach(function (item, idx) {
      var li = document.createElement('li');
      li.className = 'palette__item' + (idx === 0 ? ' is-active' : '');
      li.setAttribute('role', 'option');
      li.dataset.href = item.url || baseUrl + '/articles/' + item.id + '/';

      var title = document.createElement('span');
      title.className = 'palette__item-title';
      title.textContent = item.title || '(untitled)';
      li.appendChild(title);

      var meta = document.createElement('span');
      meta.className = 'palette__item-meta';
      var bits = [item.source || '', item.difficulty || '', item.published_at || ''].filter(Boolean);
      meta.textContent = bits.join(' · ');
      li.appendChild(meta);

      li.addEventListener('click', function () {
        navigate(item);
      });
      li.addEventListener('mouseenter', function () {
        setActive(idx);
      });

      resultsEl.appendChild(li);
    });
  }

  function setActive(idx) {
    var items = resultsEl.querySelectorAll('.palette__item');
    if (!items.length) return;
    if (idx < 0) idx = items.length - 1;
    if (idx >= items.length) idx = 0;
    activeIndex = idx;
    items.forEach(function (el, i) {
      el.classList.toggle('is-active', i === idx);
      if (i === idx && el.scrollIntoView) {
        el.scrollIntoView({ block: 'nearest' });
      }
    });
  }

  function navigate(item) {
    var href = item.url || baseUrl + '/articles/' + item.id + '/';
    window.location.href = href;
  }

  /* ----------------------------------------------------------------------
     搜索
     ---------------------------------------------------------------------- */
  function runSearch() {
    var query = input.value.trim();
    loadIndex().then(function (index) {
      if (!query) {
        render(index.slice(0, 8));
        return;
      }
      var scored = [];
      index.forEach(function (item) {
        var s = scoreItem(item, query);
        if (s > 0) scored.push({ item: item, score: s });
      });
      scored.sort(function (a, b) {
        return b.score - a.score;
      });
      render(
        scored.slice(0, 12).map(function (entry) {
          return entry.item;
        })
      );
    });
  }

  /* ----------------------------------------------------------------------
     开关
     ---------------------------------------------------------------------- */
  var lastFocused = null;

  function openSearch() {
    lastFocused = document.activeElement;
    palette.classList.add('is-open');
    if (overlay) {
      overlay.hidden = false;
      overlay.classList.add('is-open');
    }
    document.body.classList.add('is-locked');
    if (input) {
      input.value = '';
      input.focus();
    }
    loadIndex().then(function (index) {
      render(index.slice(0, 8));
    });
  }

  function closeSearch() {
    palette.classList.remove('is-open');
    if (overlay) {
      overlay.hidden = true;
      overlay.classList.remove('is-open');
    }
    if (!document.querySelector('.drawer.is-open') && !document.querySelector('.sheet.is-open')) {
      document.body.classList.remove('is-locked');
    }
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  }

  window.lexipressOpenSearch = openSearch;
  window.lexipressCloseSearch = closeSearch;
  LP.openSearch = openSearch;
  LP.closeSearch = closeSearch;

  /* ----------------------------------------------------------------------
     事件
     ---------------------------------------------------------------------- */
  if (input) {
    var debounceTimer = null;
    input.addEventListener('input', function () {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(runSearch, 90);
    });

    input.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setActive(activeIndex + 1);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        setActive(activeIndex - 1);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        var item = currentResults[activeIndex];
        if (item) navigate(item);
      }
    });
  }

  document.addEventListener('keydown', function (event) {
    var isK = event.key === 'k' || event.key === 'K';
    if ((event.metaKey || event.ctrlKey) && isK) {
      event.preventDefault();
      if (palette.classList.contains('is-open')) {
        closeSearch();
      } else {
        openSearch();
      }
      return;
    }
    if (event.key === 'Escape' && palette.classList.contains('is-open')) {
      closeSearch();
    }
  });

  // 预取索引，让首次 ⌘K 零等待
  if ('requestIdleCallback' in window) {
    window.requestIdleCallback(loadIndex, { timeout: 2500 });
  } else {
    setTimeout(loadIndex, 1200);
  }
})();
