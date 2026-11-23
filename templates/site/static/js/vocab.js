/* ==========================================================================
   LexiPress · vocab.js
   文内生词点击浮窗：定位、发音、收藏、与词表双向联动。
   依赖 app.js 提供的 LP.readJSON / LP.saveVocab / LP.speak / LP.toast。
   ========================================================================== */
(function () {
  'use strict';

  var LP = window.LEXIPRESS = window.LEXIPRESS || {};
  var popover = document.querySelector('[data-role="vocab-popover"]');
  if (!popover) return;

  var termEl = popover.querySelector('[data-role="pop-term"]');
  var posEl = popover.querySelector('[data-role="pop-pos"]');
  var phoneticEl = popover.querySelector('[data-role="pop-phonetic"]');
  var meaningEl = popover.querySelector('[data-role="pop-meaning"]');
  var noteEl = popover.querySelector('[data-role="pop-note"]');
  var saveBtn = popover.querySelector('[data-role="pop-save"]');

  var vocabMap = {};
  var articleMeta = {};
  var currentEntry = null;
  var currentAnchor = null;

  /* ----------------------------------------------------------------------
     读取页面注入的文章数据
     ---------------------------------------------------------------------- */
  function readArticleData() {
    var el = document.querySelector('[data-role="article-data"]');
    if (!el) return {};
    try {
      var data = JSON.parse(el.textContent || '{}');
      (data.vocab || []).forEach(function (v) {
        if (v && v.term) {
          vocabMap[String(v.term).toLowerCase()] = v;
        }
      });
      articleMeta = data;
      return data;
    } catch (e) {
      return {};
    }
  }

  /* ----------------------------------------------------------------------
     定位（自动防溢出）
     ---------------------------------------------------------------------- */
  function positionFor(anchor) {
    var rect = anchor.getBoundingClientRect();
    var popRect = popover.getBoundingClientRect();
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var gap = 10;

    var top = rect.top - popRect.height - gap;
    if (top < gap) {
      top = rect.bottom + gap;
      if (top + popRect.height > vh - gap) {
        top = Math.max(gap, vh - popRect.height - gap);
      }
    }

    var left = rect.left + rect.width / 2 - popRect.width / 2;
    left = Math.max(12, Math.min(left, vw - popRect.width - 12));

    popover.style.top = Math.round(top) + 'px';
    popover.style.left = Math.round(left) + 'px';
  }

  /* ----------------------------------------------------------------------
     打开 / 关闭
     ---------------------------------------------------------------------- */
  function openFor(anchor) {
    var term = anchor.getAttribute('data-term') || anchor.textContent || '';
    var key = String(term).trim().toLowerCase();
    var entry = vocabMap[key] || null;

    currentEntry = entry ? Object.assign({}, entry) : { term: String(term).trim() };
    if (!currentEntry.term) currentEntry.term = String(anchor.textContent || '').trim();
    currentAnchor = anchor;

    termEl.textContent = currentEntry.term;
    if (currentEntry.pos) {
      posEl.textContent = currentEntry.pos;
      posEl.hidden = false;
    } else {
      posEl.hidden = true;
    }
    phoneticEl.textContent = currentEntry.phonetic || '';
    phoneticEl.hidden = !currentEntry.phonetic;
    meaningEl.textContent = currentEntry.meaning_zh || '收藏后可在学习工作台补充笔记。';
    if (currentEntry.note) {
      noteEl.textContent = currentEntry.note;
      noteEl.hidden = false;
    } else {
      noteEl.hidden = true;
    }

    syncSaveButton();

    // 先显示以便测量尺寸，再定位
    popover.style.visibility = 'hidden';
    popover.classList.add('is-open');
    positionFor(anchor);
    popover.style.visibility = '';

    document.querySelectorAll('.vocab-term.is-active').forEach(function (el) {
      el.classList.remove('is-active');
    });
    anchor.classList.add('is-active');
  }

  function close() {
    popover.classList.remove('is-open');
    if (currentAnchor) currentAnchor.classList.remove('is-active');
    currentAnchor = null;
    currentEntry = null;
  }

  function syncSaveButton() {
    if (!currentEntry) return;
    var saved = typeof LP.isSaved === 'function' && LP.isSaved(currentEntry.term);
    if (saved) {
      saveBtn.textContent = '★ 已收藏';
      saveBtn.classList.add('is-saved');
    } else {
      saveBtn.textContent = '☆ 加入生词本';
      saveBtn.classList.remove('is-saved');
    }
  }

  /* ----------------------------------------------------------------------
     保存
     ---------------------------------------------------------------------- */
  saveBtn.addEventListener('click', function () {
    if (!currentEntry) return;
    var saved = typeof LP.isSaved === 'function' && LP.isSaved(currentEntry.term);
    if (saved) {
      LP.removeVocab(currentEntry.term);
      LP.toast('已移除 · ' + currentEntry.term);
    } else {
      var payload = Object.assign({}, currentEntry, {
        articleId: articleMeta.id || '',
        source: articleMeta.title || '',
        articleTitle: articleMeta.title || ''
      });
      LP.saveVocab(payload);
      LP.toast('已加入生词本 · ' + currentEntry.term);
    }
    syncSaveButton();
    syncAsideCards();
  });

  popover.querySelector('[data-action="speak-pop"]').addEventListener('click', function () {
    if (currentEntry && currentEntry.term) LP.speak(currentEntry.term);
  });

  /* ----------------------------------------------------------------------
     词表卡片联动
     ---------------------------------------------------------------------- */
  function syncAsideCards() {
    document.querySelectorAll('.vocab-card').forEach(function (card) {
      var term = card.getAttribute('data-term') || '';
      var btn = card.querySelector('[data-action="save-vocab"]');
      if (!btn) return;
      var saved = typeof LP.isSaved === 'function' && LP.isSaved(term);
      btn.textContent = saved ? '★ 已收藏' : '☆ 收藏';
    });
  }

  function findFirstMark(term) {
    var key = String(term || '').toLowerCase();
    var marks = document.querySelectorAll('.vocab-term');
    for (var i = 0; i < marks.length; i++) {
      var t = (marks[i].getAttribute('data-term') || marks[i].textContent || '').toLowerCase();
      if (t === key) return marks[i];
    }
    return null;
  }

  function pulse(el) {
    if (!el) return;
    el.classList.remove('is-pulsing');
    // 强制重排以重启动画
    void el.offsetWidth;
    el.classList.add('is-pulsing');
    setTimeout(function () {
      el.classList.remove('is-pulsing');
    }, 1500);
  }

  function jumpToTerm(term, cardEl) {
    var mark = findFirstMark(term);
    if (!mark) {
      LP.toast('该词在当前视图中未出现');
      return;
    }
    // 若处于纯英模式，先切到生词模式，让下划线可见
    var body = document.querySelector('[data-role="article-body"]');
    if (body && body.classList.contains('reader-mode-en') && typeof LP.setMode === 'function') {
      LP.setMode('vocab');
    }
    mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
    pulse(mark);
    if (cardEl) {
      document.querySelectorAll('.vocab-card.is-linked').forEach(function (el) {
        el.classList.remove('is-linked');
      });
      cardEl.classList.add('is-linked');
    }
    setTimeout(function () {
      openFor(mark);
    }, 420);
  }

  /* ----------------------------------------------------------------------
     事件绑定
     ---------------------------------------------------------------------- */
  function bindBodyMarks() {
    var body = document.querySelector('[data-role="article-body"]');
    if (!body) return;
    body.addEventListener('click', function (event) {
      var mark = event.target.closest('.vocab-term');
      if (!mark) {
        close();
        return;
      }
      // 纯英模式不响应查词
      if (body.classList.contains('reader-mode-en')) return;
      event.preventDefault();
      if (currentAnchor === mark) {
        close();
        return;
      }
      openFor(mark);
      // 反向联动：滚动右侧词表到对应卡片
      var term = (mark.getAttribute('data-term') || '').toLowerCase();
      var card = document.querySelector('.vocab-card[data-term="' + cssEscape(term) + '"]');
      if (!card) {
        var cards = document.querySelectorAll('.vocab-card');
        for (var i = 0; i < cards.length; i++) {
          if ((cards[i].getAttribute('data-term') || '').toLowerCase() === term) {
            card = cards[i];
            break;
          }
        }
      }
      if (card) {
        document.querySelectorAll('.vocab-card.is-linked').forEach(function (el) {
          el.classList.remove('is-linked');
        });
        card.classList.add('is-linked');
        if (card.scrollIntoView) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    });

    body.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      var mark = event.target.closest('.vocab-term');
      if (!mark) return;
      event.preventDefault();
      openFor(mark);
    });
  }

  function cssEscape(value) {
    if (window.CSS && window.CSS.escape) return window.CSS.escape(value);
    return String(value).replace(/["\\]/g, '\\$&');
  }

  function bindAsideCards() {
    document.querySelectorAll('.vocab-card').forEach(function (card) {
      var term = card.getAttribute('data-term') || '';
      card.addEventListener('click', function (event) {
        if (event.target.closest('button')) return;
        jumpToTerm(term, card);
      });
      card.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') {
          event.preventDefault();
          jumpToTerm(term, card);
        }
      });

      var speakBtn = card.querySelector('[data-action="speak"]');
      if (speakBtn) {
        speakBtn.addEventListener('click', function (event) {
          event.stopPropagation();
          LP.speak(term);
        });
      }

      var saveBtnCard = card.querySelector('[data-action="save-vocab"]');
      if (saveBtnCard) {
        saveBtnCard.addEventListener('click', function (event) {
          event.stopPropagation();
          var saved = LP.isSaved(term);
          if (saved) {
            LP.removeVocab(term);
            LP.toast('已移除 · ' + term);
          } else {
            var entry = vocabMap[term.toLowerCase()] || { term: term };
            LP.saveVocab(
              Object.assign({}, entry, {
                articleId: articleMeta.id || '',
                source: articleMeta.title || ''
              })
            );
            LP.toast('已加入生词本 · ' + term);
          }
          syncAsideCards();
          syncSaveButton();
        });
      }
    });
  }

  document.addEventListener('click', function (event) {
    if (!popover.classList.contains('is-open')) return;
    if (popover.contains(event.target)) return;
    if (event.target.closest('.vocab-term')) return;
    close();
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && popover.classList.contains('is-open')) {
      close();
    }
  });

  window.addEventListener('resize', function () {
    if (popover.classList.contains('is-open') && currentAnchor) {
      positionFor(currentAnchor);
    }
  });

  window.addEventListener(
    'scroll',
    function () {
      if (popover.classList.contains('is-open') && currentAnchor) {
        positionFor(currentAnchor);
      }
    },
    { passive: true }
  );

  /* ----------------------------------------------------------------------
     启动
     ---------------------------------------------------------------------- */
  function boot() {
    readArticleData();
    bindBodyMarks();
    bindAsideCards();
    syncAsideCards();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  LP.vocab = { openFor: openFor, close: close, jumpToTerm: jumpToTerm };
})();
