import json, sys
path = sys.argv[1]
d = json.load(open(path))
for f in d:
    patch = f.get('patch','')
    if 'temperature' in patch.lower() or 'top_p' in patch.lower() or 'top_k' in patch.lower():
        print('FILE:', f['filename'])
        print(patch[:4000])
        print('---')
