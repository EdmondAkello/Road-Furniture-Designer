// Render the user guide HTML to PDF: the cover without, and the body with, running headers.
// Usage: node tools/guide/render_pdf.js <input.html> <output.pdf> <version>
// Needs Playwright (Chromium) and pdfunite (poppler-utils).
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
const { execFileSync } = require('child_process');

(async () => {
  const [input, output, version] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file://' + path.resolve(input), { waitUntil: 'networkidle' });
  const style = 'font-family: Inter, sans-serif; font-size: 7pt; color: #5b6575; width: 100%; padding: 0 17mm;';
  const cover = output.replace(/\.pdf$/, '.cover.tmp.pdf');
  const body = output.replace(/\.pdf$/, '.body.tmp.pdf');
  const hide = await page.addStyleTag({ content: 'body > :not(.cover) { display: none !important; }' });
  await page.pdf({ path: cover, format: 'A4', printBackground: true, preferCSSPageSize: true });
  await hide.evaluate((node) => node.remove());
  await page.addStyleTag({ content: '.cover { display: none !important; }' });
  await page.pdf({
    path: body, format: 'A4', printBackground: true, preferCSSPageSize: true, displayHeaderFooter: true,
    headerTemplate: `<div style="${style} display:flex; justify-content:space-between;"><span>RoadSign Designer ${version} · <b style="color:#d9822b">Experimental · Demo</b></span><span>User Guide and Technical Manual</span></div>`,
    footerTemplate: `<div style="${style} display:flex; justify-content:space-between;"><span>In development for Howard Humphreys (East Africa) Ltd · Edmond Akello</span><span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>`,
  });
  execFileSync('pdfunite', [cover, body, output]);
  fs.unlinkSync(cover); fs.unlinkSync(body);
  await browser.close();
  console.log('wrote', output);
})();
