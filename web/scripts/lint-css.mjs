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

// ---- 校验 3：裸字号禁止（font-size 只允许走 tokens 阶梯；tokens.css 自身除外）----
for (const f of cssFiles) {
  if (f.endsWith('tokens.css')) continue;
  const rel = path.relative(srcRoot, f);
  const lines = fs.readFileSync(f, 'utf8').split(/\r?\n/);
  lines.forEach((line, i) => {
    for (const m of line.matchAll(/font-size:\s*[\d.]+(?:px|rem)/g)) {
      errors.push('[raw-font-size] ' + rel + ':' + (i + 1) + ' -> ' + m[0] + '（请改用 --fs-* 阶梯令牌）');
    }
  });
}

// ---- 校验 2：语义文字色对比度（tokens.css 双主题 *-ink 对 --bg / --bg-elevated ≥ 4.5:1）----
function relLuminance(hex) {
  const c = hex.replace('#', '');
  const rgb = [0, 2, 4].map((i) => parseInt(c.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)));
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
}
function contrast(a, b) {
  const [l1, l2] = [relLuminance(a), relLuminance(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}

const tokensFile = cssFiles.find((f) => f.endsWith('tokens.css'));
if (!tokensFile) {
  errors.push('[contrast] 未找到 tokens.css');
} else {
  const src = fs.readFileSync(tokensFile, 'utf8');
  // 按主题块切分：暗色 = :root 与 [data-theme='dark']；亮色 = [data-theme='light']
  const lightIdx = src.indexOf("[data-theme='light']");
  if (lightIdx < 0) {
    errors.push('[contrast] tokens.css 缺少亮色主题块');
  } else {
    const blocks = [
      { name: 'dark', text: src.slice(0, lightIdx) },
      { name: 'light', text: src.slice(lightIdx) },
    ];
    for (const block of blocks) {
      const vars = {};
      for (const m of block.text.matchAll(/(--[A-Za-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;/g)) vars[m[1]] = m[2];
      for (const ink of ['--up-ink', '--down-ink', '--warn-ink', '--info-ink']) {
        for (const bg of ['--bg', '--bg-elevated']) {
          if (!vars[ink] || !vars[bg]) continue; // 非字面量色值交由人工评审，不在静态门禁范围
          const r = contrast(vars[ink], vars[bg]);
          if (r < 4.5) {
            errors.push('[contrast] ' + block.name + ' ' + ink + '(' + vars[ink] + ') 对 ' + bg + '(' + vars[bg] + ') = ' + r.toFixed(2) + ':1 < 4.5:1');
          }
        }
      }
    }
  }
}

if (errors.length) {
  console.error('CSS 门禁未通过：');
  for (const e of errors) console.error('  ' + e);
  process.exit(1);
}
console.log('lint-css: OK (' + cssFiles.length + ' css files, ' + used.size + ' referenced vars, ' + injected.size + ' inline-injected)');
