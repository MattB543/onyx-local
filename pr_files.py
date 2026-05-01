import sys, json
d = json.load(open(sys.argv[1]))
for f in d:
    print('FILE:', f['filename'], '(+'+str(f.get('additions',0))+' -'+str(f.get('deletions',0))+')')
