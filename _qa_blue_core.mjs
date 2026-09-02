export default async function run(page, ui) {
  await page.locator('#zyra-settings-btn').click();
  await page.locator('#zs-theme').selectOption('light');
  await page.waitForTimeout(100);
  return await page.evaluate(() => ({
    light: document.body.classList.contains('zyra-light'),
    theme: document.querySelector('#zs-theme')?.value,
    scheme: document.querySelector('#zs-color-scheme')?.value,
    canvasCount: document.querySelectorAll('canvas').length,
    bodyBackground: getComputedStyle(document.body).backgroundColor,
    inputBackground: getComputedStyle(document.querySelector('#chat-input')).backgroundColor,
    buttonBackground: getComputedStyle(document.querySelector('#btn-toggle-monitor')).backgroundImage,
    placeholder: document.querySelector('#chat-input')?.getAttribute('placeholder')
  }));
}