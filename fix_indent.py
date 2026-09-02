import sys
sys.path.insert(0, '.')
content = open("backend/url_analyzer/risk_scorer.py", "r", encoding="utf-8").read()

old = '        classification = "SUSPICIOUS"\n        else:\n        classification = "LIKELY_SAFE"'
new = '        classification = "SUSPICIOUS"\n    else:\n        classification = "LIKELY_SAFE"'

if old in content:
    content = content.replace(old, new)
    open("backend/url_analyzer/risk_scorer.py", "w", encoding="utf-8").write(content)
    print("FIX APPLIED")
else:
    print("NOT FOUND")

