import sys, json, base64, re
d = json.load(sys.stdin)
content = base64.b64decode(d['content']).decode()
# find the opus 4.7 / 4.6 / temperature sections
# print all function defs that mention 'opus' or temperature
patterns = sys.argv[1:] if len(sys.argv) > 1 else ['opus', 'temperature', 'supports_temperature']
for p in patterns:
    print('### search:', p)
    for m in re.finditer(p, content, re.IGNORECASE):
        start = max(0, m.start()-200)
        end = min(len(content), m.end()+600)
        print('----')
        print(content[start:end])
    print()
