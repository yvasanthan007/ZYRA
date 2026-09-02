"""Debug: make on_complete's exception visible instead of silently swallowed."""
import io

P = r"c:\Users\Rakshanaa\Project\ZYRA\backend\url_analyzer\analyzer.py"
with io.open(P, "r", encoding="utf-8") as f:
    src = f.read()

old = (
    '    if on_complete:\n'
    '        try:\n'
    '            on_complete(result)\n'
    '        except Exception:\n'
    '            pass\n'
    '    return result\n'
)
new = (
    '    if on_complete:\n'
    '        try:\n'
    '            on_complete(result)\n'
    '        except Exception as _e:\n'
    '            import traceback as _tb\n'
    '            print(f"[URL ANALYZER] on_complete callback failed: {_e}")\n'
    '            _tb.print_exc()\n'
    '    return result\n'
)
assert old in src, "on_complete block not found"
src = src.replace(old, new, 1)

with io.open(P, "w", encoding="utf-8", newline="\n") as f:
    f.write(src)
print("added on_complete error logging")
