/* Custom ZYRA title bar renderer — injected only when running inside Electron. */
(function () {
  if (document.getElementById('zyra-titlebar')) return;
  document.body.classList.add('zyra-desktop');

  var bar = document.createElement('div');
  bar.id = 'zyra-titlebar';
  bar.innerHTML =
    '<div class="zyra-title-left">' +
      '<span class="zyra-title-logo">\u25C8</span>' +
      '<span>ZYRA</span>' +
      '<span class="zyra-title-sub">DESKTOP</span>' +
    '</div>' +
    '<div class="zyra-window-controls">' +
      '<button id="zyra-btn-min" class="zyra-win-btn" title="Minimize" aria-label="Minimize">&#9472;</button>' +
      '<button id="zyra-btn-max" class="zyra-win-btn" title="Maximize" aria-label="Maximize">&#9744;</button>' +
      '<button id="zyra-btn-close" class="zyra-win-btn" title="Close" aria-label="Close">&#10005;</button>' +
    '</div>';
  document.body.prepend(bar);

  function api() { return window.zyraAPI; }
  function bind(id, fn) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('click', function (e) { e.stopPropagation(); fn(); });
  }
  bind('zyra-btn-min', function () { if (api()) api().window.minimize(); });
  bind('zyra-btn-max', function () { if (api()) api().window.maximize(); });
  bind('zyra-btn-close', function () { if (api()) api().window.close(); });

  function syncIcon(maximized) {
    var btn = document.getElementById('zyra-btn-max');
    if (!btn) return;
    btn.innerHTML = maximized ? '&#10064;' : '&#9744;';
    btn.title = maximized ? 'Restore' : 'Maximize';
  }
  if (api() && api().window) {
    api().window.isMaximized().then(syncIcon).catch(function () {});
    if (api().window.onMaximizedChanged) api().window.onMaximizedChanged(syncIcon);
  }
})();
