/* ==========================================================================
   LexiPress Admin · articles.js
   候选池：多维筛选、分页、批量操作、右侧正文预览抽屉。
   ========================================================================== */
(function () {
  'use strict';

  var A = window.ADMIN || {};
  var api = A.api;
  var toast = A.toast;

  var rowsEl = document.querySelector('[data-role="article-rows"]');
  if (!rowsEl) return;

  var state = {
    status: 'all',
    source_id: 'all',
    q: '',
    sort: 'score',
    page: 1,
    page_size: 20,
    total: 0,
    pages: 1,
    selected: new Set()
  };

  var pageState = { current: null };

  /* ----------------------------------------------------------------------
     渲染
     ---------------------------------------------------------------------- */
  function statusBadge(status, label) {
    var cls = 'badge--' + (status || 'fetched');
    return '<span class="badge ' + cls + '">' + A.escapeHtml(label || status) + '</span>';
  }

  function renderRows(items) {
    rowsEl.innerHTML = '';
    if (!items.length) {
      var tr = document.createElement('tr');
      tr.innerHTML = '<td colspan="8" class="empty"><strong>没有符合条件的文章</strong>试试切换状态页签、清空搜索词，或运行一次采集。</td>';
      rowsEl.appendChild(tr);
      return;
    }

    items.forEach(function (item) {
      var tr = document.createElement('tr');
      tr.setAttribute('data-id', item.id);

      var statusCls = item.status || 'fetched';
      var canPreview = true;

      tr.innerHTML =
        '<td><input class="checkbox" type="checkbox" data-role="row-check" data-id="' + A.escapeHtml(item.id) + '"' +
        (state.selected.has(item.id) ? ' checked' : '') + ' aria-label="选择"></td>' +
        '<td>' +
        '<div class="table__title" data-action="preview">' + A.escapeHtml(item.title) + '</div>' +
        '<span class="table__title-meta">' + A.escapeHtml(item.id) + '</span>' +
        '</td>' +
        '<td style="font-size:0.78rem;color:var(--text-secondary);">' + A.escapeHtml(item.source_name || '—') + '</td>' +
        '<td class="mono" style="font-size:0.68rem;">' + A.escapeHtml(item.published_at || '—') + '</td>' +
        '<td class="mono" style="font-size:0.7rem;">' +
        (item.word_count || 0) +
        (item.read_time_min ? '<span class="table__title-meta">' + item.read_time_min + ' min</span>' : '') +
        '</td>' +
        '<td><span class="badge ' + A.scoreClass(item.score) + '">' + Number(item.score || 0).toFixed(1) + '</span></td>' +
        '<td>' + statusBadge(statusCls, item.status_label) + '</td>' +
        '<td>' +
        '<div class="table__actions">' +
        '<button class="btn btn--xs" data-action="preview">预览</button>' +
        (statusCls === 'fetched' || statusCls === 'shortlisted'
          ? '<button class="btn btn--xs" data-act="shortlist">★ 精选</button>'
          : '') +
        (statusCls === 'fetched' || statusCls === 'shortlisted' || statusCls === 'parsed'
          ? '<button class="btn btn--xs" data-act="parse">✨ 解析</button>'
          : '') +
        (statusCls === 'failed' || statusCls === 'paywalled'
          ? '<button class="btn btn--xs" data-act="refetch">↻ 重试</button>'
          : '') +
        (statusCls !== 'rejected' ? '<button class="btn btn--xs btn--danger" data-act="reject">✕</button>' : '') +
        '</div>' +
        '</td>';

      rowsEl.appendChild(tr);
    });

    bindRowActions();
    syncBatchBar();
  }

  /* ----------------------------------------------------------------------
     行事件
     ---------------------------------------------------------------------- */
  function bindRowActions() {
    rowsEl.querySelectorAll('tr[data-id]').forEach(function (tr) {
      var id = tr.getAttribute('data-id');

      tr.querySelectorAll('[data-action="preview"]').forEach(function (node) {
        node.addEventListener('click', function (event) {
          event.preventDefault();
          openPreview(id);
        });
      });

      tr.querySelectorAll('[data-act]').forEach(function (btn) {
        btn.addEventListener('click', function (event) {
          event.preventDefault();
          event.stopPropagation();
          var act = btn.getAttribute('data-act');
          if (act === 'shortlist') changeStatus(id, 'shortlisted');
          else if (act === 'reject') changeStatus(id, 'rejected');
          else if (act === 'refetch') refetch(id);
          else if (act === 'parse') parseOne(id);
        });
      });

      var check = tr.querySelector('[data-role="row-check"]');
      if (check) {
        check.addEventListener('change', function () {
          if (check.checked) state.selected.add(id);
          else state.selected.delete(id);
          syncBatchBar();
        });
      }
    });
  }

  /* ----------------------------------------------------------------------
     操作
     ---------------------------------------------------------------------- */
  async function changeStatus(id, status) {
    try {
      await api('/api/articles/' + encodeURIComponent(id) + '/status', {
        method: 'PATCH',
        body: { status: status }
      });
      toast('状态已更新为 ' + status, 'ok');
      load();
    } catch (e) {
      toast('更新失败：' + e.message, 'error');
    }
  }

  async function refetch(id) {
    try {
      toast('正在重新抓取…');
      var res = await api('/api/articles/' + encodeURIComponent(id) + '/refetch', { method: 'POST' });
      toast(res.message || '已重取', res.ok ? 'ok' : 'error');
      load();
    } catch (e) {
      toast('重取失败：' + e.message, 'error');
    }
  }

  async function parseOne(id) {
    try {
      toast('正在解析（LLM 或规则降级）…');
      var res = await api('/api/articles/' + encodeURIComponent(id) + '/parse', {
        method: 'POST',
        body: { publish: false }
      });
      toast(res.message || '解析完成', res.ok ? 'ok' : 'error');
      load();
    } catch (e) {
      toast('解析失败：' + e.message, 'error');
    }
  }

  /* ----------------------------------------------------------------------
     批量操作
     ---------------------------------------------------------------------- */
  function syncBatchBar() {
    var bar = document.querySelector('[data-role="batch-bar"]');
    var countEl = document.querySelector('[data-role="batch-count"]');
    if (!bar) return;
    var n = state.selected.size;
    if (countEl) countEl.textContent = String(n);
    bar.classList.toggle('is-open', n > 0);
  }

  document.querySelector('[data-action="batch-shortlist"]') &&
    document.querySelector('[data-action="batch-shortlist"]').addEventListener('click', function () {
      batchStatus('shortlisted');
    });
  document.querySelector('[data-action="batch-reject"]') &&
    document.querySelector('[data-action="batch-reject"]').addEventListener('click', function () {
      batchStatus('rejected');
    });
  document.querySelector('[data-action="batch-clear"]') &&
    document.querySelector('[data-action="batch-clear"]').addEventListener('click', function () {
      state.selected.clear();
      rowsEl.querySelectorAll('[data-role="row-check"]').forEach(function (c) {
        c.checked = false;
      });
      syncBatchBar();
    });
  document.querySelector('[data-action="batch-parse"]') &&
    document.querySelector('[data-action="batch-parse"]').addEventListener('click', async function () {
      var ids = Array.from(state.selected);
      if (!ids.length) return;
      try {
        toast('批量解析 ' + ids.length + ' 篇…');
        var res = await api('/api/articles/parse-batch', {
          method: 'POST',
          body: { ids: ids, publish: true }
        });
        toast(res.message || '批量解析完成', 'ok');
        state.selected.clear();
        load();
      } catch (e) {
        toast('批量解析失败：' + e.message, 'error');
      }
    });

  async function batchStatus(status) {
    var ids = Array.from(state.selected);
    if (!ids.length) return;
    try {
      await Promise.all(
        ids.map(function (id) {
          return api('/api/articles/' + encodeURIComponent(id) + '/status', {
            method: 'PATCH',
            body: { status: status }
          });
        })
      );
      toast('已批量更新 ' + ids.length + ' 篇 → ' + status, 'ok');
      state.selected.clear();
      load();
    } catch (e) {
      toast('批量更新失败：' + e.message, 'error');
      load();
    }
  }

  /* ----------------------------------------------------------------------
     预览抽屉
     ---------------------------------------------------------------------- */
  var drawer = document.querySelector('[data-role="drawer"]');
  var overlay = document.querySelector('[data-role="drawer-overlay"]');

  function openDrawer() {
    if (drawer) drawer.classList.add('is-open');
    if (overlay) overlay.classList.add('is-open');
    document.body.style.overflow = 'hidden';
  }

  function closeDrawer() {
    if (drawer) drawer.classList.remove('is-open');
    if (overlay) overlay.classList.remove('is-open');
    document.body.style.overflow = '';
  }

  document.querySelector('[data-action="close-drawer"]') &&
    document.querySelector('[data-action="close-drawer"]').addEventListener('click', closeDrawer);
  overlay && overlay.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeDrawer();
  });

  async function openPreview(id) {
    pageState.current = id;
    openDrawer();
    var titleEl = document.querySelector('[data-role="drawer-title"]');
    var metaEl = document.querySelector('[data-role="drawer-meta"]');
    var bodyEl = document.querySelector('[data-role="drawer-body"]');
    var footEl = document.querySelector('[data-role="drawer-foot"]');
    if (titleEl) titleEl.textContent = '加载中…';
    if (metaEl) metaEl.textContent = '';
    if (bodyEl) bodyEl.innerHTML = '<p class="empty">正在读取正文…</p>';
    if (footEl) footEl.innerHTML = '';

    try {
      var res = await api('/api/articles/' + encodeURIComponent(id));
      var row = res.data || {};
      renderPreview(row);
    } catch (e) {
      if (bodyEl) bodyEl.innerHTML = '<p class="alert alert--error">读取失败：' + A.escapeHtml(e.message) + '</p>';
    }
  }

  function renderPreview(row) {
    var titleEl = document.querySelector('[data-role="drawer-title"]');
    var metaEl = document.querySelector('[data-role="drawer-meta"]');
    var bodyEl = document.querySelector('[data-role="drawer-body"]');
    var footEl = document.querySelector('[data-role="drawer-foot"]');

    if (titleEl) titleEl.textContent = row.title || '(untitled)';
    if (metaEl) {
      metaEl.textContent =
        (row.source_name || '—') +
        ' · ' + (row.published_at || '—') +
        ' · ' + (row.word_count || 0) + ' words' +
        ' · 状态 ' + (row.status || '—');
    }

    var html = '';
    if (row.error_message) {
      html += '<div class="alert alert--error"><strong>抓取异常：</strong>' + A.escapeHtml(row.error_message) + '</div>';
    }
    if (row.has_parsed && row.parsed_summary) {
      var ps = row.parsed_summary;
      html +=
        '<div class="alert alert--ok">已生成精读资产：' +
        (ps.parser_mode === 'llm' ? 'LLM 模式' : '规则模式') +
        ' · 生词 ' + ps.vocab + ' · 长难句 ' + ps.sentences +
        ' · 已译段落 ' + ps.translated + '/' + ps.paragraphs +
        '</div>';
    }

    html += '<div class="diag-grid">';
    html += cell('来源', row.source_name || '—');
    html += cell('作者', row.author || '—');
    html += cell('发布时间', row.published_at || '—');
    html += cell('抓取时间', A.fmtTime(row.fetched_at));
    html += cell('词数 / 时长', (row.word_count || 0) + ' 词 · ' + (row.read_time_min || 0) + ' min');
    html += cell('推荐分', Number(row.score || 0).toFixed(2));
    html += cell('段落数', String(row.paragraph_count || 0));
    html += cell('状态', row.status_label || row.status || '—');
    html += '</div>';

    if (row.cover_image) {
      html +=
        '<div style="margin-bottom:14px;"><img src="' + A.escapeHtml(row.cover_image) +
        '" alt="cover" style="max-height:130px;border-radius:6px;border:1px solid var(--border-subtle);" referrerpolicy="no-referrer"></div>';
    }

    html += '<div style="margin:14px 0 8px;font-family:var(--font-mono);font-size:0.58rem;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);">清洗后正文预览</div>';
    var paragraphs = row.paragraphs || [];
    if (paragraphs.length) {
      html += '<div class="preview-body">';
      paragraphs.forEach(function (p, i) {
        html += '<p' + (i === 0 ? ' class="is-first"' : '') + '>' + A.escapeHtml(p) + '</p>';
      });
      html += '</div>';
    } else {
      html += '<p class="empty">没有可预览的正文段落。</p>';
    }

    if (bodyEl) bodyEl.innerHTML = html;

    var id = row.id;
    if (footEl) {
      footEl.innerHTML =
        (row.status !== 'shortlisted' ? '<button class="btn btn--sm" data-foot="shortlist">★ 设为精选</button>' : '') +
        '<button class="btn btn--sm btn--primary" data-foot="parse">✨ 立即解析</button>' +
        (row.canonical_url
          ? '<a class="btn btn--sm" href="' + A.escapeHtml(row.canonical_url) + '" target="_blank" rel="noopener">原文 ↗</a>'
          : '') +
        '<span class="spacer"></span>' +
        (row.status !== 'rejected' ? '<button class="btn btn--sm btn--danger" data-foot="reject">淘汰</button>' : '');

      footEl.querySelectorAll('[data-foot]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
          var act = btn.getAttribute('data-foot');
          if (act === 'shortlist') {
            await changeStatus(id, 'shortlisted');
            closeDrawer();
          } else if (act === 'reject') {
            await changeStatus(id, 'rejected');
            closeDrawer();
          } else if (act === 'parse') {
            await parseOne(id);
            closeDrawer();
          }
        });
      });
    }
  }

  function cell(label, value) {
    return (
      '<div class="diag-cell"><span class="diag-cell__label">' + A.escapeHtml(label) +
      '</span><span class="diag-cell__value">' + A.escapeHtml(value) + '</span></div>'
    );
  }

  /* ----------------------------------------------------------------------
     加载
     ---------------------------------------------------------------------- */
  async function load() {
    var params = new URLSearchParams({
      status: state.status,
      source_id: state.source_id,
      q: state.q,
      sort: state.sort,
      page: String(state.page),
      page_size: String(state.page_size)
    });
    try {
      var res = await api('/api/articles?' + params.toString());
      var data = res.data || {};
      state.total = data.total || 0;
      state.pages = data.pages || 1;
      renderRows(data.items || []);

      var info = document.querySelector('[data-role="pager-info"]');
      if (info) {
        info.textContent =
          '共 ' + state.total + ' 篇 · 第 ' + state.page + ' / ' + state.pages + ' 页';
      }
      var prev = document.querySelector('[data-action="prev-page"]');
      var next = document.querySelector('[data-action="next-page"]');
      if (prev) prev.disabled = state.page <= 1;
      if (next) next.disabled = state.page >= state.pages;
    } catch (e) {
      rowsEl.innerHTML = '<tr><td colspan="8" class="empty">加载失败：' + A.escapeHtml(e.message) + '</td></tr>';
    }
  }

  /* ----------------------------------------------------------------------
     筛选事件
     ---------------------------------------------------------------------- */
  document.querySelectorAll('[data-role="status-tabs"] .tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      document.querySelectorAll('[data-role="status-tabs"] .tab').forEach(function (t) {
        t.classList.toggle('is-active', t === tab);
      });
      state.status = tab.getAttribute('data-status');
      state.page = 1;
      state.selected.clear();
      load();
    });
  });

  var searchInput = document.querySelector('[data-role="search"]');
  if (searchInput) {
    var timer = null;
    searchInput.addEventListener('input', function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () {
        state.q = searchInput.value.trim();
        state.page = 1;
        load();
      }, 260);
    });
  }

  var sourceFilter = document.querySelector('[data-role="source-filter"]');
  if (sourceFilter) {
    sourceFilter.addEventListener('change', function () {
      state.source_id = sourceFilter.value;
      state.page = 1;
      load();
    });
  }

  var sortSelect = document.querySelector('[data-role="sort"]');
  if (sortSelect) {
    sortSelect.addEventListener('change', function () {
      state.sort = sortSelect.value;
      state.page = 1;
      load();
    });
  }

  var reloadBtn = document.querySelector('[data-action="reload"]');
  if (reloadBtn) reloadBtn.addEventListener('click', load);

  var prevBtn = document.querySelector('[data-action="prev-page"]');
  if (prevBtn) {
    prevBtn.addEventListener('click', function () {
      if (state.page > 1) {
        state.page -= 1;
        load();
      }
    });
  }

  var nextBtn = document.querySelector('[data-action="next-page"]');
  if (nextBtn) {
    nextBtn.addEventListener('click', function () {
      if (state.page < state.pages) {
        state.page += 1;
        load();
      }
    });
  }

  var checkAll = document.querySelector('[data-role="check-all"]');
  if (checkAll) {
    checkAll.addEventListener('change', function () {
      rowsEl.querySelectorAll('[data-role="row-check"]').forEach(function (c) {
        c.checked = checkAll.checked;
        var id = c.getAttribute('data-id');
        if (checkAll.checked) state.selected.add(id);
        else state.selected.delete(id);
      });
      syncBatchBar();
    });
  }

  load();
})();
