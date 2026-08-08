/**
 * Render carousel stills for a whole week.
 *
 *   node render-carousels.mjs <specDir> <outDir>
 *
 * Bundles the Remotion project ONCE and reuses it for every still, instead of
 * paying the bundle cost per image as `npx remotion still` does.
 */
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';
import {copyFileSync, mkdirSync, readFileSync, readdirSync, writeFileSync} from 'node:fs';
import {basename, extname, join, resolve} from 'node:path';

const specDir = resolve(process.argv[2]);
const outRoot = resolve(process.argv[3]);
const browserExecutable =
  process.env.REMOTION_BROWSER_EXECUTABLE ??
  '/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell';

const specs = readdirSync(specDir).filter((f) => f.endsWith('.json')).sort();
if (!specs.length) throw new Error(`no specs in ${specDir}`);

for (const file of specs) {
  const name = basename(file, extname(file));
  const specPath = join(specDir, file);
  const spec = JSON.parse(readFileSync(specPath, 'utf8'));

  // Root.tsx imports ./spec.json statically, so stage it before bundling.
  copyFileSync(specPath, join(process.cwd(), 'spec.json'));

  console.log(`bundling for ${name}...`);
  const serveUrl = await bundle({entryPoint: join(process.cwd(), 'src/index.ts')});
  const composition = await selectComposition({
    serveUrl,
    id: 'CarouselSlide',
    inputProps: {spec, index: 0},
    browserExecutable,
  });

  const dir = join(outRoot, name);
  mkdirSync(dir, {recursive: true});

  for (let i = 0; i < spec.slides.length; i++) {
    const n = String(i + 1).padStart(2, '0');
    await renderStill({
      // selectComposition bakes resolved props onto the composition object, so
      // passing inputProps alone renders slide 0 every time. Override props here.
      composition: {...composition, props: {spec, index: i}},
      serveUrl,
      output: join(dir, `slide_${n}.jpg`),
      imageFormat: 'jpeg',
      jpegQuality: 92,
      inputProps: {spec, index: i},
      browserExecutable,
    });
  }

  if (spec.caption || spec.hashtags) {
    const tags = (spec.hashtags ?? []).slice(0, 5).join(' ');
    writeFileSync(join(dir, 'caption.txt'), `${(spec.caption ?? '').trim()}\n\n${tags}\n`);
  }
  console.log(`  ${name}: ${spec.slides.length} slides -> ${dir}`);
}
console.log('done');
