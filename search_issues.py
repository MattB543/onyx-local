import sys, json
d = json.load(sys.stdin)
for i in d.get('items', []):
    print(i['number'], i['state'], '-', i['title'], '-', i['html_url'])
