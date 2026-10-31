from pathlib import Path
path = Path(__file__).with_name("screen_ocr.py")
source = path.read_text()
source = source.replace(chr(34) * 2 + "Load EasyOCR once in the background during application startup." + chr(34) * 3, chr(34) * 3 + "Load EasyOCR once in the background during application startup." + chr(34) * 3)
source = source.replace(chr(34) * 2 + "Extract the displayed browser URL, preferring its address bar strip." + chr(34) * 3, chr(34) * 3 + "Extract the displayed browser URL, preferring its address bar strip." + chr(34) * 3)
path.write_text(source)
