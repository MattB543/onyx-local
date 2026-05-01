import sys, json
path = sys.argv[1]
name_filter = sys.argv[2] if len(sys.argv) > 2 else ''
d = json.load(open(path))
for f in d:
    if name_filter and name_filter not in f['filename']:
        continue
    print('==== FILE:', f['filename'])
    print(f.get('patch',''))
    print()
