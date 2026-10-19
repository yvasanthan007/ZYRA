from pathlib import Path
p = Path('screen_ocr.py')
s = p.read_text(encoding='utf-8')
s = s.replace('    ""Read the focused browser address bar URL, preserving clipboard contents.', '    ""Read the focused browser address bar URL, preserving clipboard contents.')
p.write_text(s, encoding='utf-8')
