content = open("backend/url_analyzer/validator.py", "r", encoding="utf-8").read()
lines = content.split("\n")
for i in range(103, 175):
    if i < len(lines):
        print(f"{i+1:3d}| {lines[i]}")

