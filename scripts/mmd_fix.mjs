/**
 * mmd_fix.mjs — нормализация Mermaid-файла.
 * - CRLF -> LF
 * - добавляет init-директиву, если её нет
 * - заменяет «одинокие» % на &#37; (кроме %XX и URL-энкодинга)
 */
import fs from 'fs';

const file = process.argv[2] || 'docs/menu_map.mmd';
if (!fs.existsSync(file)) {
  console.log(`[mmd_fix] not found: ${file}`);
  process.exit(0);
}
let s = fs.readFileSync(file, 'utf8');

// normalize EOL
s = s.replace(/\r\n/g, '\n');

// ensure init directive
if (!/^%%\{.*init.*\}%%/m.test(s)) {
  const init = "%%{init: {'theme':'default', 'flowchart':{'htmlLabels':false}}}%%\n";
  s = init + s;
}

// escape lone % (сохраняем % в URL и %XX)
s = s.replace(/(https?:\/\/[^\s]+)/g, m => m.replace(/%/g, '__PCT__'));
s = s.replace(/%(?![0-9A-Fa-f]{2})/g, '&#37;');
s = s.replace(/__PCT__/g, '%');

fs.writeFileSync(file, s, 'utf8');
console.log('[mmd_fix] normalized:', file);
