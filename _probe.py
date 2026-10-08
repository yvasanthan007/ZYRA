lines = open(r"desktop-ui/src/main/main.ts", encoding="utf-8").read().splitlines(keepends=True)
start = None
for i, l in enumerate(lines):
    if "Voice Control" in l:
        start = i; break
end = None
for i in range(start, len(lines)):

    if "_emitVoiceResult" in lines[i]:
        end = i; break
print("START", start)
print("END", end)
print("---SNIP---")
for i in range(start, min(end+2, len(lines))):
    print(i, repr(lines[i]))
