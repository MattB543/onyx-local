import sys, json
d = json.load(sys.stdin)
if isinstance(d, dict) and 'message' in d and 'tag_name' not in d:
    print('ERROR:', d.get('message'))
    sys.exit(0)
if isinstance(d, list):
    for t in d:
        name = t.get('name') or t.get('tag_name') or ''
        if 'opus' in name.lower() or '4-7' in name or '4.7' in name or '1.83' in name:
            print(name)
else:
    print('TAG:', d.get('tag_name'))
    print('NAME:', d.get('name'))
    print('PUB:', d.get('published_at'))
    print()
    print((d.get('body') or '')[:4000])
