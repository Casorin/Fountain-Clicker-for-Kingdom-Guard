// Render each Windows icon size directly from the SVG, not a resized bitmap.
const fs = require('node:fs');
const path = require('node:path');
const sharp = require(process.argv[2] || 'sharp');
const root = path.resolve(__dirname, '..');
const svg = fs.readFileSync(path.join(root, 'assets', 'fountain.svg'), 'utf8');
const output = path.join(root, 'runtime', 'icon-render');
fs.mkdirSync(output, { recursive: true });

(async () => {
  for (const size of [16, 24, 32, 48, 64, 128, 256, 1024]) {
    const source = svg.replace('width="512" height="512"', `width="${size}" height="${size}"`);
    await sharp(Buffer.from(source)).png().toFile(path.join(output, `${size}.png`));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
