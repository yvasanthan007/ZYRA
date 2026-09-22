const { app, BrowserWindow } = require("electron");
app.whenReady().then(() => {
  const w = new BrowserWindow({ width: 1400, height: 900, show: false });
  w.loadFile("desktop-dashboard/index.html").then(() => {
    setTimeout(async () => {
      try { await w.webContents.executeJavaScript("localStorage.setItem('zyra_seeded','1'); localStorage.setItem('zyra_onboarded','1');"); } catch (e) {}
      w.webContents.reload();
      setTimeout(async () => {
        try {
          await w.webContents.executeJavaScript(`
            document.querySelectorAll('.onboard,.onboarding,.overlay,.modal-backdrop').forEach(e=>e.remove());
            const b=document.getElementById('chat-mic');
            const c=b.getBoundingClientRect();
            JSON.stringify({mic:{x:Math.round(c.x),y:Math.round(c.y),w:Math.round(c.width)},count:document.querySelectorAll('#chat-mic').length})
          `).then(r=>console.log("MICINFO "+r)).catch(e=>console.log("ERR2 "+e.message));
        } catch (e) { console.log("ERR3 " + e.message); }
        setTimeout(async () => {
          const img = await w.webContents.capturePage();
          require("fs").writeFileSync("_shot_moved.png", img.toPNG());
          console.log("SHOT OK");
          app.exit(0);
        }, 3000);
      }, 3500);
    }, 2500);
  });
  w.webContents.on("console-message", (e, lv, msg) => console.log("CONSOLE: " + msg));
});
