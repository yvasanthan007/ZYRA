import re

content = open(r"backend/url_analyzer/analyzer.py", "r", encoding="utf-8").read()

old = 'emit("reputation", "running")\r\n\r\n    emit("threats", "running")'
new = (
    'emit("reputation", "running")\r\n'
    '    try:\r\n'
    '        reputation = check_reputation(url, parts)\r\n'
    '    except Exception as e:\r\n'
    '        reputation = {\r\n'
    '            "available": False, "provider": None,\r\n'
    '            "reputation": "Unknown", "malware": "Unknown",\r\n'
    '            "phishing": "Unknown", "engines": None,\r\n'
    '            "note": f"Reputation check error ({type(e).__name__}).",\r\n'
    '        }\r\n'
    '    rep_detail = reputation.get("reputation") or reputation.get("note") or "checked"\r\n'
    '    emit("reputation", "done" if reputation.get("available") else "skip", rep_detail)\r\n'
    '\r\n'
    '    emit("threats", "running")'
)

if old not in content:
    print("OLD TEXT NOT FOUND - trying with \\n only")
    old2 = old.replace('\r\n', '\n')
    if old2 in content:
        print("Found with \\n endings")
        content = content.replace(old2, new.replace('\r\n', '\n'))
    else:
        print("NOT FOUND with \\n either")
else:
    content = content.replace(old, new)
    print("Replaced successfully with \\r\\n")

open(r"backend/url_analyzer/analyzer.py", "w", encoding="utf-8").write(content)
print("Done")
