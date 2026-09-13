import pathlib

p = pathlib.Path('desktop-dashboard/index.html')
content = p.read_text(encoding='utf-8')

# Conflict 1: createGlowTexture function signature
old1 = '<<<<<<< HEAD\n  // Dark = original amber/orange glow, light = cyan/blue glow (same falloff curve)\n  function createGlowTexture(isLight) {\n=======\n  function createGlowTexture(blue) {\n>>>>>>> a29be3dc60710d4ce21fdc93a70f084846fa1784'
new1 = '  // Dark = original amber/orange glow, light = cyan/blue glow (same falloff curve)\n  function createGlowTexture(isLight) {'
if old1 in content:
    content = content.replace(old1, new1)
    print('Fixed conflict 1')
else:
    print('Conflict 1 not found!')

# Conflict 2: Color stops inside createGlowTexture
old2 = '<<<<<<< HEAD\n    if (isLight) {\n      grad.addColorStop(0, \'rgba(120, 220, 255, 1)\');\n      grad.addColorStop(0.1, \'rgba(40, 165, 255, 0.8)\');\n      grad.addColorStop(0.3, \'rgba(22, 119, 255, 0.4)\');\n      grad.addColorStop(0.5, \'rgba(15, 77, 200, 0.15)\');\n      grad.addColorStop(0.7, \'rgba(5, 40, 120, 0.05)\');\n    } else {\n      grad.addColorStop(0, \'rgba(255, 200, 100, 1)\');\n      grad.addColorStop(0.1, \'rgba(255, 150, 50, 0.8)\');\n      grad.addColorStop(0.3, \'rgba(255, 100, 30, 0.4)\');\n      grad.addColorStop(0.5, \'rgba(255, 80, 20, 0.15)\');\n      grad.addColorStop(0.7, \'rgba(200, 50, 10, 0.05)\');\n    }\n=======\n    const glowStops = blue\n      ? [\'rgba(180,225,255,1)\', \'rgba(80,175,255,.8)\', \'rgba(22,119,255,.4)\', \'rgba(15,90,220,.15)\', \'rgba(6,59,120,.05)\']\n      : [\'rgba(255,200,100,1)\', \'rgba(255,150,50,.8)\', \'rgba(255,100,30,.4)\', \'rgba(255,80,20,.15)\', \'rgba(200,50,10,.05)\'];\n    grad.addColorStop(0, glowStops[0]);\n    grad.addColorStop(0.1, glowStops[1]);\n    grad.addColorStop(0.3, glowStops[2]);\n    grad.addColorStop(0.5, glowStops[3]);\n    grad.addColorStop(0.7, glowStops[4]);\n>>>>>>> a29be3dc60710d4ce21fdc93a70f084846fa1784'
new2 = '    if (isLight) {\n      grad.addColorStop(0, \'rgba(120, 220, 255, 1)\');\n      grad.addColorStop(0.1, \'rgba(40, 165, 255, 0.8)\');\n      grad.addColorStop(0.3, \'rgba(22, 119, 255, 0.4)\');\n      grad.addColorStop(0.5, \'rgba(15, 77, 200, 0.15)\');\n      grad.addColorStop(0.7, \'rgba(5, 40, 120, 0.05)\');\n    } else {\n      grad.addColorStop(0, \'rgba(255, 200, 100, 1)\');\n      grad.addColorStop(0.1, \'rgba(255, 150, 50, 0.8)\');\n      grad.addColorStop(0.3, \'rgba(255, 100, 30, 0.4)\');\n      grad.addColorStop(0.5, \'rgba(255, 80, 20, 0.15)\');\n      grad.addColorStop(0.7, \'rgba(200, 50, 10, 0.05)\');\n    }'
if old2 in content:
    content = content.replace(old2, new2)
    print('Fixed conflict 2')
else:
    print('Conflict 2 not found!')


# Conflicts 3 & 4: glowTextureDark vs createGlowTexture(false) (two occurrences)
old3 = '<<<<<<< HEAD\n    map: glowTextureDark,\n=======\n    map: createGlowTexture(false),\n>>>>>>> a29be3dc60710d4ce21fdc93a70f084846fa1784'
new3 = '    map: createGlowTexture(false),'
count3 = content.count(old3)
if count3 > 0:
    content = content.replace(old3, new3)
    print(f'Fixed conflicts 3 & 4 ({count3} occurrences)')
else:
    print('Conflicts 3 & 4 not found!')

# Conflict 5: Neural theme application - combine both approaches
marker5 = '<<<<<<< HEAD\n  // ===== NEURAL CORE THEME COLORS ====='
if marker5 in content:
    start5 = content.find(marker5)
    end5_marker = '>>>>>>> a29be3dc60710d4ce21fdc93a70f084846fa1784'
    end5 = content.find(end5_marker, start5) + len(end5_marker)
    new5 = '''  // ===== NEURAL CORE THEME COLORS =====
  // Dark theme keeps the original orange palette; light theme switches the
  // neural core to the blue/cyan appearance. Only material colors and canvas
  // textures are swapped here -- geometry, sizes, positions, animation timing
  // and all movement stay exactly the same.
  const NEURAL_THEMES = {
    dark: {
      stars: 0xff8844, wash: 0x441100,
      innerCore: 0xff8800, center: 0xffcc44, halo: 0xff6600, outerHalo: 0xff4400,
      mainWire: 0xff8800, midWire: 0xffaa33, innerMesh1: 0xff9933, innerMesh2: 0xffbb44,
      orbits: [0xff8800, 0xffaa33, 0xff7700, 0xff9933, 0xffbb44],
      orbitParticles: 0xffaa44, scatterParticles: 0xff9933,
      ambient: 0xff6633, point: 0xff8833
    },
    light: {
      stars: 0x3fa8ff, wash: 0x001a44,
      innerCore: 0x1677ff, center: 0x0a3a8c, halo: 0x00c2ff, outerHalo: 0x1677ff,
      mainWire: 0x00d0ff, midWire: 0x2ea8ff, innerMesh1: 0x36c9ff, innerMesh2: 0x5fd8ff,
      orbits: [0x1677ff, 0x2e9bff, 0x0f6fe0, 0x39b1ff, 0x5cc8ff],
      orbitParticles: 0x33bbff, scatterParticles: 0x1e90ff,
      ambient: 0x3399ff, point: 0x3399ff
    }
  };
  const orbitMats = [orbit1.material, orbit2.material, orbit3.material, orbit4.material, orbit5.material];

  function applyNeuralTheme(isLight) {
    const t = isLight ? NEURAL_THEMES.light : NEURAL_THEMES.dark;
    starMat.color.setHex(t.stars);
    washMat.color.setHex(t.wash);
    innerCoreMat.color.setHex(t.innerCore);
    centerMat.color.setHex(t.center);
    haloMat.color.setHex(t.halo);
    outerHaloMat.color.setHex(t.outerHalo);
    mainWireMat.color.setHex(t.mainWire);
    midWireMat.color.setHex(t.midWire);
    innerMesh1Mat.color.setHex(t.innerMesh1);
    innerMesh2Mat.color.setHex(t.innerMesh2);
    orbitMats.forEach(function (m, i) { m.color.setHex(t.orbits[i]); });
    orbitParticleMat.color.setHex(t.orbitParticles);
    scatterMat.color.setHex(t.scatterParticles);
    ambientLight.color.setHex(t.ambient);
    pointLight.color.setHex(t.point);
    const sqTex = isLight ? squareTextureLight : squareTexture;
    if (orbitParticleMat.map !== sqTex) { orbitParticleMat.map = sqTex; orbitParticleMat.needsUpdate = true; }
    if (scatterMat.map !== sqTex) { scatterMat.map = sqTex; scatterMat.needsUpdate = true; }
    glowSpriteMat.map = createGlowTexture(isLight); glowSpriteMat.needsUpdate = true;
    innerGlowMat.map = createGlowTexture(isLight); innerGlowMat.needsUpdate = true;
  }
  // Exposed so the existing settings theme system (zsApplyTheme) can drive it.
  window.zyraSetNeuralTheme = applyNeuralTheme;
  // Also listen for theme-change events dispatched by the settings panel.
  document.body.addEventListener('zyra-theme-change', function(event) {
    applyNeuralTheme(event.detail && event.detail.theme === 'light');
  });
  applyNeuralTheme(document.body.classList.contains('zyra-light'));'''
    content = content[:start5] + new5 + content[end5:]
    print('Fixed conflict 5')
else:
    print('Conflict 5 not found!')
