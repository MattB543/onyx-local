import sys, json
d = json.load(sys.stdin)
for c in d:
    msg = c['commit']['message'].split('\n')[0]
    if any(k in msg.lower() for k in ['temperature', 'opus', '4.7', '4-7', 'reasoning', 'thinking']):
        print(c['sha'][:10], '-', msg)
