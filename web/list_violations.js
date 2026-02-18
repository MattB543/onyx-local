const fs = require('fs');
const path = require('path');
const data = fs.readFileSync(path.join(__dirname, 'eslint_out.json'), 'utf8');
const results = JSON.parse(data);
const targetRule = process.argv[2];
if (!targetRule) {
  console.error('Usage: node list_violations.js <rule-name>');
  process.exit(1);
}
results.forEach(f => {
  const msgs = f.messages.filter(m => m.ruleId === targetRule);
  if (msgs.length > 0) {
    const relPath = f.filePath.replace(/\\/g, '/');
    msgs.forEach(m => {
      console.log(relPath + ':' + m.line + ':' + m.column + ' ' + m.message);
    });
  }
});
