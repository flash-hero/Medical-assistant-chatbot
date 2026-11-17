/**
 * SVG -> PNG through headless Chromium (Playwright, already a dev dependency), and PNG -> ICO.
 * Rendering in a real browser engine matches what visitors see; no native image library is needed.
 */
import { chromium } from "playwright";

export async function openRasterizer() {
  const browser = await chromium.launch();
  const context = await browser.newContext({ deviceScaleFactor: 1 });
  const page = await context.newPage();

  /** Render `svg` (a full <svg> document string) into a width x height PNG buffer. */
  async function svgToPng(svg, width, height) {
    if (!svg.trimStart().startsWith("<svg")) throw new Error("svgToPng expects an <svg> document");
    await page.setViewportSize({ width, height });
    const src = `data:image/svg+xml;base64,${Buffer.from(svg, "utf8").toString("base64")}`;
    await page.setContent(
      `<!doctype html><html><body style="margin:0;background:transparent">` +
        `<img src="${src}" width="${width}" height="${height}" style="display:block"></body></html>`,
    );
    await page.waitForFunction(() => document.images[0]?.complete && document.images[0].naturalWidth > 0);
    return page.screenshot({ type: "png", omitBackground: true, clip: { x: 0, y: 0, width, height } });
  }

  return { svgToPng, close: () => browser.close() };
}

/**
 * ICO container holding PNG-compressed images (supported by every current browser and by Windows
 * since Vista). `images` is [{ size, png }], sizes up to 256.
 */
export function pngsToIco(images) {
  if (images.length === 0) throw new Error("an ICO needs at least one image");
  const HEADER = 6;
  const ENTRY = 16;
  const header = Buffer.alloc(HEADER);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // type 1 = icon
  header.writeUInt16LE(images.length, 4);
  let offset = HEADER + ENTRY * images.length;
  const entries = images.map(({ size, png }) => {
    if (size < 1 || size > 256) throw new Error(`ICO image size out of range: ${size}`);
    const entry = Buffer.alloc(ENTRY);
    entry.writeUInt8(size === 256 ? 0 : size, 0);
    entry.writeUInt8(size === 256 ? 0 : size, 1);
    entry.writeUInt8(0, 2); // palette
    entry.writeUInt8(0, 3); // reserved
    entry.writeUInt16LE(1, 4); // colour planes
    entry.writeUInt16LE(32, 6); // bits per pixel
    entry.writeUInt32LE(png.length, 8);
    entry.writeUInt32LE(offset, 12);
    offset += png.length;
    return entry;
  });
  return Buffer.concat([header, ...entries, ...images.map((i) => i.png)]);
}
