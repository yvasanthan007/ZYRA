"""Static audit: every dark-theme text-color rule must have a body.zyra-light override."""
import re, io, sys

PATH = r"c:\Users\Rakshanaa\Project\ZYRA\desktop-dashboard\index.html"
css = io.open(PATH, encoding="utf-8").read()
css = css[css.index("<style>"):css.index("</style>")]
css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)  # strip comments so they don't glue into selectors

# Parse rules (file uses simple flat rules; no nested @media with color rules except responsive block)
rules = re.findall(r'([^{}]+)\{([^{}]*)\}', css)

def split_selectors(sel):
    return [s.strip() for s in sel.split(',') if s.strip()]

dark_text = {}   # selector -> color value (rules without body.zyra-light)
light_sel = set()  # selector text after stripping body.zyra-light prefix

for sel, body in rules:
    sel = sel.strip()
    if not sel or sel.startswith('/*') or '@' in sel:
        continue
    m = re.search(r'(?<![a-zA-Z-])color\s*:\s*([^;]+)', body)
    if sel.startswith('body.zyra-light'):
        for s in split_selectors(sel):
            s = re.sub(r'^body\.zyra-light\s+', '', s)
            light_sel.add('body' if s in ('', 'body.zyra-light') else s)  # bare body.zyra-light -> 'body'
    elif m:
        for s in split_selectors(sel):
            dark_text[s] = m.group(1).strip()

# pseudo-element aware normalization: a light rule covers a dark rule if the
# full selector (incl. pseudo) matches, else if its base matches AND dark rule
# has no pseudo (base rule covers pseudo via inheritance except ::placeholder/
# ::before which need their own rule).
missing = []
for sel, color in sorted(dark_text.items()):
    if sel in light_sel:
        continue
    base = re.sub(r'::{1,2}[a-z-]+$', '', sel)
    has_pseudo = base != sel
    if not has_pseudo and base in light_sel:
        continue  # inherited from base override
    missing.append((sel, color, 'needs own rule' if has_pseudo else 'no base override'))

print("Dark text-color rules total:", len(dark_text))
print("Light selectors total:", len(light_sel))
if missing:
    print("\nUNCOVERED text-color rules:")
    for s, c, why in missing:
        print(f"  {s}  ->  {c}   ({why})")
else:
    print("\nOK: every dark text-color rule has a light-theme override.")
