"""Régénère le sous-ensemble Font Awesome auto-hébergé.

Pourquoi : la feuille `all.min.css` du CDN pèse ~100 Ko et la police
`fa-solid-900.woff2` 155 Ko, pour 99 icônes réellement utilisées. On extrait donc
les seules règles utiles et on sous-ensemble la police sur les points de code
correspondants (~9 Ko), ce qui supprime au passage la dépendance à
cdnjs.cloudflare.com (ressource bloquante + origine tierce dans la CSP).

Prérequis : `pip install fonttools brotli` et le paquet npm
`@fortawesome/fontawesome-free` téléchargé dans un dossier temporaire :

    npm pack @fortawesome/fontawesome-free@6.7.2 && tar xzf fortawesome-*.tgz

Usage : python scripts/build_icons.py <dossier_package_fontawesome>
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FAMILIES = {
    "fa-solid", "fa-regular", "fa-brands", "fa-light", "fa-thin", "fa-duotone",
    "fa-sharp", "fa-fw", "fa-spin", "fa-pulse", "fa-lg", "fa-xs", "fa-sm",
    "fa-xl", "fa-2xl", "fa-2x", "fa-3x",
}

HEADER = """/* Font Awesome Free 6.7.2 (licence CC BY 4.0) — sous-ensemble auto-hébergé.
   Généré par `python scripts/build_icons.py` : ne pas éditer à la main.
   {count} icônes embarquées, police sous-ensemblée à {size} Ko (contre 155 Ko),
   et plus aucune requête vers cdnjs.cloudflare.com. */
@font-face{{
  font-family:"Font Awesome 6 Free";
  font-style:normal;
  font-weight:900;
  font-display:block;
  src:url("../webfonts/fa-solid-900.woff2") format("woff2");
}}
.fa-solid,.fa-regular,.fas,.far{{
  font-family:"Font Awesome 6 Free";
  font-weight:900;
  -moz-osx-font-smoothing:grayscale;
  -webkit-font-smoothing:antialiased;
  display:var(--fa-display,inline-block);
  font-style:normal;
  font-variant:normal;
  line-height:1;
  text-rendering:auto;
}}
.fa-fw{{text-align:center;width:1.25em}}
.fa-spin{{animation:fa-spin 2s linear infinite}}
@keyframes fa-spin{{from{{transform:rotate(0)}}to{{transform:rotate(360deg)}}}}
@media (prefers-reduced-motion:reduce){{.fa-spin{{animation-delay:-1ms;animation-duration:1ms;animation-iteration-count:1}}}}
"""


def main(package: pathlib.Path) -> int:
    css = (package / "css" / "fontawesome.min.css").read_text()

    used = set()
    for f in (ROOT / "templates").rglob("*.html"):
        used |= set(re.findall(r"fa-[a-z0-9-]+", f.read_text()))
    used -= FAMILIES

    rules = dict(re.findall(r'\.(fa-[a-z0-9-]+)\{--fa:"(\\[0-9a-f]+)"\}', css))
    for selectors, code in re.findall(
        r'((?:\.fa-[a-z0-9-]+,)+\.fa-[a-z0-9-]+)\{--fa:"(\\[0-9a-f]+)"\}', css
    ):
        for sel in selectors.split(","):
            rules[sel.strip(".")] = code

    kept = {n: c for n, c in rules.items() if n in used}
    missing = sorted(n for n in used if n not in rules)
    if missing:
        # Typiquement des icônes Font Awesome Pro : elles ne s'affichaient pas
        # non plus avec le CDN, autant le signaler bruyamment.
        print(f"⚠ icônes introuvables dans Font Awesome Free : {missing}")

    font_out = ROOT / "static" / "webfonts" / "fa-solid-900.woff2"
    font_out.parent.mkdir(parents=True, exist_ok=True)
    codepoints = sorted({int(c.lstrip("\\"), 16) for c in kept.values()})
    subprocess.run(
        [
            sys.executable, "-m", "fontTools.subset",
            str(package / "webfonts" / "fa-solid-900.woff2"),
            "--unicodes=" + ",".join(f"U+{c:04X}" for c in codepoints),
            "--flavor=woff2", "--layout-features=", "--no-hinting", "--desubroutinize",
            f"--output-file={font_out}",
        ],
        check=True,
    )

    size = font_out.stat().st_size
    body = "\n".join(f'.{n}::before{{content:var(--fa);--fa:"{c}"}}' for n, c in sorted(kept.items()))
    css_out = ROOT / "static" / "css" / "icons.css"
    css_out.write_text(HEADER.format(count=len(kept), size=size // 1024) + body + "\n")
    print(f"{len(kept)} icônes — {font_out.name} : {size / 1024:.1f} Ko, {css_out.name} : {css_out.stat().st_size / 1024:.1f} Ko")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(pathlib.Path(sys.argv[1])))
