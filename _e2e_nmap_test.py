"""Temporary end-to-end test for the ZYRA Nmap dashboard integration."""
import sys
import time
import json
import threading
import urllib.request

sys.path.insert(0, r'c:\Users\Rakshanaa\Project\ZYRA')

from backend.server import app  # noqa: E402
import uvicorn  # noqa: E402

BASE = 'http://127.0.0.1:8099'


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=15).read().decode())


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
    )
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())


def main():
    t = threading.Thread(
        target=lambda: uvicorn.run(app, host='127.0.0.1', port=8099, log_level='error'),
        daemon=True,
    )
    t.start()
    time.sleep(4)

    print('STATE:', json.dumps(get('/api/nmap/state'))[:220])
    ops = get('/api/nmap/operations')
    print('OPERATIONS:', [o['key'] for o in ops['operations']])
    print('OP SAMPLE:', json.dumps(ops['operations'][0])[:220])

    launch = post('/api/nmap/scan', {
        'operation': 'network_discovery',
        'target': '127.0.0.1',
        'request_text': 'Scan my network',
    })
    print('LAUNCH:', json.dumps(launch)[:220])

    st = {}
    sid = None
    for i in range(40):
        time.sleep(1)
        data = get('/api/nmap/state').get('data', {})
        st = data.get('active') or data.get('last') or {}
        sid = st.get('scan_id')
        print(f"  poll {i}: status={st.get('status')} progress={st.get('progress')} stage={st.get('stage')}")
        if st.get('status') in ('COMPLETE', 'ERROR'):
            break

    print('FINAL STATUS:', st.get('status'))
    print('SUMMARY:', json.dumps(st.get('summary')))
    print('COMMAND:', st.get('command'))
    print('OBSERVATIONS:', json.dumps(st.get('observations', [])[:4], indent=1))
    print('CHAT_RESPONSE:', st.get('chat_response'))

    if not sid:
        print('NO SCAN ID — aborting report tests')
        return

    # JSON report (machine readable)
    jdata = get(f'/api/nmap/report/{sid}?format=json')
    print('JSON REPORT TOP KEYS:', sorted(jdata.keys()))

    # TXT report (human readable)
    txt = urllib.request.urlopen(BASE + f'/api/nmap/report/{sid}?format=txt', timeout=15).read().decode()
    print('--- TXT REPORT HEAD ---')
    print('\n'.join(txt.splitlines()[:14]))
    print('-----------------------')

    # PDF report
    pdf = urllib.request.urlopen(BASE + f'/api/nmap/report/{sid}?format=pdf', timeout=30).read()
    print('PDF bytes:', len(pdf), 'header:', pdf[:5])

    # Invalid target (safety validation) — the API answers 400 Bad Request
    try:
        bad = post('/api/nmap/scan', {'operation': 'quick', 'target': 'not a target!!'})
        print('INVALID TARGET RESPONSE:', json.dumps(bad)[:200])
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print('INVALID TARGET -> HTTP', e.code, '(validation OK):', body[:160])

    print('E2E TEST DONE')


if __name__ == '__main__':
    main()
