"""One-off helper: insert the Google Analytics gtag snippet right after
<head> in every user-facing HTML page. Idempotent — skips files that
already contain the tag. Reads/writes strict UTF-8 (no BOM)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    ROOT / "frontend" / "index.html",
    ROOT / "public" / "contact.html",
    ROOT / "public" / "faq.html",
    ROOT / "public" / "features.html",
    ROOT / "public" / "privacy.html",
    ROOT / "public" / "terms.html",
]

GA = """
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-QW43LYP6E6"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());

  gtag('config', 'G-QW43LYP6E6');
</script>
"""

for f in FILES:
    text = f.read_text(encoding="utf-8")
    if "googletagmanager.com" in text:
        print(f"skip (already tagged): {f.relative_to(ROOT)}")
        continue
    idx = text.find("<head>")
    if idx == -1:
        print(f"ERROR: no <head> in {f}")
        continue
    insert_at = idx + len("<head>")
    new_text = text[:insert_at] + "\n" + GA.strip("\n") + "\n" + text[insert_at:]
    f.write_text(new_text, encoding="utf-8", newline="")
    print(f"tagged: {f.relative_to(ROOT)}")

print("done")
