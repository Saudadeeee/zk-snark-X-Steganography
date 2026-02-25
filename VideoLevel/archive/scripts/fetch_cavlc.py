import urllib.request
import json
import os
import sys

# Github search API to find 'cavlc_tables.py'
req = urllib.request.Request('https://api.github.com/search/code?q=COEFF_TOKEN_NC_0_1+language:python', headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as response:
        content = response.read().decode('utf-8')
        data = json.loads(content)
        if data['items']:
            item = data['items'][0]
            print(f"Found in {item['repository']['full_name']} / {item['path']}")
            url = item['html_url'].replace('github.com', 'raw.githubusercontent.com').replace('/blob/', '/')
            print(url)
            
            # Download it
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})) as r2:
                with open('downloaded_cavlc_tables.py', 'w') as f:
                    f.write(r2.read().decode('utf-8'))
            print('Downloaded successfully!')
        else:
            print('No results found.')
except Exception as e:
    print('Failed:', e)
