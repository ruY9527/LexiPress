/* ==========================================================================
   LexiPress Admin · publish.js
   构建状态、Git 同步面板、上线开关、重新解析、清单过滤。
   ========================================================================== */
(function () {
  'use strict';

  var A = window.ADMIN || {};
  var api = A.api;
  var toast = A.toast;

  /* ----------------------------------------------------------------------
     构建状态
     ---------------------------------------------------------------------- */
  async function loadSiteStatus() {
    try {
      var res = await api('/api/site/status');
      var d = res.data || {};
      set('[data-role="s-built"]', d.built_at || '—');
      set('[data-role="s-pages"]', d.article_pages != null ? String(d.article_pages) : '—');
      set('[data-role="s-nojekyll"]', d.has_nojekyll ? '✓ 已生成' : '✗ 缺失');
      set('[data-role="s-404"]', d.has_404 ? '✓ 已生成' : '✗ 缺失');
      set('[data-role="s-search"]', d.has_search_index ? '✓ 已生成' : '✗ 缺失');
      set('[data-role="s-size"]', d.size_kb ? d.size_kb + ' KB' : '—');

      var badge = document.querySelector('[data-role="dist-badge"]');
      if (badge) {
        badge.textContent = d.index_exists ? 'dist/ 已就绪' : 'dist/ 未构建';
        badge.className = 'badge ' + (d.index_exists ? 'badge--published' : 'badge--rejected');
      }
    } catch (e) {
      set('[data-role="s-built"]', '读取失败');
    }
  }

  function set(selector, text) {
    var el = document.querySelector(selector);
    if (el) el.textContent = text;
  }

  /* ----------------------------------------------------------------------
     构建
     ---------------------------------------------------------------------- */
  async function buildSite(btn) {
    if (btn) btn.disabled = true;
    try {
      toast('正在构建静态站…');
      var res = await api('/api/site/build', { method: 'POST', body: {} });
      toast(res.message || '构建完成', 'ok');
      await loadSiteStatus();
      if (A.startTaskPolling) A.startTaskPolling();
    } catch (e) {
      if (e.status === 409) toast('已有构建任务在运行', 'error');
      else toast('构建失败：' + e.message, 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  document.querySelectorAll('[data-action="build"]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      buildSite(btn);
    });
  });

  /* ----------------------------------------------------------------------
     Git 状态
     ---------------------------------------------------------------------- */
  async function loadGit() {
    var panel = document.querySelector('[data-role="git-panel"]');
    if (!panel) return;
    try {
      var res = await api('/api/git/status');
      var d = res.data || {};
      if (!d.is_repo) {
        panel.innerHTML = '<div class="alert alert--warn">' + A.escapeHtml(d.summary || '当前目录不是 Git 仓库') + '</div>';
        return;
      }

      var html = '';
      html += '<div class="row" style="margin-bottom:12px;">';
      html += '<span class="badge">branch · ' + A.escapeHtml(d.branch || '—') + '</span>';
      html +=
        '<span class="badge ' + (d.has_changes ? 'badge--shortlisted' : 'badge--published') + '">' +
        (d.has_changes ? (d.changed || []).length + ' 项待提交' : '工作区干净') +
        '</span>';
      html += '</div>';

      if (d.has_changes) {
        html += '<div class="preview-body" style="max-height:190px;font-family:var(--font-mono);font-size:0.7rem;background:#1b1d21;color:#c9ccd2;border-color:transparent;">';
        (d.changed || []).slice(0, 40).forEach(function (line) {
          html += '<div style="margin:0 0 2px;font-family:inherit;font-size:inherit;line-height:1.6;color:#c9ccd2;">' + A.escapeHtml(line) + '</div>';
        });
        if ((d.changed || []).length > 40) {
          html += '<div style="color:#7d818a;">… 还有 ' + ((d.changed || []).length - 40) + ' 项</div>';
        }
        html += '</div>';

        html += '<p style="margin:12px 0 6px;font-size:0.74rem;color:var(--text-muted);">一键复制提交命令：</p>';
        html +=
          '<div class="row row--tight"><input class="input input--grow" readonly value="' +
          A.escapeHtml(d.commit_hint || '') +
          '" data-role="commit-hint"><button class="btn btn--sm" data-action="copy-hint">复制</button></div>';
        html +=
          '<p style="margin:10px 0 0;font-size:0.72rem;color:var(--text-muted);line-height:1.7;">' +
          '推送后 <code>.github/workflows/deploy-site.yml</code> 会自动重建并发布，约 30 秒上线。' +
          '</p>';
      } else {
        html += '<p style="margin:0;font-size:0.8rem;color:var(--text-secondary);line-height:1.75;">' +
          '没有待提交的内容。若刚完成解析或构建，可先在上方生成静态站，再提交 <code>data/parsed/</code> 与 <code>data/index.json</code>。</p>';
      }

      panel.innerHTML = html;

      var copyBtn = panel.querySelector('[data-action="copy-hint"]');
      if (copyBtn) {
        copyBtn.addEventListener('click', async function () {
          var input = panel.querySelector('[data-role="commit-hint"]');
          if (!input) return;
          try {
            await navigator.clipboard.writeText(input.value);
            toast('已复制提交命令', 'ok');
          } catch (e) {
            input.select();
            toast('请手动复制（Ctrl+C）');
          }
        });
      }
    } catch (e) {
      panel.innerHTML = '<div class="alert alert--error">读取失败：' + A.escapeHtml(e.message) + '</div>';
    }
  }

  var refreshGit = document.querySelector('[data-action="refresh-git"]');
  if (refreshGit) refreshGit.addEventListener('click', loadGit);

  /* ----------------------------------------------------------------------
     文章清单操作
     ---------------------------------------------------------------------- */
  var rowsEl = document.querySelector('[data-role="publish-rows"]');
  if (rowsEl) {
    rowsEl.querySelectorAll('tr[data-article-id]').forEach(function (tr) {
      var id = tr.getAttribute('data-article-id');

      var toggle = tr.querySelector('[data-action="toggle-online"]');
      if (toggle) {
        toggle.addEventListener('click', async function () {
          var isOn = toggle.classList.contains('is-on');
          toggle.disabled = true;
          try {
            await api('/api/articles/' + encodeURIComponent(id) + '/publish', {
              method: 'POST',
              body: { online: !isOn }
            });
            toggle.classList.toggle('is-on', !isOn);
            toast(id + (isOn ? ' 已下线' : ' 已上线'), 'ok');
          } catch (e) {
            toast('操作失败：' + e.message, 'error');
          } finally {
            toggle.disabled = false;
          }
        });
      }

      var reparse = tr.querySelector('[data-action="reparse"]');
      if (reparse) {
        reparse.addEventListener('click', async function () {
          reparse.disabled = true;
          try {
            toast('重新解析中…');
            var res = await api('/api/articles/' + encodeURIComponent(id) + '/parse', {
              method: 'POST',
              body: { publish: true }
            });
            toast(res.message || '解析完成', 'ok');
          } catch (e) {
            toast('解析失败：' + e.message, 'error');
          } finally {
            reparse.disabled = false;
          }
        });
      }

      var preview = tr.querySelector('[data-action="open-article"]');
      if (preview) {
        preview.addEventListener('click', function () {
          window.open('/LexiPress/articles/' + encodeURIComponent(id) + '/', '_blank', 'noopener');
        });
      }
    });

    var search = document.querySelector('[data-role="publish-search"]');
    if (search) {
      search.addEventListener('input', function () {
        var q = search.value.trim().toLowerCase();
        rowsEl.querySelectorAll('tr[data-article-id]').forEach(function (tr) {
          var title = tr.getAttribute('data-title') || '';
          tr.style.display = !q || title.indexOf(q) >= 0 ? '' : 'none';
        });
      });
    }
  }

  /* ----------------------------------------------------------------------
     启动
     ---------------------------------------------------------------------- */
  loadSiteStatus();
  loadGit();
})();
