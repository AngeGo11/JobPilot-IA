"""Remplace les <head> à base de CDN par l'inclusion de partials/_head_assets.html.

Script d'exécution unique, conservé pour tracer la transformation appliquée aux
gabarits (suppression du CDN Tailwind, de Font Awesome cdnjs et de l'@import
Google Fonts). Il est idempotent : relancé, il ne touche plus rien.
"""
import pathlib
import re
import sys

TEMPLATES = pathlib.Path("templates")

# 1. Le script CDN Tailwind et la feuille Font Awesome distante
CDN_TAILWIND = re.compile(r'[ \t]*<script src="https://cdn\.tailwindcss\.com"></script>\n')
CDN_FA = re.compile(r'[ \t]*<link href="https://cdnjs\.cloudflare\.com/[^"]*" rel="stylesheet">\n')
CDN_FA_ALT = re.compile(r'[ \t]*<link rel="stylesheet" href="https://cdnjs\.cloudflare\.com/[^"]*">\n')

# 2. L'@import de polices, première ligne du <style> de chaque gabarit
GF_IMPORT = re.compile(r"[ \t]*@import url\('https://fonts\.googleapis\.com/[^']*'\);\n")

# 3. Le bloc `tailwind.config = {...}` devenu inutile (repris dans tailwind.config.js)
TW_CONFIG = re.compile(
    r'[ \t]*<script>\s*tailwind\.config\s*=\s*\{.*?\}\s*;?\s*</script>\n',
    re.DOTALL,
)

# 4. L'ancien favicon de 2 Mo
OLD_FAVICON = re.compile(
    r'[ \t]*<link rel="shortcut icon" href="\{% static \'images/Logo\.png\' %\}"[^>]*>\n'
)

INCLUDE = '    {% include "partials/_head_assets.html" %}\n'


def rewrite(path: pathlib.Path) -> bool:
    original = path.read_text()
    text = original

    had_cdn = bool(CDN_TAILWIND.search(text))
    if not had_cdn:
        return False

    text = CDN_TAILWIND.sub(INCLUDE, text, count=1)
    text = CDN_FA.sub("", text)
    text = CDN_FA_ALT.sub("", text)
    text = GF_IMPORT.sub("", text)
    text = TW_CONFIG.sub("", text)
    text = OLD_FAVICON.sub("", text)

    # Un <style> vidé de son @import peut ne plus contenir que des blancs.
    text = re.sub(r"[ \t]*<style>\s*</style>\n", "", text)

    if text == original:
        return False
    path.write_text(text)
    return True


def main() -> int:
    changed = [p for p in sorted(TEMPLATES.rglob("*.html")) if rewrite(p)]
    for p in changed:
        print(f"réécrit : {p}")
    print(f"{len(changed)} gabarit(s) modifié(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
