import re

content = open("backend/url_analyzer/analyzer.py", "r", encoding="utf-8").read()

# Find the reputation emit line and the next emit("threats") line
pattern = r'(emit\("reputation", "running"\)\n)(.*)(emit\("threats", "running"\))'
match = re.search(pattern, content, re.DOTALL)
if match:
    print("Found pattern matching with DOTALL")
    insertion = match.group(1) + (
        '    try:\n'
        '        reputation = check_reputation(url, parts)\n'
        '    except Exception as e:\n'
        '        reputation = {\n'
        '            "available": False, "provider": None,\n'
        '            "reputation": "Unknown", "malware": "Unknown",\n'
        '            "phishing": "Unknown", "engines": None,\n'
        '            "note": f"Reputation check error ({type(e).__name__}).",\n'
        '        }\n'
        '    rep_detail = reputation.get("reputation") or reputation.get("note") or "checked"\n'
        '    emit("reputation", "done" if reputation.get("available") else "skip", rep_detail)\n'
    ) + match.group(2) + match.group(3)
    content = content[:match.start()] + insertion + content[match.end():]
    open("backend/url_analyzer/analyzer.py", "w", encoding="utf-8").write(content)
    print("FIX APPLIED")
else:
    print("Pattern not found")
    i1 = content.find('emit("reputation", "running")')
    i2 = content.find('emit("threats", "running")')
    print(f"reputation emit at: {i1}")
    print(f"threats emit at: {i2}")
    if i1 >= 0 and i2 >= 0:
        between = content[i1+28:i2]
        print("Between them repr:", repr(between[:300]))

