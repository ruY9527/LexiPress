/* ==========================================================================
   LexiPress · app.js
   全局交互：主题切换、学习工作台抽屉、LocalStorage 统计、Anki / Markdown 导出。
   所有持久化键统一 `lexipress_` 前缀。
   ========================================================================== */
(function () {
  'use strict';

  var LP = window.LEXIPRESS = window.LEXIPRESS || {};
  LP.baseUrl = LP.baseUrl || '';
  LP.defaultTheme = LP.defaultTheme || 'paper';

  var KEYS = {
    theme: 'lexipress_theme',
    prefs: 'lexipress_reader_prefs',
    history: 'lexipress_read_history',
    vocab: 'lexipress_vocab_book'
  };
  LP.KEYS = KEYS;

  var THEME_ORDER = ['paper', 'sepia', 'ink'];
  var THEME_LABEL = { paper: '晨纸白', sepia: '羊皮纸', ink: '静谧夜' };

  /* ----------------------------------------------------------------------
     安全读写：隐私模式 / 禁用 localStorage 时不抛错
     ---------------------------------------------------------------------- */
  function readJSON(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      if (!raw) return fallback;
      var parsed = JSON.parse(raw);
      return parsed == null ? fallback : parsed;
    } catch (e) {
      return fallback;
    }
  }

  function writeJSON(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (e) {
      return false;
    }
  }

  function readString(key, fallback) {
    try {
      return localStorage.getItem(key) || fallback;
    } catch (e) {
      return fallback;
    }
  }

  function writeString(key, value) {
    try {
      localStorage.setItem(key, value);
      return true;
    } catch (e) {
      return false;
    }
  }

  LP.readJSON = readJSON;
  LP.writeJSON = writeJSON;
  LP.readString = readString;
  LP.writeString = writeString;

  /* ----------------------------------------------------------------------
     主题
     ---------------------------------------------------------------------- */
  function currentTheme() {
    var t = document.documentElement.getAttribute('data-theme');
    return THEME_ORDER.indexOf(t) >= 0 ? t : LP.defaultTheme;
  }

  function applyTheme(theme, persist) {
    if (THEME_ORDER.indexOf(theme) < 0) theme = LP.defaultTheme;
    document.documentElement.setAttribute('data-theme', theme);
    if (persist) writeString(KEYS.theme, theme);
    document.querySelectorAll('.theme-dot').forEach(function (dot) {
      dot.classList.toggle('is-active', dot.getAttribute('data-theme-value') === theme);
    });
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute('content', theme === 'ink' ? '#121417' : theme === 'sepia' ? '#f4ecd8' : '#faf8f5');
    }
    return theme;
  }

  function cycleTheme() {
    var idx = THEME_ORDER.indexOf(currentTheme());
    var next = THEME_ORDER[(idx + 1) % THEME_ORDER.length];
    applyTheme(next, true);
    toast('主题 · ' + (THEME_LABEL[next] || next));
  }

  LP.applyTheme = applyTheme;
  LP.currentTheme = currentTheme;
  LP.cycleTheme = cycleTheme;

  /* ----------------------------------------------------------------------
     Toast
     ---------------------------------------------------------------------- */
  var toastTimer = null;
  function toast(message) {
    var el = document.querySelector('[data-role="toast"]');
    if (!el) return;
    el.textContent = message;
    el.classList.add('is-visible');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      el.classList.remove('is-visible');
    }, 1900);
  }
  LP.toast = toast;

  /* ----------------------------------------------------------------------
     阅读历史 / 打卡统计
     ---------------------------------------------------------------------- */
  function getHistory() {
    var h = readJSON(KEYS.history, null);
    if (!h || typeof h !== 'object') h = {};
    if (!Array.isArray(h.readIds)) h.readIds = [];
    if (typeof h.streakDays !== 'number') h.streakDays = 0;
    if (!h.lastReadDate) h.lastReadDate = '';
    return h;
  }

  function todayStr() {
    var d = new Date();
    var m = d.getMonth() + 1;
    var day = d.getDate();
    return d.getFullYear() + '-' + (m < 10 ? '0' + m : m) + '-' + (day < 10 ? '0' + day : day);
  }

  function dayDiff(a, b) {
    // a, b: 'YYYY-MM-DD'
    var pa = a.split('-').map(Number);
    var pb = b.split('-').map(Number);
    var da = Date.UTC(pa[0], pa[1] - 1, pa[2]);
    var db = Date.UTC(pb[0], pb[1] - 1, pb[2]);
    return Math.round((da - db) / 86400000);
  }

  function markRead(articleId) {
    var h = getHistory();
    if (h.readIds.indexOf(articleId) < 0) h.readIds.push(articleId);
    var today = todayStr();
    if (h.lastReadDate !== today) {
      if (h.lastReadDate && dayDiff(today, h.lastReadDate) === 1) {
        h.streakDays = (h.streakDays || 0) + 1;
      } else if (!h.lastReadDate || dayDiff(today, h.lastReadDate) > 1) {
        h.streakDays = 1;
      }
      h.lastReadDate = today;
    } else if (!h.streakDays) {
      h.streakDays = 1;
    }
    writeJSON(KEYS.history, h);
    return h;
  }

  function isRead(articleId) {
    var h = getHistory();
    return h.readIds.indexOf(articleId) >= 0;
  }

  function getStats() {
    var h = getHistory();
    var book = getVocabBook();
    return {
      streak: h.streakDays || 0,
      readCount: h.readIds ? h.readIds.length : 0,
      vocabCount: book.length
    };
  }

  LP.markRead = markRead;
  LP.isRead = isRead;
  LP.getStats = getStats;
  LP.todayStr = todayStr;

  /* ----------------------------------------------------------------------
     生词本
     ---------------------------------------------------------------------- */
  function getVocabBook() {
    var book = readJSON(KEYS.vocab, []);
    return Array.isArray(book) ? book : [];
  }

  function normalizeTerm(term) {
    return String(term || '').trim().toLowerCase();
  }

  function isSaved(term) {
    var key = normalizeTerm(term);
    return getVocabBook().some(function (item) {
      return normalizeTerm(item.term) === key;
    });
  }

  function saveVocab(entry) {
    if (!entry || !entry.term) return { ok: false, reason: 'empty' };
    var book = getVocabBook();
    var key = normalizeTerm(entry.term);
    var existing = book.findIndex(function (item) {
      return normalizeTerm(item.term) === key;
    });
    var record = {
      term: String(entry.term).trim(),
      phonetic: entry.phonetic || '',
      meaning_zh: entry.meaning_zh || '',
      note: entry.note || '',
      pos: entry.pos || '',
      source: entry.source || '',
      articleId: entry.articleId || '',
      savedAt: new Date().toISOString()
    };
    if (existing >= 0) {
      book[existing] = record;
      writeJSON(KEYS.vocab, book);
      return { ok: true, action: 'updated', count: book.length };
    }
    book.unshift(record);
    writeJSON(KEYS.vocab, book);
    updateBadges();
    return { ok: true, action: 'added', count: book.length };
  }

  function removeVocab(term) {
    var key = normalizeTerm(term);
    var book = getVocabBook().filter(function (item) {
      return normalizeTerm(item.term) !== key;
    });
    writeJSON(KEYS.vocab, book);
    updateBadges();
    return book.length;
  }

  LP.getVocabBook = getVocabBook;
  LP.saveVocab = saveVocab;
  LP.removeVocab = removeVocab;
  LP.isSaved = isSaved;

  /* ----------------------------------------------------------------------
     徽标与统计刷新
     ---------------------------------------------------------------------- */
  function updateBadges() {
    var stats = getStats();
    var badge = document.querySelector('[data-role="vocab-badge"]');
    if (badge) {
      if (stats.vocabCount > 0) {
        badge.textContent = stats.vocabCount > 99 ? '99+' : String(stats.vocabCount);
        badge.hidden = false;
      } else {
        badge.hidden = true;
      }
    }
    var streakEl = document.querySelector('[data-role="stat-streak"]');
    if (streakEl) streakEl.textContent = String(stats.streak);
    var readEl = document.querySelector('[data-role="stat-read"]');
    if (readEl) readEl.textContent = String(stats.readCount);
    var vocabEl = document.querySelector('[data-role="stat-vocab"]');
    if (vocabEl) vocabEl.textContent = String(stats.vocabCount);

    var readCount = document.querySelector('[data-role="read-count"]');
    if (readCount) readCount.textContent = String(stats.readCount);
    var fill = document.querySelector('[data-role="read-fill"]');
    if (fill) {
      var total = document.querySelectorAll('.card[data-article-id]').length;
      if (total > 0) {
        var pct = Math.min(100, (stats.readCount / total) * 100);
        fill.style.width = pct + '%';
      }
    }
    renderVocabList();
  }
  LP.updateBadges = updateBadges;

  /* ----------------------------------------------------------------------
     生词本渲染
     ---------------------------------------------------------------------- */
  function articleHref(articleId) {
    if (!articleId) return '';
    return LP.baseUrl + '/articles/' + articleId + '/';
  }

  function renderVocabList() {
    var listEl = document.querySelector('[data-role="vocab-list"]');
    var emptyEl = document.querySelector('[data-role="vocab-empty"]');
    if (!listEl) return;
    var filterEl = document.querySelector('[data-role="vocab-filter"]');
    var filter = filterEl ? filterEl.value.trim().toLowerCase() : '';
    var book = getVocabBook();
    if (filter) {
      book = book.filter(function (item) {
        return (
          String(item.term || '').toLowerCase().indexOf(filter) >= 0 ||
          String(item.meaning_zh || '').toLowerCase().indexOf(filter) >= 0
        );
      });
    }
    listEl.innerHTML = '';
    if (!book.length) {
      if (emptyEl) emptyEl.style.display = 'block';
      return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    book.forEach(function (item) {
      var li = document.createElement('li');
      li.className = 'vocab-entry';

      var head = document.createElement('div');
      head.className = 'vocab-entry__head';
      var term = document.createElement('span');
      term.className = 'vocab-entry__term';
      term.textContent = item.term;
      var phon = document.createElement('span');
      phon.className = 'vocab-entry__phonetic';
      phon.textContent = item.phonetic || '';
      head.appendChild(term);
      head.appendChild(phon);
      li.appendChild(head);

      if (item.meaning_zh) {
        var meaning = document.createElement('p');
        meaning.className = 'vocab-entry__meaning';
        meaning.textContent = item.meaning_zh;
        li.appendChild(meaning);
      }

      var foot = document.createElement('div');
      foot.className = 'vocab-entry__foot';

      var speakBtn = document.createElement('button');
      speakBtn.className = 'mini-button';
      speakBtn.type = 'button';
      speakBtn.textContent = '🔊';
      speakBtn.setAttribute('aria-label', '朗读 ' + item.term);
      speakBtn.addEventListener('click', function () {
        speak(item.term);
      });
      foot.appendChild(speakBtn);

      if (item.articleId) {
        var link = document.createElement('a');
        link.href = articleHref(item.articleId);
        link.textContent = item.source ? truncate(item.source, 22) : '查看原文';
        foot.appendChild(link);
      }

      var delBtn = document.createElement('button');
      delBtn.className = 'mini-button';
      delBtn.type = 'button';
      delBtn.textContent = '删除';
      delBtn.style.marginLeft = 'auto';
      delBtn.addEventListener('click', function () {
        removeVocab(item.term);
        toast('已从生词本移除 · ' + item.term);
      });
      foot.appendChild(delBtn);

      li.appendChild(foot);
      listEl.appendChild(li);
    });
  }

  function truncate(text, n) {
    text = String(text || '');
    return text.length > n ? text.slice(0, n - 1) + '…' : text;
  }

  /* ----------------------------------------------------------------------
     发音（Web Speech API）
     ---------------------------------------------------------------------- */
  function speak(text) {
    if (!text) return;
    if (!('speechSynthesis' in window)) {
      toast('当前浏览器不支持语音朗读');
      return;
    }
    try {
      window.speechSynthesis.cancel();
      var utter = new SpeechSynthesisUtterance(String(text));
      utter.lang = 'en-US';
      utter.rate = 0.92;
      utter.pitch = 1;
      var voices = window.speechSynthesis.getVoices();
      for (var i = 0; i < voices.length; i++) {
        if (/en[-_]US/i.test(voices[i].lang)) {
          utter.voice = voices[i];
          break;
        }
      }
      window.speechSynthesis.speak(utter);
    } catch (e) {
      toast('朗读失败');
    }
  }
  LP.speak = speak;

  /* ----------------------------------------------------------------------
     导出
     ---------------------------------------------------------------------- */
  function download(filename, content, mime) {
    try {
      var blob = new Blob([content], { type: (mime || 'text/plain') + ';charset=utf-8' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () {
        URL.revokeObjectURL(url);
      }, 1000);
      return true;
    } catch (e) {
      toast('导出失败，请检查浏览器权限');
      return false;
    }
  }

  function csvEscape(value) {
    var s = String(value == null ? '' : value);
    if (/[",\n\r]/.test(s)) {
      return '"' + s.replace(/"/g, '""') + '"';
    }
    return s;
  }

  function exportAnki() {
    var book = getVocabBook();
    if (!book.length) {
      toast('生词本为空，先收藏几个词吧');
      return;
    }
    var rows = ['Word,Phonetic,Meaning,Context,Source'];
    book.forEach(function (item) {
      rows.push(
        [
          csvEscape(item.term),
          csvEscape(item.phonetic),
          csvEscape(item.meaning_zh),
          csvEscape(item.note),
          csvEscape(item.source)
        ].join(',')
      );
    });
    // UTF-8 BOM，确保 Excel / Anki 导入中文不乱码
    var content = '\ufeff' + rows.join('\r\n') + '\r\n';
    if (download('lexipress-vocab-' + todayStr() + '.csv', content, 'text/csv')) {
      toast('已导出 Anki CSV · ' + book.length + ' 词');
    }
  }

  function exportMarkdown() {
    var book = getVocabBook();
    if (!book.length) {
      toast('生词本为空，先收藏几个词吧');
      return;
    }
    var stats = getStats();
    var lines = [];
    lines.push('# LexiPress 生词复习清单');
    lines.push('');
    lines.push('- 导出日期：' + todayStr());
    lines.push('- 生词数：' + book.length);
    lines.push('- 已读文章：' + stats.readCount);
    lines.push('- 连续打卡：' + stats.streak + ' 天');
    lines.push('');
    lines.push('---');
    lines.push('');
    book.forEach(function (item, idx) {
      lines.push('## ' + (idx + 1) + '. ' + item.term);
      lines.push('');
      if (item.phonetic) lines.push('- **音标**：' + item.phonetic);
      if (item.pos) lines.push('- **词性**：' + item.pos);
      if (item.meaning_zh) lines.push('- **释义**：' + item.meaning_zh);
      if (item.note) lines.push('- **用法**：' + item.note);
      if (item.source) {
        var src = item.source;
        if (item.articleId) {
          src = '[' + src + '](' + articleHref(item.articleId) + ')';
        }
        lines.push('- **来源**：' + src);
      }
      if (item.savedAt) lines.push('- **收藏于**：' + String(item.savedAt).slice(0, 10));
      lines.push('');
    });
    var content = lines.join('\n');
    if (download('lexipress-vocab-' + todayStr() + '.md', content, 'text/markdown')) {
      toast('已导出 Markdown · ' + book.length + ' 词');
    }
  }

  LP.exportAnki = exportAnki;
  LP.exportMarkdown = exportMarkdown;

  /* ----------------------------------------------------------------------
     遮罩 / 抽屉
     ---------------------------------------------------------------------- */
  function setOverlay(target, open) {
    document.querySelectorAll('[data-role="overlay"]').forEach(function (el) {
      if (el.getAttribute('data-target') === target) {
        el.hidden = !open;
        el.classList.toggle('is-open', open);
      }
    });
  }

  function anyOpen() {
    return (
      document.querySelector('.palette.is-open') ||
      document.querySelector('.drawer.is-open') ||
      document.querySelector('.sheet.is-open')
    );
  }

  function openDrawer() {
    var el = document.querySelector('[data-role="drawer"]');
    if (!el) return;
    el.classList.add('is-open');
    setOverlay('drawer', true);
    document.body.classList.add('is-locked');
    renderVocabList();
  }

  function closeDrawer() {
    var el = document.querySelector('[data-role="drawer"]');
    if (!el) return;
    el.classList.remove('is-open');
    setOverlay('drawer', false);
    if (!anyOpen()) document.body.classList.remove('is-locked');
  }

  LP.openDrawer = openDrawer;
  LP.closeDrawer = closeDrawer;

  /* ----------------------------------------------------------------------
     事件绑定
     ---------------------------------------------------------------------- */
  function bindGlobal() {
    document.addEventListener('click', function (event) {
      var actionEl = event.target.closest('[data-action]');
      if (actionEl) {
        var action = actionEl.getAttribute('data-action');
        if (action === 'cycle-theme') {
          cycleTheme();
          return;
        }
        if (action === 'open-drawer') {
          openDrawer();
          return;
        }
        if (action === 'close-drawer') {
          closeDrawer();
          return;
        }
        if (action === 'export-anki') {
          exportAnki();
          return;
        }
        if (action === 'export-markdown') {
          exportMarkdown();
          return;
        }
        if (action === 'reset-filters') {
          if (typeof window.lexipressResetFilters === 'function') window.lexipressResetFilters();
          return;
        }
        if (action === 'open-search') {
          if (typeof window.lexipressOpenSearch === 'function') window.lexipressOpenSearch();
          return;
        }
      }

      // 点击遮罩关闭
      var overlay = event.target.closest('[data-role="overlay"]');
      if (overlay) {
        var target = overlay.getAttribute('data-target');
        if (target === 'drawer') closeDrawer();
        if (target === 'palette' && typeof window.lexipressCloseSearch === 'function') window.lexipressCloseSearch();
        if (target === 'sheet' && typeof window.lexipressCloseSheet === 'function') window.lexipressCloseSheet();
      }
    });

    var filterEl = document.querySelector('[data-role="vocab-filter"]');
    if (filterEl) {
      filterEl.addEventListener('input', renderVocabList);
    }

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        closeDrawer();
        if (typeof window.lexipressCloseSheet === 'function') window.lexipressCloseSheet();
      }
    });
  }

  /* ----------------------------------------------------------------------
     首页：筛选 + 已读标记
     ---------------------------------------------------------------------- */
  function initHome() {
    var grid = document.querySelector('[data-role="grid"]');
    if (!grid) return;
    var filters = { source: 'all', level: 'all', state: 'all' };

    function applyFilters() {
      var visible = 0;
      grid.querySelectorAll('.card[data-article-id]').forEach(function (card) {
        var ok = true;
        if (filters.source !== 'all' && card.getAttribute('data-source') !== filters.source) ok = false;
        if (filters.level !== 'all' && card.getAttribute('data-level') !== filters.level) ok = false;
        var read = card.getAttribute('data-read') === '1';
        if (filters.state === 'read' && !read) ok = false;
        if (filters.state === 'unread' && read) ok = false;
        card.classList.toggle('is-hidden', !ok);
        if (ok) visible++;
      });
      var empty = document.querySelector('[data-role="empty-state"]');
      if (empty) empty.hidden = visible > 0;
    }

    document.querySelectorAll('.pill[data-filter]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var group = btn.getAttribute('data-filter');
        filters[group] = btn.getAttribute('data-value');
        document.querySelectorAll('.pill[data-filter="' + group + '"]').forEach(function (peer) {
          peer.classList.toggle('is-active', peer === btn);
        });
        applyFilters();
      });
    });

    window.lexipressResetFilters = function () {
      filters = { source: 'all', level: 'all', state: 'all' };
      document.querySelectorAll('.pill[data-filter]').forEach(function (btn) {
        btn.classList.toggle('is-active', btn.getAttribute('data-value') === 'all');
      });
      applyFilters();
    };

    // 已读注入
    grid.querySelectorAll('.card[data-article-id]').forEach(function (card) {
      var id = card.getAttribute('data-article-id');
      if (isRead(id)) {
        card.setAttribute('data-read', '1');
        card.classList.add('is-read');
      }
    });

    applyFilters();
  }

  /* ----------------------------------------------------------------------
     主题色块绑定（精读页 Aa 面板）
     ---------------------------------------------------------------------- */
  function bindThemeDots() {
    var dots = document.querySelectorAll('.theme-dot');
    if (!dots.length) return;
    dots.forEach(function (dot) {
      dot.classList.toggle('is-active', dot.getAttribute('data-theme-value') === currentTheme());
      dot.addEventListener('click', function () {
        applyTheme(dot.getAttribute('data-theme-value'), true);
      });
    });
  }

  /* ----------------------------------------------------------------------
     启动
     ---------------------------------------------------------------------- */
  function boot() {
    applyTheme(currentTheme(), false);
    bindGlobal();
    bindThemeDots();
    initHome();
    updateBadges();

    // 预加载语音列表（部分浏览器异步填充）
    if ('speechSynthesis' in window) {
      window.speechSynthesis.getVoices();
      window.speechSynthesis.onvoiceschanged = function () {
        window.speechSynthesis.getVoices();
      };
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
