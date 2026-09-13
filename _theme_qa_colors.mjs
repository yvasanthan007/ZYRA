import fs from 'node:fs';
import assert from 'node:assert/strict';

export default async function run(page, ui) {
  const root = 'C:/Users/Rakshanaa/Project/ZYRA';
  const originalText = fs.readFileSync(root + '/desktop-dashboard/index.html', 'utf8');
  const servedHtml = originalText
    .replace('    renderer.render(scene, camera);', '    window.__themeQA = { scene: scene, renderer: renderer, mainGroup: mainGroup, orbitParticleData: orbitParticleData, time: time };\n    renderer.render(scene, camera);');
  if (servedHtml === originalText) throw new Error('instrumentation anchor missing');
  console.log('[harness] served bytes', servedHtml.length);

  let source = servedHtml;
  await page.route('http://zyra-theme.test/**', route => {
    const request = route.request();
    console.log('[route]', request.resourceType(), request.url(), 'body=' + source.length);
    if (request.url() === 'http://zyra-theme.test/' && request.resourceType() === 'document') {
      return route.fulfill({ status: 200, contentType: 'text/html', body: servedHtml });
    }
    // The dashboard's own endpoints stay unreachable in this harness; only the
    // page itself is served, so no live backend is touched by the checks.
    return route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
  });
  await page.addInitScript(() => {
    try { localStorage.clear(); } catch (err) { /* storage unavailable */ }
  });
  async function load() {
    await page.goto('http://zyra-theme.test/').catch(() => {});
    await page.waitForTimeout(2500);
    const diagnostics = await page.evaluate(() => ({
      url: String(location.href),
      title: document.title,
      three: String(typeof window.THREE),
      boot: String(window.__boot),
      lastError: String(window.__lastError),
      html: document.body.innerHTML.length
    }));
    const scriptCount = await page.evaluate(() => document.scripts.length);
    const state = await page.evaluate(() => ({ three: String(typeof window.THREE), qa: String(typeof window.__themeQA), canvas: document.querySelectorAll('canvas').length }));
    console.log('[state]', JSON.stringify(state));
    try {
      await page.waitForFunction(() => window.__themeQA && document.querySelector('#set-voice-volume'), { timeout: 20000 });
    } catch (e) {
      throw new Error('dashboard did not mount: ' + JSON.stringify(diagnostics) + ' scripts=' + scriptCount);
    }
  }
  async function openSettings() {
    await page.waitForTimeout(1200);
    const snap = await ui.snapshot();
    const ref = snap.match(/@(e\d+) button "Open Settings"/)?.[1];
    assert.ok(ref, 'settings button not found; page=' + page.url() + ' snapshot=' + snap);
    await ui.click(ref);
    await page.locator('#settings-overlay.open').waitFor();
  }
  async function theme(value) {
    await page.evaluate(v => {
      const card = document.querySelector('.theme-card[data-theme-value="' + v + '"]');
      if (!card) throw new Error('theme card missing: ' + v);
      card.click();
    }, value);
    await page.waitForFunction(v => document.body.classList.contains('theme-light') === (v === 'light'), value);
    await page.waitForTimeout(300); // Let existing control-color transitions finish.
  }
  async function capture() {
    return page.evaluate(() => {
      const q = window.__themeQA;
      if (!q || !q.scene) throw new Error('core not present: theme-light=' + document.body.classList.contains('theme-light') + ' three=' + String(typeof window.THREE) + ' boot=' + String(window.__boot) + ' scripts=' + document.scripts.length + ' err=' + String(window.__lastError));
      const materials = [];
      q.scene.traverse(obj => {
        const m = obj.material;
        if (!m && !obj.isLight) return;
        const texture = m && m.map && m.map.image;
        materials.push({
          type: obj.type,
          color: (m ? m.color : obj.color).getHexString(),
          texture: texture && texture.getContext ? texture.toDataURL() : null,
          geometry: obj.geometry ? (obj.geometry.parameters || 'buffer') : null,
          count: obj.geometry && obj.geometry.attributes.position ? obj.geometry.attributes.position.count : null,
          size: m ? m.size : undefined,
          blending: m ? m.blending : undefined,
          wireframe: m ? m.wireframe : undefined
        });
      });
      const controls = Array.from(document.querySelectorAll('#settings-panel .settings-toggle')).map(el => {
        const c = getComputedStyle(el), knob = getComputedStyle(el, '::after');
        return { id: el.id, on: el.classList.contains('on'), background: c.backgroundColor, border: c.borderColor, glow: c.boxShadow, knob: knob.backgroundColor, knobGlow: knob.boxShadow, width: c.width, height: c.height };
      });
      const range = document.querySelector('#set-voice-volume');
      const layout = Array.from(document.querySelectorAll('#top-bar, #bottom-controls, #settings-panel, #settings-panel .settings-row, body > canvas')).map(el => {
        const r = el.getBoundingClientRect();
        return [el.id || el.tagName, Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];
      });
      return { materials, controls, layout, range: { background: getComputedStyle(range).background, value: range.value, fill: range.style.getPropertyValue('--volume-fill') } };
    });
  }
  async function freshCapture(tag) {
    await load();
    await openSettings();
    const state = await capture();
    state.console = 'mounted';
    state.tag = tag;
    return state;
  }
  const dark = await freshCapture('dark');
  for (const m of dark.materials) assert.ok(!['168bff', '0066cc', '38cfff'].includes(m.color), 'Dark core must stay orange: ' + m.type + ' = ' + m.color);
  for (const c of dark.controls) assert.equal(c.background, c.on ? 'rgba(255, 136, 68, 0.35)' : 'rgba(255, 136, 68, 0.15)', 'Dark toggle must keep the orange accent: ' + c.id + ' = ' + c.background);
  assert.ok(dark.range.background.includes('rgba(255, 136, 68, 0.2)'), 'Dark volume track must stay orange: ' + dark.range.background);
  const darkMaterials = JSON.parse(JSON.stringify(dark.materials));
  const darkControls = JSON.parse(JSON.stringify(dark.controls));
  await page.evaluate(() => {
    window.__originalObjects = [];
    window.__themeQA.scene.traverse(o => window.__originalObjects.push([o, o.geometry, o.material]));
    return window.__originalObjects.length;
  }).catch(() => null);
  await theme('light');
  const light = await capture();
  assert.deepEqual(light.layout, dark.layout, 'No theme-related layout changes');
  for (const c of light.controls) {
    assert.equal(c.background, c.on ? 'rgb(22, 119, 255)' : 'rgb(217, 226, 236)', c.id + ' track was ' + c.background + ' (on=' + c.on + ')');
    assert.equal(c.knob, 'rgb(255, 255, 255)', c.id + ' knob was ' + c.knob);
  }
  assert.ok(light.range.background.includes('rgb(22, 119, 255)') && light.range.background.includes('rgb(217, 226, 236)'), light.range.background);
  for (const m of light.materials) assert.ok(['168bff', '0066cc', '38cfff', '063b78'].includes(m.color), 'Unexpected warm material: ' + m.type + ' = ' + m.color);
  assert.notEqual(light.materials.find(m => m.texture).texture, darkMaterials.find(m => m.texture).texture, 'Light textures must be blue');
  const expectedTrack = c => c.on ? 'rgb(22, 119, 255)' : 'rgb(217, 226, 236)';
  await page.evaluate(() => {
    const input = document.querySelector('#set-accent');
    input.value = '#ff7700';
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  for (const c of (await capture()).controls) assert.equal(c.background, expectedTrack(c), 'custom accent override on ' + c.id);
  for (const id of ['set-voice-toggle', 'set-save-history', 'set-chat-sidebar']) {
    await page.evaluate(sel => document.querySelector(sel).click(), '#' + id);
    await page.waitForTimeout(300);
    const c = (await capture()).controls.find(x => x.id === id);
    assert.equal(c.background, expectedTrack(c), id + ' after click');
    assert.equal(c.knob, 'rgb(255, 255, 255)', id + ' knob after click');
    await page.evaluate(sel => document.querySelector(sel).click(), '#' + id);
  }
  for (const value of ['0', '37', '100', '80']) {
    await page.evaluate(v => {
      const input = document.querySelector('#set-voice-volume');
      input.value = v;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }, value);
    await page.waitForTimeout(150);
    const state = await capture();
    assert.equal(state.range.fill, value + '%', 'volume fill after ' + value);
    assert.equal(await page.evaluate(() => document.querySelector('#set-voice-volume-val').textContent), value + '%', 'volume label after ' + value);
  }
  await page.screenshot({ path: root + '/_theme_qa_light_settings.png' });
  await page.evaluate(() => document.querySelector('#settings-close').click());
  await page.waitForTimeout(900);
  await page.screenshot({ path: root + '/_theme_qa_light_core.png' });
  const alive = await page.evaluate(() => {
    const q = window.__themeQA;
    let i = 0, same = true, nodes = 0;
    q.scene.traverse(o => {
      nodes++;
      const before = window.__originalObjects[i++];
      same = same && !!before && before[0] === o && before[1] === o.geometry && before[2] === o.material;
    });
    return { same, nodes, recorded: window.__originalObjects.length, time: q.time, particleT: q.orbitParticleData[0].t };
  });
  assert.equal(alive.nodes, alive.recorded, 'Scene tree gained or lost nodes');
  assert.equal(alive.same, true, 'Objects, geometry and materials never replaced');
  await page.waitForFunction(t => window.__themeQA.time > t, alive.time);
  assert.ok(await page.evaluate(t => window.__themeQA.orbitParticleData[0].t > t, alive.particleT), 'animation still advancing');
  await openSettings();
  await page.evaluate(() => document.querySelector('#set-accent-reset').click());
  await theme('dark');
  const restored = await capture();
  assert.deepEqual(restored.materials, darkMaterials, 'Exact orange colors/textures restored');
  assert.deepEqual(restored.controls, darkControls, 'Exact orange toggle styling restored');
  await theme('light');
  await load();
  try {
    await page.waitForFunction(() => window.__themeQA && document.body.classList.contains('theme-light'), { timeout: 15000 });
  } catch (err) {
    throw new Error('saved light theme not restored on reload: ' + page.url() + ' bodyChars=' + (await page.evaluate(() => document.body.innerHTML.length)));
  }
  const afterReload = await capture();
  assert.equal(afterReload.materials[2].color, light.materials[2].color, 'Saved light theme not applied on startup: ' + JSON.stringify(afterReload.materials.slice(0, 6).map(m => m.color)) + ' vs ' + JSON.stringify(light.materials.slice(0, 6).map(m => m.color)) + ' stored=' + (await page.evaluate(() => String(localStorage.getItem('zyra.settings')))));
  await openSettings();
  await page.setViewportSize({ width: 700, height: 850 });
  const smallLight = (await capture()).layout;
  await theme('dark');
  assert.deepEqual((await capture()).layout, smallLight, 'Responsive layout unchanged between themes');
  return { passed: true, animationUnchanged: true, exactDarkBaselineAndRestoration: true, materialCount: light.materials.length, geometryAndObjectsPreserved: alive.same, toggles: light.controls, volumeTested: [0, 37, 100, 80], customAccentOverride: true, savedTheme: true, responsiveLayout: true, screenshots: ['_theme_qa_light_settings.png', '_theme_qa_light_core.png'] };
}
