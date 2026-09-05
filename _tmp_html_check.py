import re, sys
s = open('desktop-dashboard/index.html', encoding='utf-8').read()
ok = True
for tag in ['div', 'select', 'option', 'section', 'span', 'button', 'label', 'table', 'tr', 'td']:
    op = len(re.findall(r'<%s(?:\s|>)' % tag, s))
    cl = len(re.findall(r'</%s>' % tag, s))
    status = 'OK' if op == cl else 'MISMATCH'
    if op != cl:
        ok = False
    print(tag, op, cl, status)
sys.exit(0 if ok else 1)