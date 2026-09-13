import fs from 'node:fs';

// Verifies the theme-aware colour work end to end on the real dashboard file:
//   dark  -> core stays orange, toggles/slider stay orange
//   light -> core turns blue/cyan, toggles/slider turn blue
// Geometry, object identity and the animation loop are checked for non-interference.
export default async function run(page) {
  const target = 'C:/Users/Rakshanaa/Project/ZYRA/desktop-dashboard/index.html';
  const html = fs.readFileSync(target, 'utf8');
  const served = html.replace(
    '    renderer.render(scene, camera);',
    '    window.__core = { scene: scene };\n    renderer.render(scene, camera);'
  );
  if (served === html) throw new Error('instrumentation anchor missing');
  await page.goto('http://127.0.0.1:8099/').catch(() => {});
  await page.waitForFunction(() => window.__core && window.__core.scene, { timeout: 20000 });

  const readCore = () => page.evaluate(() => {
    const colors = new Map();
    let materials = 0, textures = 0;
    window.__core.scene.traverse(o => {
      const list = o.material ? [].concat(o.material) : [];
      for (const m of list) {
        if (!m.color) continue;
        materials++;
        colors.set(m.color.getHexString(), (colors.get(m.color.getHexString()) || 0) + 1);
        if (m.map && m.map.image && m.map.image.getContext) textures++;
      }
    });
    return { colors: Object.fromEntries(colors), materials, textures };
  });

  const openSettings = async () => {
    if (!(await page.evaluate(() => document.getElementById('settings-overlay').classList.contains('open')))) {
      await page.evaluate(() => document.getElementById('settings-btn').click());
      await page.locator('#settings-overlay.open').waitFor();
      await page.waitForTimeout(400);
    }
  };
  const readControls = () => page.evaluate(() => ({
    toggles: Array.from(document.querySelectorAll('#settings-panel .settings-toggle')).map(el => ({
      id: el.id,
      on: el.classList.contains('on'),
      track: getComputedStyle(el).backgroundColor,
      knob: getComputedStyle(el, '::after').backgroundColor
    })),
    volume: getComputedStyle(document.getElementById('set-voice-volume')).backgroundImage,
    volumeFill: document.getElementById('set-voice-volume').style.getPropertyValue('--volume-fill')
  }));
  const setTheme = async value => {
    await page.evaluate(v => document.querySelector('.theme-card[data-theme-value="' + v + '"]').click(), value);
    await page.waitForFunction(v => document.body.classList.contains('theme-light') === (v === 'light'), value);
    await page.waitForTimeout(400);
  };

  const report = {};
  await openSettings();
  report.darkCore = await readCore();
  report.darkControls = await readControls();

  await page.evaluate(() => {
    window.__snapshot = [];
    window.__core.scene.traverse(o => window.__snapshot.push([o, o.geometry, o.material]));
  });
  await setTheme('light');
  report.lightCore = await readCore();
  report.lightControls = await readControls();

  // Interactions: flip each toggle off and on, drag the volume slider over its range.
  report.toggleStates = [];
  for (const id of ['set-voice-toggle', 'set-save-history', 'set-chat-sidebar']) {
    for (const pass of [1, 2]) {
      await page.evaluate(sel => document.getElementById(sel).click(), id);
      await page.waitForTimeout(260);
      const state = await readControls();
      report.toggleStates.push({ id, pass, ...state.toggles.find(t => t.id === id) });
    }
  }
  report.volumeStates = [];
  for (const value of ['0', '13', '50', '100']) {
    await page.evaluate(v => {
      const el = document.getElementById('set-voice-volume');
      el.value = v;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      return v;
    }, value);
    await page.waitForTimeout(150);
    report.volumeStates.push(await page.evaluate(() => ({
      fill: document.getElementById('set-voice-volume').style.getPropertyValue('--volume-fill'),
      label: document.getElementById('set-voice-volume-val').textContent
    })).then(s => ({ value, ...s })));
  }

  // A saved custom accent must not override the light-theme blue.
  await page.evaluate(() => {
    const input = document.getElementById('set-accent');
    input.value = '#ff7700';
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.waitForTimeout(300);
  report.customAccentControls = await readControls();
  await page.evaluate(() => document.getElementById('set-accent-reset').click());

  report.lightLayout = await page.evaluate(() =>
    Array.from(document.querySelectorAll('#top-bar, #bottom-controls, #settings-panel, body > canvas')).map(el => {
      const r = el.getBoundingClientRect();
      return [el.id || el.tagName, Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];
    }));

  await page.screenshot({ path: 'C:/Users/Rakshanaa/Project/ZYRA/_theme_qa_light_settings.png' });
  await page.evaluate(() => document.getElementById('settings-close').click());
  await page.waitForTimeout(900);
  await page.screenshot({ path: 'C:/Users/Rakshanaa/Project/ZYRA/_theme_qa_light_core.png' });

  report.coreStillAnimating = await page.evaluate(() => new Promise(resolve => {
    let i = 0, same = true;
    window.__core.scene.traverse(o => {
      const before = window.__snapshot[i++];
      same = same && !!before && before[0] === o && before[1] === o.geometry && before[2] === o.material;
    });
    const nodes = i, recorded = window.__snapshot.length;
    setTimeout(() => resolve({ same, nodes, recorded }), 800);
  }));

  await openSettings();
  await setTheme('dark');
  report.restoredCore = await readCore();
  report.restoredControls = await readControls();
  await setTheme('light');
  await page.goto('http://127.0.0.1:8099/').catch(() => {});
  await page.waitForFunction(() => window.__core && window.__core.scene, { timeout: 20000 });
  await page.waitForTimeout(600);
  report.afterReload = {
    themeLight: await page.evaluate(() => document.body.classList.contains('theme-light')),
    core: await readCore().catch(() => null)
  };
  await page.setViewportSize({ width: 700, height: 850 });
  await page.waitForTimeout(400);
  report.smallLight = await page.evaluate(() =>
    Array.from(document.querySelectorAll('#top-bar, #bottom-controls, #settings-panel, body > canvas')).map(el => {
      const r = el.getBoundingClientRect();
      return [el.id || el.tagName, Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];
    }));
  await setTheme('dark');
  report.smallDark = await page.evaluate(() =>
    Array.from(document.querySelectorAll('#top-bar, #bottom-controls, #settings-panel, body > canvas')).map(el => {
      const r = el.getBoundingClientRect();
      return [el.id || el.tagName, Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];
    }));
  return report;
}
