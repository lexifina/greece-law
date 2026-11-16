"""Fill page.tpl.html with data.json and write the page."""
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
data = open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, '.build', 'data.json'), encoding='utf-8').read()
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, '..', 'to-elliniko-dikaio-se-20-grafimata.html')
tpl = open(os.path.join(here, 'page.tpl.html'), encoding='utf-8').read()
json.loads(data)
page = tpl.replace('/*DATA*/null', data.replace('</', '<\\/'))  # no "</script>" inside the data
open(out, 'w', encoding='utf-8', newline='\n').write(page)
print(out, len(page))
