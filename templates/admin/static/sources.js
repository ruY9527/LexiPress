/* ==========================================================================
   LexiPress Admin · sources.js
   源管理：启用开关、新增/编辑、删除、单源测试报告。
   ========================================================================== */
(function () {
  'use strict';

  var A = window.ADMIN || {};
  var api = A.api;
  var toast = A.toast;

  var rowsEl = document.querySelector('[data-role="source-rows"]');
  if (!rowsEl) return;

  var modal = document.querySelector('[data-role="source-modal"]');
  var testModal = document.querySelector('[data-role="test-modal"]');
  var editingId = null;

  /* ----------------------------------------------------------------------
     弹窗基础
     ---------------------------------------------------------------------- */
  function openModal(node) {
    if (node) node.classList.add('is-open');
  }

  function closeModal(node) {
    if (node) node.classList.remove('is-open');
  }

  document.querySelectorAll('[data-action="close-modal"]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      closeModal(modal);
    });
  });

  document.querySelectorAll('[data-action="close-test-modal"]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      closeModal(testModal);
    });
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      closeModal(modal);
      closeModal(testModal);
    }
  });

  [modal, testModal].forEach(function (node) {
    if (!node) return;
    node.addEventListener('click', function (event) {
      if (event.target === node) closeModal(node);
    });
  });

  /* ----------------------------------------------------------------------
     表单
     ---------------------------------------------------------------------- */
  var fields = {};
  document.querySelectorAll('[data-field]').forEach(function (input) {
    fields[input.getAttribute('data-field')] = input;
  });

  var weightRange = fields.weight;
  var weightValue = document.querySelector('[data-role="weight-value"]');
  if (weightRange && weightValue) {
    weightRange.addEventListener('input', function () {
      weightValue.textContent = Number(weightRange.value).toFixed(2);
    });
  }

  var typeSelect = fields.type;
  var hnFields = document.querySelector('[data-role="hn-fields"]');
  function syncHnFields() {
    if (!hnFields || !typeSelect) return;
    hnFields.hidden = typeSelect.value !== 'hackernews';
  }
  if (typeSelect) typeSelect.addEventListener('change', syncHnFields);

  function resetForm() {
    editingId = null;
    var title = document.querySelector('[data-role="modal-title"]');
    if (title) title.textContent = '新增订阅源';
    if (fields.id) {
      fields.id.value = '';
      fields.id.disabled = false;
    }
    if (fields.name) fields.name.value = '';
    if (fields.type) fields.type.value = 'rss';
    if (fields.url) fields.url.value = '';
    if (fields.category) fields.category.value = '';
    if (fields.weight) fields.weight.value = '0.85';
    if (weightValue) weightValue.textContent = '0.85';
    if (fields.min_score) fields.min_score.value = '180';
    if (fields.limit) fields.limit.value = '20';
    var err = document.querySelector('[data-role="modal-error"]');
    if (err) err.hidden = true;
    syncHnFields();
  }

  function fillForm(source) {
    editingId = source.id;
    var title = document.querySelector('[data-role="modal-title"]');
    if (title) title.textContent = '编辑订阅源 · ' + source.name;
    if (fields.id) {
      fields.id.value = source.id;
      fields.id.disabled = true;
    }
    if (fields.name) fields.name.value = source.name || '';
    if (fields.type) fields.type.value = source.type || 'rss';
    if (fields.url) fields.url.value = source.url || '';
    if (fields.category) fields.category.value = source.category || '';
    if (fields.weight) fields.weight.value = String(source.weight != null ? source.weight : 0.85);
    if (weightValue) weightValue.textContent = Number(source.weight || 0.85).toFixed(2);
    if (fields.min_score) fields.min_score.value = String(source.min_score || 180);
    if (fields.limit) fields.limit.value = String(source.limit || 20);
    syncHnFields();
  }

  async function fetchSource(sourceId) {
    var res = await api('/api/sources');
    var list = (res.data && res.data.sources) || [];
    return list.find(function (s) {
      return s.id === sourceId;
    });
  }

  function showFormError(message) {
    var err = document.querySelector('[data-role="modal-error"]');
    if (!err) return;
    err.textContent = message;
    err.hidden = false;
  }

  /* ----------------------------------------------------------------------
     新增
     ---------------------------------------------------------------------- */
  var addBtn = document.querySelector('[data-action="add-source"]');
  if (addBtn) {
    addBtn.addEventListener('click', function () {
      resetForm();
      openModal(modal);
      if (fields.name) fields.name.focus();
    });
  }

  var saveBtn = document.querySelector('[data-action="save-source"]');
  if (saveBtn) {
    saveBtn.addEventListener('click', async function () {
      var payload = {
        id: fields.id ? fields.id.value.trim().toLowerCase() : '',
        name: fields.name ? fields.name.value.trim() : '',
        type: fields.type ? fields.type.value : 'rss',
        url: fields.url ? fields.url.value.trim() : '',
        category: fields.category ? fields.category.value.trim() || 'General' : 'General',
        weight: fields.weight ? Number(fields.weight.value) : 0.85,
        min_score: fields.min_score ? Number(fields.min_score.value) : 180,
        limit: fields.limit ? Number(fields.limit.value) : 20
      };

      if (!payload.id || !payload.name) {
        showFormError('ID 与名称都不能为空');
        return;
      }
      if (payload.type === 'rss' && !payload.url) {
        showFormError('RSS 类型必须填写 Feed URL');
        return;
      }

      saveBtn.disabled = true;
      try {
        if (editingId) {
          var patch = Object.assign({}, payload);
          delete patch.id;
          await api('/api/sources/' + encodeURIComponent(editingId), { method: 'PATCH', body: patch });
          toast('已更新 ' + payload.name, 'ok');
        } else {
          await api('/api/sources', { method: 'POST', body: payload });
          toast('已新增 ' + payload.name, 'ok');
        }
        closeModal(modal);
        setTimeout(function () {
          window.location.reload();
        }, 500);
      } catch (e) {
        showFormError(e.message);
      } finally {
        saveBtn.disabled = false;
      }
    });
  }

  /* ----------------------------------------------------------------------
     行操作
     ---------------------------------------------------------------------- */
  rowsEl.querySelectorAll('tr[data-source-id]').forEach(function (tr) {
    var sourceId = tr.getAttribute('data-source-id');

    var toggle = tr.querySelector('[data-action="toggle-source"]');
    if (toggle) {
      toggle.addEventListener('click', async function () {
        var isOn = toggle.classList.contains('is-on');
        toggle.disabled = true;
        try {
          await api('/api/sources/' + encodeURIComponent(sourceId), {
            method: 'PATCH',
            body: { enabled: !isOn }
          });
          toggle.classList.toggle('is-on', !isOn);
          toggle.setAttribute('aria-pressed', String(!isOn));
          toast(sourceId + (isOn ? ' 已停用' : ' 已启用'), 'ok');
        } catch (e) {
          toast('切换失败：' + e.message, 'error');
        } finally {
          toggle.disabled = false;
        }
      });
    }

    var editBtn = tr.querySelector('[data-action="edit-source"]');
    if (editBtn) {
      editBtn.addEventListener('click', async function () {
        try {
          var src = await fetchSource(sourceId);
          if (!src) {
            toast('未找到该源', 'error');
            return;
          }
          fillForm(src);
          openModal(modal);
        } catch (e) {
          toast('读取失败：' + e.message, 'error');
        }
      });
    }

    var delBtn = tr.querySelector('[data-action="delete-source"]');
    if (delBtn) {
      delBtn.addEventListener('click', async function () {
        if (!window.confirm('确定删除采集源「' + sourceId + '」？该操作会写回 config/feeds.yaml。')) return;
        try {
          await api('/api/sources/' + encodeURIComponent(sourceId), { method: 'DELETE' });
          toast('已删除 ' + sourceId, 'ok');
          tr.remove();
        } catch (e) {
          toast('删除失败：' + e.message, 'error');
        }
      });
    }

    var testBtn = tr.querySelector('[data-action="test-source"]');
    if (testBtn) {
      testBtn.addEventListener('click', async function () {
        var body = document.querySelector('[data-role="test-body"]');
        if (body) body.innerHTML = '<p class="empty">正在试抓前 3 篇，请稍候…</p>';
        openModal(testModal);
        testBtn.disabled = true;
        try {
          var res = await api('/api/sources/' + encodeURIComponent(sourceId) + '/test', { method: 'POST' });
          renderTestReport(res.data || {}, res.message || '');
        } catch (e) {
          if (body) body.innerHTML = '<div class="alert alert--error">测试失败：' + A.escapeHtml(e.message) + '</div>';
        } finally {
          testBtn.disabled = false;
        }
      });
    }
  });

  function renderTestReport(report, message) {
    var body = document.querySelector('[data-role="test-body"]');
    if (!body) return;

    var html = '';
    html +=
      '<div class="alert ' + (report.ok ? 'alert--ok' : 'alert--error') + '">' +
      A.escapeHtml(message || (report.ok ? '测试通过' : '测试未通过')) +
      '</div>';

    html += '<div class="diag-grid">';
    html += cell('源名称', report.source_name || '—');
    html += cell('源 ID', report.source_id || '—');
    html += cell('发现条目', String(report.discovered_count || 0));
    html += cell('成功抽取', String(report.extracted_count || 0));
    html += cell('耗时', (report.latency_ms || 0).toFixed(0) + ' ms');
    html += cell('首篇词数', String(report.first_word_count || 0));
    html += cell('首篇段落', String(report.first_paragraphs || 0));
    html += cell('Feed 解析', report.feed_parsed ? '正常' : '未解析');
    html += '</div>';

    var samples = report.samples || [];
    if (samples.length) {
      html += '<div style="margin:14px 0 8px;font-family:var(--font-mono);font-size:0.58rem;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);">试抽样本</div>';
      html += '<div class="table-wrap"><table class="table table--compact"><thead><tr><th>标题</th><th>状态</th><th>词数</th><th>耗时方式</th></tr></thead><tbody>';
      samples.forEach(function (s) {
        html +=
          '<tr><td>' + A.escapeHtml(s.title || '(untitled)') +
          (s.error ? '<span class="table__title-meta" style="color:var(--error);">' + A.escapeHtml(s.error) + '</span>' : '') +
          '</td><td><span class="badge badge--' + A.escapeHtml(s.status || 'fetched') + '">' + A.escapeHtml(s.status || '—') + '</span></td>' +
          '<td class="mono">' + (s.word_count || 0) + '</td>' +
          '<td class="mono" style="font-size:0.68rem;">' + A.escapeHtml(s.method || '—') + '</td></tr>';
      });
      html += '</tbody></table></div>';
    }

    body.innerHTML = html;
  }

  function cell(label, value) {
    return (
      '<div class="diag-cell"><span class="diag-cell__label">' + A.escapeHtml(label) +
      '</span><span class="diag-cell__value">' + A.escapeHtml(value) + '</span></div>'
    );
  }

  syncHnFields();
})();
