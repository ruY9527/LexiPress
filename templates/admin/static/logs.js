/* ==========================================================================
   LexiPress Admin · logs.js
   SSE 实时日志终端：自动重连、级别过滤、自动滚动、任务进度。
   ========================================================================== */
(function () {
  'use strict';

  var A = window.ADMIN || {};
  var outEl = document.querySelector('[data-role="terminal-out"]');
  if (!outEl) return;

  var connLabel = document.querySelector('[data-role="connection-label"]');
  var autoscroll = true;
  var levelFilter = 'ALL';
  var source = null;
  var retryDelay = 1200;
  var retryTimer = null;
  var seenKeys = new Set();

  var autoscrollBtn = document.querySelector('[data-action="toggle-autoscroll"]');
  var clearBtn = document.querySelector('[data-action="clear-log"]');

  /* ----------------------------------------------------------------------
     渲染一行
     ---------------------------------------------------------------------- */
  function lineKey(entry) {
    return (entry.ts || '') + '|' + (entry.level || '') + '|' + (entry.message || '');
  }

  function appendLine(entry, opts) {
    var options = opts || {};
    if (!options.force) {
      var key = lineKey(entry);
      if (seenKeys.has(key)) return;
      seenKeys.add(key);
    }

    var level = String(entry.level || 'INFO').toUpperCase();
    if (levelFilter !== 'ALL' && level !== levelFilter) return;

    var row = document.createElement('div');
    row.className = 'terminal__line terminal__line--' + level;

    var ts = document.createElement('span');
    ts.className = 'terminal__ts';
    ts.textContent = (entry.ts || '').replace('T', ' ').slice(5, 19);

    var lvl = document.createElement('span');
    lvl.className = 'terminal__lvl terminal__lvl--' + level;
    lvl.textContent = level;

    var msg = document.createElement('span');
    msg.className = 'terminal__msg';
    msg.textContent = entry.message || '';

    row.appendChild(ts);
    row.appendChild(lvl);
    row.appendChild(msg);
    outEl.appendChild(row);

    // 限制 DOM 规模，避免长时间运行卡顿
    while (outEl.childElementCount > 1200) {
      outEl.removeChild(outEl.firstElementChild);
    }

    if (autoscroll) {
      outEl.scrollTop = outEl.scrollHeight;
    }
  }

  function rerender() {
    var raw = Array.from(outEl.children).map(function (node) {
      return {
        ts: node.querySelector('.terminal__ts') ? node.querySelector('.terminal__ts').textContent : '',
        level: node.querySelector('.terminal__lvl') ? node.querySelector('.terminal__lvl').textContent : 'INFO',
        message: node.querySelector('.terminal__msg') ? node.querySelector('.terminal__msg').textContent : ''
      };
    });
    outEl.innerHTML = '';
    raw.forEach(function (entry) {
      appendLine(entry, { force: true });
    });
  }

  /* ----------------------------------------------------------------------
     SSE
     ---------------------------------------------------------------------- */
  function setConnection(text) {
    if (connLabel) connLabel.textContent = text;
  }

  function connect() {
    if (source) {
      try {
        source.close();
      } catch (e) {
        /* ignore */
      }
    }
    setConnection('Connecting…');
    source = new EventSource('/api/logs/stream');

    source.addEventListener('open', function () {
      setConnection('Connected · LIVE');
      retryDelay = 1200;
    });

    source.addEventListener('history', function (event) {
      try {
        var payload = JSON.parse(event.data);
        (payload.items || []).forEach(function (entry) {
          appendLine(entry);
        });
        if (payload.tasks && A.updateTaskBadges) A.updateTaskBadges(payload.tasks);
      } catch (e) {
        /* ignore malformed frame */
      }
    });

    source.addEventListener('log', function (event) {
      try {
        appendLine(JSON.parse(event.data));
      } catch (e) {
        /* ignore */
      }
    });

    source.addEventListener('error', function () {
      setConnection('Reconnecting…');
      try {
        source.close();
      } catch (e) {
        /* ignore */
      }
      if (retryTimer) clearTimeout(retryTimer);
      retryTimer = setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 1.6, 8000);
    });
  }

  /* ----------------------------------------------------------------------
     控件
     ---------------------------------------------------------------------- */
  document.querySelectorAll('.terminal__filter').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.querySelectorAll('.terminal__filter').forEach(function (b) {
        b.classList.toggle('is-active', b === btn);
      });
      levelFilter = btn.getAttribute('data-level') || 'ALL';
      rerender();
    });
  });

  if (autoscrollBtn) {
    autoscrollBtn.addEventListener('click', function () {
      autoscroll = !autoscroll;
      autoscrollBtn.textContent = '自动滚动：' + (autoscroll ? '开' : '关');
      if (autoscroll) outEl.scrollTop = outEl.scrollHeight;
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', async function () {
      outEl.innerHTML = '';
      seenKeys.clear();
      try {
        await A.api('/api/logs/clear', { method: 'POST' });
      } catch (e) {
        /* 本地已清空即可 */
      }
    });
  }

  // 用户上滑时自动关闭 autoscroll，回到底部再打开
  outEl.addEventListener('scroll', function () {
    var atBottom = outEl.scrollHeight - outEl.scrollTop - outEl.clientHeight < 24;
    if (!atBottom && autoscroll) {
      autoscroll = false;
      if (autoscrollBtn) autoscrollBtn.textContent = '自动滚动：关';
    } else if (atBottom && !autoscroll) {
      autoscroll = true;
      if (autoscrollBtn) autoscrollBtn.textContent = '自动滚动：开';
    }
  });

  // 页面隐藏时断开，回来时重连，节省资源
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      if (source) {
        try {
          source.close();
        } catch (e) {
          /* ignore */
        }
        setConnection('Paused');
      }
    } else {
      connect();
    }
  });

  connect();
})();
