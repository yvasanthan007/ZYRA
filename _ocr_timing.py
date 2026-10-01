"""Temporary OCR timing probe."""
import time

import pyperclip

try:
    pyperclip.copy("")
except Exception:
    pass

from screen_ocr import get_active_url  # noqa: E402

for i in range(2):
    started = time.time()
    url = get_active_url()
    print(f"run{i + 1}: {round(time.time() - started, 2)}s -> {url}")
