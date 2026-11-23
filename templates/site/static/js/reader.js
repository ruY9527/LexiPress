/* ==========================================================================
   LexiPress · reader.js
   精读页交互：阅读进度、三模式切换、字号、禅模式、单段译文、Tab、移动端抽屉、
   已读标记、快捷键（1/2/3 · Z · T）。
   ========================================================================== */
(function () {
  'use strict';

  var LP = window.LEXIPRESS = window.LEXIPRESS || {};
  var body = document.querySelector('[data-role="article-body"]');
  if (!body) return;

  var layout = document.querySelector('[data-role="article-layout"]');
  var progress = document.querySelector('[data-role="reading-progress"]');
  var aaPanel = document.querySelector('[data-role="aa-panel"]');
  var articleId = body.getAttribute('data-article-id') || '';

  var MODES = ['en', 'vocab', 'dual'];
  var MODE_LABEL = { en: '纯英', vocab: '生词', dual: '双语' };

  /* ----------------------------------------------------------------------
     阅读偏好持久化
     ---------------------------------------------------------------------- */
  function getPrefs() {
    var prefs = LP.readJSON ? LP.readJSON(LP.KEYS.prefs, null) : null;
    if (!prefs || typeof prefs !== 'object') prefs = {};
    if (MODES.indexOf(prefs.mode) < 0) prefs.mode = 'vocab';
    if (['s', 'm', 'l'].indexOf(prefs.fontSize) < 0) prefs.fontSize = 'm';
    if (typeof prefs.zen !== 'boolean') prefs.zen = false;
    return prefs;
  }

  function savePrefs(patch) {
    var prefs = Object.assign(getPrefs(), patch || {});
    if (LP.writeJSON) LP.writeJSON(LP.KEYS.prefs, prefs);
    return prefs;
  }

  /* ----------------------------------------------------------------------
     阅读模式
     ---------------------------------------------------------------------- */
  function setMode(mode, persist) {
    if (MODES.indexOf(mode) < 0) mode = 'vocab';
    body.classList.remove('reader-mode-en', 'reader-mode-vocab', 'reader-mode-dual');
    body.classList.add('reader-mode-' + mode);

    document.querySelectorAll('.segmented__btn[data-mode]').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.getAttribute('data-mode') === mode);
    });

    // 双语模式：全部段落展开译文，同时隐藏单段「译」按钮的高亮态
    if (mode === 'dual') {
      document.querySelectorAll('.para-block').forEach(function (block) {
        block.classList.add('is-zh-open');
      });
    }

    if (persist !== false) savePrefs({ mode: mode });
    if (typeof LP.vocab === 'object' && LP.vocab.close) LP.vocab.close();
  }
  LP.setMode = setMode;

  /* ----------------------------------------------------------------------
     字号
     ---------------------------------------------------------------------- */
  function setFontSize(size, persist) {
    if (['s', 'm', 'l'].indexOf(size) < 0) size = 'm';
    document.documentElement.setAttribute('data-font', size);
    document.querySelectorAll('.size-btn').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.getAttribute('data-size') === size);
    });
    if (persist !== false) savePrefs({ fontSize: size });
  }

  /* ----------------------------------------------------------------------
     禅模式
     ---------------------------------------------------------------------- */
  function setZen(on, persist) {
    if (!layout) return;
    layout.classList.toggle('is-zen', on);
    var btn = document.querySelector('[data-action="toggle-zen"]');
    if (btn) btn.classList.toggle('is-active', on);
    if (persist !== false) savePrefs({ zen: on });
    if (on) LP.toast('禅模式已开启');
  }

  function toggleZen() {
    setZen(!(layout && layout.classList.contains('is-zen')));
  }

  /* ----------------------------------------------------------------------
     进度条
     ---------------------------------------------------------------------- */
  function updateProgress() {
    if (!progress) return;
    var doc = document.documentElement;
    var scrollTop = window.scrollY || doc.scrollTop || 0;
    var height = doc.scrollHeight - window.innerHeight;
    var pct = height > 0 ? Math.min(100, (scrollTop / height) * 100) : 0;
    progress.style.width = pct.toFixed(2) + '%';
  }

  /* ----------------------------------------------------------------------
     单段译文
     ---------------------------------------------------------------------- */
  function bindParaToggles() {
    body.addEventListener('click', function (event) {
      var toggle = event.target.closest('[data-action="toggle-para"]');
      if (!toggle) return;
      var block = toggle.closest('.para-block');
      if (!block) return;
      event.preventDefault();
      block.classList.toggle('is-zh-open');
      toggle.setAttribute(
        'aria-expanded',
        block.classList.contains('is-zh-open') ? 'true' : 'false'
      );
    });
  }

  /* ----------------------------------------------------------------------
     助手栏 Tab（桌面 + 移动端共享逻辑）
     ---------------------------------------------------------------------- */
  function bindTabs(scope) {
    var tabs = scope.querySelectorAll('.aside-tab');
    if (!tabs.length) return;
    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        var target = tab.getAttribute('data-tab');
        tabs.forEach(function (peer) {
          peer.classList.toggle('is-active', peer === tab);
        });

        if (scope.hasAttribute('data-role') && scope.getAttribute('data-role') === 'sheet') {
          // 移动端：把对应面板搬到 sheet body
          renderSheetPanel(target);
        } else {
          scope.querySelectorAll('.aside-panel').forEach(function (panel) {
            panel.classList.toggle('is-active', panel.getAttribute('data-panel') === target);
          });
        }
      });
    });
  }

  /* ----------------------------------------------------------------------
     移动端抽屉
     ---------------------------------------------------------------------- */
  var sheet = document.querySelector('[data-role="sheet"]');
  var sheetBody = document.querySelector('[data-role="sheet-body"]');

  function renderSheetPanel(name) {
    if (!sheetBody) return;
    var aside = document.querySelector('[data-role="study-aside"]');
    sheetBody.innerHTML = '';
    if (!aside) {
      sheetBody.innerHTML = '<p class="empty-hint">本文暂无精读笔记。</p>';
      return;
    }
    var source = aside.querySelector('.aside-panel[data-panel="' + name + '"]');
    if (!source) {
      sheetBody.innerHTML = '<p class="empty-hint">该栏目暂无内容。</p>';
      return;
    }
    var clone = source.cloneNode(true);
    clone.classList.add('is-active');
    // 去掉 id/for 冲突（克隆元素里没有 id，安全）
    sheetBody.appendChild(clone);

    // 重新绑定克隆内的交互
    if (typeof LP.vocab === 'object' && LP.vocab && LP.vocab.rebind) LP.vocab.rebind(sheetBody);
    bindClonedInteractions(sheetBody);
  }

  function bindClonedInteractions(scope) {
    scope.querySelectorAll('[data-action="reveal-spoiler"]').forEach(function (veil) {
      veil.addEventListener('click', function () {
        var spoiler = veil.closest('.spoiler');
        if (spoiler) spoiler.classList.add('is-revealed');
      });
    });

    scope.querySelectorAll('[data-action="speak"]').forEach(function (btn) {
      btn.addEventListener('click', function (event) {
        event.stopPropagation();
        LP.speak(btn.getAttribute('data-term') || '');
      });
    });

    scope.querySelectorAll('[data-action="save-vocab"]').forEach(function (btn) {
      btn.addEventListener('click', function (event) {
        event.stopPropagation();
        var term = btn.getAttribute('data-term') || '';
        if (!term) return;
        if (LP.isSaved(term)) {
          LP.removeVocab(term);
          LP.toast('已移除 · ' + term);
        } else {
          LP.saveVocab({
            term: term,
            phonetic: btn.getAttribute('data-phonetic') || '',
            meaning_zh: btn.getAttribute('data-meaning') || '',
            articleId: btn.getAttribute('data-article-id') || '',
            source: btn.getAttribute('data-source') || ''
          });
          LP.toast('已加入生词本 · ' + term);
        }
        syncCloneButtons(scope);
      });
    });

    scope.querySelectorAll('.vocab-card').forEach(function (card) {
      card.addEventListener('click', function (event) {
        if (event.target.closest('button')) return;
        var term = card.getAttribute('data-term') || '';
        closeSheet();
        if (typeof LP.vocab === 'object' && LP.vocab.jumpToTerm) {
          LP.vocab.jumpToTerm(term, null);
        }
      });
    });

    syncCloneButtons(scope);
  }

  function syncCloneButtons(scope) {
    scope.querySelectorAll('[data-action="save-vocab"]').forEach(function (btn) {
      var term = btn.getAttribute('data-term') || '';
      var saved = LP.isSaved(term);
      btn.textContent = saved ? '★ 已收藏' : '☆ 收藏';
    });
  }

  function openSheet() {
    if (!sheet) return;
    var activeTab = document.querySelector('.sheet .aside-tab.is-active');
    renderSheetPanel(activeTab ? activeTab.getAttribute('data-tab') : 'overview');
    sheet.classList.add('is-open');
    var overlay = document.querySelector('[data-role="overlay"][data-target="sheet"]');
    if (overlay) {
      overlay.hidden = false;
      overlay.classList.add('is-open');
    }
    document.body.classList.add('is-locked');
  }

  function closeSheet() {
    if (!sheet) return;
    sheet.classList.remove('is-open');
    var overlay = document.querySelector('[data-role="overlay"][data-target="sheet"]');
    if (overlay) {
      overlay.hidden = true;
      overlay.classList.remove('is-open');
    }
    if (!document.querySelector('.drawer.is-open') && !document.querySelector('.palette.is-open')) {
      document.body.classList.remove('is-locked');
    }
  }

  window.lexipressCloseSheet = closeSheet;
  LP.openSheet = openSheet;
  LP.closeSheet = closeSheet;

  /* ----------------------------------------------------------------------
     已读标记
     ---------------------------------------------------------------------- */
  function initMarkRead() {
    var btn = document.querySelector('[data-action="mark-read"]');
    if (!btn) return;
    var label = btn.querySelector('[data-role="mark-read-label"]');

    function sync() {
      var done = LP.isRead(articleId);
      btn.classList.toggle('is-done', done);
      if (label) label.textContent = done ? '已标记为已读' : '标记为已读';
    }

    btn.addEventListener('click', function () {
      if (LP.isRead(articleId)) {
        LP.toast('这篇文章已经在你的已读清单里');
        return;
      }
      var stats = LP.markRead(articleId);
      sync();
      if (LP.updateBadges) LP.updateBadges();
      LP.toast('已读打卡 · 连续 ' + (stats.streakDays || 1) + ' 天');
    });

    sync();
  }

  /* ----------------------------------------------------------------------
     盲读保护罩
     ---------------------------------------------------------------------- */
  function bindSpoiler() {
    document.querySelectorAll('[data-action="reveal-spoiler"]').forEach(function (veil) {
      function reveal() {
        var spoiler = veil.closest('.spoiler');
        if (spoiler) spoiler.classList.add('is-revealed');
      }
      veil.addEventListener('click', reveal);
      veil.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          reveal();
        }
      });
    });
  }

  /* ----------------------------------------------------------------------
     Aa 面板
     ---------------------------------------------------------------------- */
  function bindAaPanel() {
    var toggle = document.querySelector('[data-action="toggle-aa"]');
    if (toggle && aaPanel) {
      toggle.addEventListener('click', function (event) {
        event.stopPropagation();
        aaPanel.classList.toggle('is-open');
      });
      document.addEventListener('click', function (event) {
        if (!aaPanel.classList.contains('is-open')) return;
        if (aaPanel.contains(event.target) || event.target.closest('[data-action="toggle-aa"]')) return;
        aaPanel.classList.remove('is-open');
      });
    }

    document.querySelectorAll('.size-btn').forEach(function (btn) {
      btn.addEventListener('click', function (event) {
        event.stopPropagation();
        setFontSize(btn.getAttribute('data-size'));
      });
    });
  }

  /* ----------------------------------------------------------------------
     音频倍速（Phase 3 预留）
     ---------------------------------------------------------------------- */
  function bindAudio() {
    var audio = document.querySelector('.audio-bar audio');
    var btn = document.querySelector('[data-action="cycle-speed"]');
    if (!audio || !btn) return;
    var speeds = [1.0, 1.25, 1.5, 0.8];
    var idx = 0;
    btn.addEventListener('click', function () {
      idx = (idx + 1) % speeds.length;
      audio.playbackRate = speeds[idx];
      btn.textContent = speeds[idx].toFixed(2).replace(/0$/, '') + 'x';
    });
  }

  /* ----------------------------------------------------------------------
     快捷键
     ---------------------------------------------------------------------- */
  function bindShortcuts() {
    document.addEventListener('keydown', function (event) {
      var tag = (event.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || event.target.isContentEditable) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      if (event.key === '1') {
        setMode('en');
        LP.toast('纯英沉浸');
      } else if (event.key === '2') {
        setMode('vocab');
        LP.toast('生词高亮');
      } else if (event.key === '3') {
        setMode('dual');
        LP.toast('双语对照');
      } else if (event.key === 'z' || event.key === 'Z') {
        toggleZen();
      } else if (event.key === 't' || event.key === 'T') {
        if (typeof LP.cycleTheme === 'function') LP.cycleTheme();
      }
    });
  }

  /* ----------------------------------------------------------------------
     启动
     ---------------------------------------------------------------------- */
  function boot() {
    var prefs = getPrefs();
    setMode(prefs.mode, false);
    setFontSize(prefs.fontSize, false);
    if (prefs.zen) setZen(true, false);

    // Aa 面板中的主题色块高亮
    document.querySelectorAll('.theme-dot').forEach(function (dot) {
      dot.classList.toggle(
        'is-active',
        dot.getAttribute('data-theme-value') === (LP.currentTheme ? LP.currentTheme() : 'paper')
      );
    });

    bindParaToggles();
    bindTabs(document.querySelector('[data-role="study-aside"]') || document);
    bindTabs(sheet || document);
    bindSpoiler();
    bindAaPanel();
    bindAudio();
    initMarkRead();
    bindShortcuts();

    var fab = document.querySelector('[data-action="open-sheet"]');
    if (fab) fab.addEventListener('click', openSheet);
    var sheetClose = document.querySelector('[data-action="close-sheet"]');
    if (sheetClose) sheetClose.addEventListener('click', closeSheet);

    var zenBtn = document.querySelector('[data-action="toggle-zen"]');
    if (zenBtn) zenBtn.addEventListener('click', toggleZen);

    document.querySelectorAll('.segmented__btn[data-mode]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setMode(btn.getAttribute('data-mode'));
      });
    });

    // 首次进入文章自动记为“浏览过”，但不自动标记已读（尊重用户主动打卡）
    updateProgress();
    window.addEventListener('scroll', updateProgress, { passive: true });
    window.addEventListener('resize', updateProgress);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
