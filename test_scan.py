import sys, time
sys.path.insert(0, '.')
from backend.url_analyzer import start_scan, get_scan, build_report_data, report_to_pdf, report_filename, report_to_text

# Test 1: Suspicious URL
print("=== TEST 1: Suspicious URL ===")
result = start_scan('http://login-paypal.secure-update.click/auth?session=abc123&return=http://evil.com', source='test')
scan_id = result['scan_id']
for i in range(20):
    time.sleep(1)
    s = get_scan(scan_id)
    if not s:
        continue
    if s.get('status') == 'COMPLETE' or s.get('status') == 'ERROR':
        break

s = get_scan(scan_id)
if s:
    res = s.get('result', {})
    if res:
        print(f"score: {res.get('score')}")
        print(f"risk_level: {res.get('risk_level')}")
        print(f"classification: {res.get('classification')}")
        findings = res.get('findings', [])
        print(f"findings ({len(findings)}):")
        for f in findings:
            print(f"  [{f.get('severity')}] {f.get('id')} - {f.get('title')}")
    else:
        print("ERROR:", s.get('error'))

# Test 2: Report generation
print("\n=== TEST 2: Report Generation ===")
if s and s.get('result'):
    report = build_report_data(s['result'])
    print("Report data keys:", list(report.keys()))
    filename = report_filename(s['result'])
    print("Filename:", filename)
    txt = report_to_text(report)
    print("Text report length:", len(txt))
    try:
        pdf = report_to_pdf(report)
        print("PDF generated, size:", len(pdf), "bytes")
    except Exception as e:
        print("PDF error:", e)

# Test 3: Invalid URL
print("\n=== TEST 3: Invalid URL ===")
result3 = start_scan('not-a-valid-url', source='test')
scan_id3 = result3['scan_id']
time.sleep(3)
s3 = get_scan(scan_id3)
if s3:
    res = s3.get('result', {})
    print("status:", s3.get('status'))
    print("error:", s3.get('error'))

# Test 4: SSRF protection
print("\n=== TEST 4: SSRF protection ===")
for bad_url in ['http://127.0.0.1/', 'http://192.168.1.1/', 'http://169.254.169.254/latest/meta-data/']:
    result4 = start_scan(bad_url, source='test')
    scan_id4 = result4['scan_id']
    time.sleep(3)
    s4 = get_scan(scan_id4)
    if s4:
        res = s4.get('result', {})
        print(f"  {bad_url} -> status={s4.get('status')}, error={res.get('error', s4.get('error', 'N/A'))}")


