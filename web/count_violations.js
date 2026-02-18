const fs = require('fs');
const path = require('path');
const data = fs.readFileSync(path.join(__dirname, 'eslint_out.json'), 'utf8');
const results = JSON.parse(data);
const counts = {};
const excluded = ['import-x/order', 'import-x/no-duplicates', 'unused-imports/no-unused-vars', 'unused-imports/no-unused-imports', '@typescript-eslint/no-explicit-any'];
results.forEach(f => f.messages.forEach(m => {
  const rule = m.ruleId || 'parse-error';
  if (!excluded.includes(rule)) {
    counts[rule] = (counts[rule] || 0) + 1;
  }
}));
const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
sorted.forEach(([rule, count]) => console.log(count + '\t' + rule));
console.log('---');
console.log('Total target violations:', sorted.reduce((s, [,c]) => s + c, 0));
