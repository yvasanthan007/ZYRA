const { app, BrowserWindow } = require('electron');
app.whenReady().then(async () => {
  const win = new BrowserWindow({ width: 1280, height: 800, show: false });
  await win.loadFile('desktop-dashboard/index.html');
  await new Promise(r => setTimeout(r, 2500));
  const img = await win.capturePage();
  require('fs').writeFileSync('_shot_moved.png', img.toPNG());
  app.quit();
});
