// CSS 设计令牌静态门禁（Fail-Fast：任一违例即非零退出）
// 校验项：
//   1. var() 引用的自定义属性必须存在定义（定义域 = web/src 全部 CSS；
//      例外 = 从 TSX 内联 style 注入的自定义属性，自动扫描得出，不允许手工维护白名单）
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const webRoot = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const srcRoot = path.join(webRoot, 'src');

function walk(dir, exts) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(p, exts));
    else if (exts.some((e) => entry.name.endsWith(e))) out.push(p);
  }
  return out;
}

const cssFiles = walk(srcRoot, ['.css']);
const tsFiles = walk(srcRoot, ['.ts', '.tsx']);

const defined = new Set();
const used = new Map(); // name -> [file:line]
for (const f of cssFiles) {
  const rel = path.relative(srcRoot, f);
  const lines = fs.readFileSync(f, 'utf8').split(/\r?\n/);
  lines.forEach((line, i) => {
    for (const m of line.matchAll(/(--[A-Za-z0-9-]+)\s*:/g)) defined.add(m[1]);
    for (const m of line.matchAll(/var\(\s*(--[A-Za-z0-9-]+)/g)) {
      if (!used.has(m[1])) used.set(m[1], []);
      used.get(m[1]).push(rel + ':' + (i + 1));
    }
  });
}

// TSX 内联注入的自定义属性（style={{ '--x': ... }}）视为合法定义来源
const injected = new Set();
for (const f of tsFiles) {
  const s = fs.readFileSync(f, 'utf8');
  for (const m of s.matchAll(/['"](---?[A-Za-z0-9-]+)['"]\s*[:]/g)) injected.add(m[1]);
}

const errors = [];
for (const [name, sites] of used) {
  if (!defined.has(name) && !injected.has(name)) {
    errors.push('[undefined-var] ' + name + ' 被引用但未定义 -> ' + sites.slice(0, 4).join(', ') + (sites.length > 4 ? ' 等 ' + sites.length + ' 处' : ''));
  }
}
// 反向豁免说明：TSX 注入但 CSS 未消费属运行时动态样式，不检查。

if (errors.length) {
  console.error('CSS 门禁未通过：');
  for (const e of errors) console.error('  ' + e);
  process.exit(1);
}
console.log('lint-css: OK (' + cssFiles.length + ' css files, ' + used.size + ' referenced vars, ' + injected.size + ' inline-injected)');
