/* ==========================================================================
   LexiPress Admin · admin.js（公共层）
   API 客户端、Toast、任务轮询、SSE 订阅、通用工具。
   ========================================================================== */
(function () {
  'use strict';

  var A = (window.ADMIN = window.ADMIN || {});
  A.page = A.page || 'dashboard';

  /* ----------------------------------------------------------------------
     API 客户端
     ---------------------------------------------------------------------- */
  async function api(path, options) {
    var opts = Object.assign({ headers: {} }, options || {});
    if (opts.body && typeof opts.body !== 'string') {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.body);
    }
    var res = await fetch(path, opts);
    var payload = null;
    try {
      payload = await res.json();
    } catch (e) {
      payload = { ok: false, message: 'HTTP ' + res.status };
    }
    if (!res.ok) {
      var msg = (payload && (payload.detail || payload.message)) || 'HTTP ' + res.status;
      var err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
      err.status = res.status;
      err.payload = payload;
      throw err;
    }
    return payload;
  }
  A.api = api;

  /* ----------------------------------------------------------------------
     Toast
     ---------------------------------------------------------------------- */
  var toastTimer = null;
  function toast(message, kind) {
    var el = document.querySelector('[data-role="toast"]');
    if (!el) return;
    el.textContent = message;
    el.className = 'toast is-visible' + (kind === 'error' ? ' is-error' : kind === 'ok' ? ' is-ok' : '');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      el.className = 'toast';
    }, 3200);
  }
  A.toast = toast;

  /* ----------------------------------------------------------------------
     工具
     ---------------------------------------------------------------------- */
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  A.el = el;

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  A.escapeHtml = escapeHtml;

  function scoreClass(score) {
    var s = Number(score) || 0;
    if (s >= 8) return 'badge--score-high';
    if (s >= 6) return 'badge--score-mid';
    return 'badge--score-low';
  }
  A.scoreClass = scoreClass;

  function fmtTime(iso) {
    if (!iso) return '—';
    return String(iso).replace('T', ' ').slice(0, 16);
  }
  A.fmtTime = fmtTime;

  /* ----------------------------------------------------------------------
     任务状态轮询（全局）
     ---------------------------------------------------------------------- */
  var TASK_LABELS = { crawl: '采集', parse: '解析', build: '构建' };

  function updateTaskBadges(states) {
    var running = [];
    Object.keys(states || {}).forEach(function (name) {
      if (states[name] && states[name].status === 'running') {
        running.push(TASK_LABELS[name] || name);
      }
    });

    var badge = document.querySelector('[data-role="global-task-badge"]');
    if (badge) {
      badge.hidden = running.length === 0;
      var text = badge.querySelector('[data-role="global-task-text"]');
      if (text) text.textContent = running.join(' / ') + ' 运行中';
    }

    var navDot = document.querySelector('[data-role="nav-running-dot"]');
    if (navDot) navDot.hidden = running.length === 0;

    var banner = document.querySelector('[data-role="run-banner"]');
    if (banner) {
      banner.hidden = running.length === 0;
      var bannerText = banner.querySelector('[data-role="run-banner-text"]');
      if (bannerText && running.length) {
        var name = Object.keys(states).find(function (k) {
          return states[k] && states[k].status === 'running';
        });
        var state = states[name] || {};
        bannerText.textContent =
          (TASK_LABELS[name] || name) +
          ' 运行中 · ' +
          (state.message || '') +
          (state.progress ? ' · ' + Math.round(state.progress) + '%' : '');
      }
    }

    var progressFill = document.querySelector('[data-role="run-progress"]');
    var progressText = document.querySelector('[data-role="run-progress-text"]');
    if (progressFill || progressText) {
      var anyState = null;
      Object.keys(states || {}).some(function (k) {
        if (states[k] && states[k].status === 'running') {
          anyState = states[k];
          return true;
        }
        return false;
      });
      var pct = anyState ? Math.round(anyState.progress || 0) : 0;
      if (progressFill) progressFill.style.width = pct + '%';
      if (progressText) progressText.textContent = pct + '%';
    }
  }
  A.updateTaskBadges = updateTaskBadges;

  var pollTimer = null;
  function startTaskPolling() {
    if (pollTimer) return;
    var tick = async function () {
      try {
        var res = await api('/api/tasks');
        var states = (res && res.data) || {};
        updateTaskBadges(states);
        A.tasks = states;
        document.dispatchEvent(new CustomEvent('admin:tasks', { detail: states }));
      } catch (e) {
        /* 静默：轮询失败不打断用户操作 */
      }
    };
    tick();
    pollTimer = setInterval(tick, 2500);
  }
  A.startTaskPolling = startTaskPolling;

  /* ----------------------------------------------------------------------
     触发采集（全局通用）
     ---------------------------------------------------------------------- */
  async function runCrawl() {
    try {
      await api('/api/crawl/run', { method: 'POST', body: { trigger_type: 'manual' } });
      toast('采集任务已启动，正在实时输出日志…', 'ok');
      startTaskPolling();
      if (A.page !== 'logs') {
        setTimeout(function () {
          window.location.href = '/logs';
        }, 900);
      }
    } catch (e) {
      if (e.status === 409) {
        toast('已有采集任务在运行，正在查看实时日志…');
        setTimeout(function () {
          window.location.href = '/logs';
        }, 900);
      } else {
        toast('启动失败：' + e.message, 'error');
      }
    }
  }
  A.runCrawl = runCrawl;

  /* ----------------------------------------------------------------------
     全局点击分发（供各页面复用）
     ---------------------------------------------------------------------- */
  document.addEventListener('click', function (event) {
    var target = event.target.closest('[data-action]');
    if (!target) return;
    var action = target.getAttribute('data-action');

    if (action === 'run-crawl') {
      event.preventDefault();
      var btn = target;
      if (btn.disabled) return;
      btn.disabled = true;
      runCrawl().finally(function () {
        setTimeout(function () {
          btn.disabled = false;
        }, 600);
      });
      return;
    }

    if (action === 'manual-fetch') {
      event.preventDefault();
      var input = document.querySelector('[data-role="manual-url"]');
      var url = input ? input.value.trim() : '';
      if (!url) {
        toast('请先粘贴文章 URL', 'error');
        return;
      }
      target.disabled = true;
      api('/api/articles/manual', { method: 'POST', body: { url: url } })
        .then(function (res) {
          if (res.ok) {
            toast(res.message || '已入库', 'ok');
            if (input) input.value = '';
            setTimeout(function () {
              window.location.href = '/articles';
            }, 900);
          } else {
            toast(res.message || '抓取未成功', 'error');
          }
        })
        .catch(function (e) {
          toast('抓取失败：' + e.message, 'error');
        })
        .finally(function () {
          target.disabled = false;
        });
      return;
    }
  });

  /* ----------------------------------------------------------------------
     启动
     ---------------------------------------------------------------------- */
  function boot() {
    startTaskPolling();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
