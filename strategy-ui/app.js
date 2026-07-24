/* QuantHub · 策略模块原型 · 共享交互
   UI Designer — 轻交互：主题 / Tab / 分段 / 行展开 / 筛选联动
   尊重 prefers-reduced-motion */
(function () {
  'use strict'

  /* ---------- 主题切换（暗 / 亮 / 跟随系统） ---------- */
  var root = document.documentElement
  var saved = localStorage.getItem('qh-theme') || 'dark'
  applyTheme(saved)
  function applyTheme(mode) {
    var sys = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    var eff = mode === 'system' ? sys : mode
    root.setAttribute('data-theme', eff)
    document.querySelectorAll('[data-theme-btn]').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-theme-btn') === mode)
    })
    var label = document.querySelector('[data-theme-label]')
    if (label) label.textContent = mode === 'system' ? '跟随系统' : mode === 'dark' ? '暗色' : '亮色'
  }
  document.querySelectorAll('[data-theme-btn]').forEach(function (b) {
    b.addEventListener('click', function () {
      var mode = b.getAttribute('data-theme-btn')
      localStorage.setItem('qh-theme', mode)
      applyTheme(mode)
    })
  })
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
    if ((localStorage.getItem('qh-theme') || 'dark') === 'system') applyTheme('system')
  })

  /* ---------- Tab 切换（事件委托） ---------- */
  document.addEventListener('click', function (e) {
    var tab = e.target.closest('[data-tab]')
    if (tab) {
      var group = tab.getAttribute('data-tab-group') || 'default'
      var name = tab.getAttribute('data-tab')
      document.querySelectorAll('[data-tab][data-tab-group="' + group + '"]').forEach(function (t) {
        t.classList.toggle('active', t === tab)
      })
      document.querySelectorAll('[data-tab-panel][data-tab-group="' + group + '"]').forEach(function (p) {
        p.classList.toggle('active', p.getAttribute('data-tab-panel') === name)
      })
      return
    }
    /* ---------- 分段控件 ---------- */
    var seg = e.target.closest('[data-seg]')
    if (seg) {
      seg.parentElement.querySelectorAll('[data-seg]').forEach(function (s) { s.classList.remove('active') })
      seg.classList.add('active')
      var key = seg.parentElement.getAttribute('data-seg-group') || 'view'
      document.dispatchEvent(new CustomEvent('segchange', { detail: { group: key, value: seg.getAttribute('data-seg') } }))
      if (key === 'view') {
        var t = document.querySelector('[data-view-target]')
        if (t) t.classList.toggle('list-view', seg.getAttribute('data-seg') === 'list')
      }
      if (key === 'sigview') {
        var v = seg.getAttribute('data-seg')
        document.querySelectorAll('[data-pane]').forEach(function (p) {
          p.classList.toggle('hide', p.getAttribute('data-pane') !== v)
        })
      }
      if (key === 'dir') {
        var d = seg.getAttribute('data-seg')
        document.querySelectorAll('.sig-row').forEach(function (r) {
          r.style.display = (d === 'all' || r.getAttribute('data-dir') === d) ? '' : 'none'
        })
      }
      return
    }
    /* ---------- 信号行展开 ---------- */
    var row = e.target.closest('[data-sig-row] .head')
    if (row) { row.parentElement.classList.toggle('open'); return }
    /* ---------- 通用折叠面板 ---------- */
    var tog = e.target.closest('[data-toggle-panel]')
    if (tog) {
      var id = tog.getAttribute('data-toggle-panel')
      var el = document.getElementById(id)
      if (el) el.classList.toggle('hide')
      return
    }
  })

  /* ---------- 即时筛选（根据 data-filter 属性联动表格/列表） ---------- */
  function bindFilter(input, targetSel, matchFn) {
    input.addEventListener('input', function () {
      var q = input.value.trim().toLowerCase()
      document.querySelectorAll(targetSel).forEach(function (row) {
        var hit = !q || matchFn(row, q)
        row.style.display = hit ? '' : 'none'
      })
    })
  }
  document.querySelectorAll('[data-filter-search]').forEach(function (inp) {
    var sel = inp.getAttribute('data-filter-search')
    bindFilter(inp, sel, function (row, q) {
      return (row.textContent || '').toLowerCase().includes(q)
    })
  })
  document.querySelectorAll('[data-filter-select]').forEach(function (sel) {
    var target = sel.getAttribute('data-filter-select')
    var colAttr = sel.getAttribute('data-col')
    sel.addEventListener('change', function () {
      var v = sel.value
      document.querySelectorAll(target).forEach(function (row) {
        var cell = row.querySelector('[data-' + colAttr + ']')
        var val = cell ? cell.getAttribute('data-' + colAttr + '') : ''
        row.style.display = !v || val === v ? '' : 'none'
      })
    })
  })

  /* ---------- 快速运行（原型态：乐观按钮反馈） ---------- */
  document.addEventListener('click', function (e) {
    var run = e.target.closest('[data-run]')
    if (!run) return
    var orig = run.textContent
    run.disabled = true
    run.textContent = '运行中…'
    setTimeout(function () {
      run.disabled = false
      run.textContent = orig
      var tip = document.querySelector('[data-run-tip]')
      if (tip) { tip.textContent = '最近运行：刚刚 · 已生成 ' + (3 + Math.floor(Math.random() * 6)) + ' 条信号'; }
    }, 1100)
  })

  /* ---------- 行内收藏切换 ---------- */
  document.addEventListener('click', function (e) {
    var fav = e.target.closest('[data-fav]')
    if (!fav) return
    e.stopPropagation()
    fav.classList.toggle('on')
    fav.textContent = fav.classList.contains('on') ? '★ 已收藏' : '☆ 收藏'
  })
})()
