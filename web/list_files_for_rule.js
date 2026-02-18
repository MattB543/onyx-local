const fs = require('fs');
const data = JSON.parse(fs.readFileSync(require('path').join(__dirname, 'eslint_out.json'), 'utf8'));
const targetRule = process.argv[2];
if (!targetRule) { console.error('Usage: node list_files_for_rule.js <rule>'); process.exit(1); }
const files = new Set();
data.forEach(f => {
  f.messages.forEach(m => {
    if (m.ruleId === targetRule) {
      const rel = f.filePath.replace(/\\/g, '/').replace(/.*\/web\//, '');
      files.add(rel);
    }
  });
});
files.forEach(f => console.log(f));
