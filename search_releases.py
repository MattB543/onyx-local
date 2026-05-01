import sys, json
d = json.load(sys.stdin)
for r in d:
    name = r.get('name') or r.get('tag_name')
    tag = r.get('tag_name')
    date = r.get('published_at')
    body = r.get('body') or ''
    rel = False
    if '2026-04' in (date or '') or '2026-03' in (date or ''):
        rel = True
    if any(k in body.lower() for k in ['opus', '4.7', '4-7']):
        rel = True
    if rel:
        print(tag, '|', date)
        lines = body.split('\n')
        for ln in lines:
            if any(k in ln.lower() for k in ['temperature', 'opus', '4.7', '4-7', 'thinking', 'reasoning', 'adaptive', 'effort']):
                print('   >', ln[:250])
        print()
