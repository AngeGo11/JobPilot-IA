"""Génère les variantes d'images servies au navigateur depuis `assets/Logo.png`.

Le master (2 Mo, 1140×1052) vit hors de `static/` pour ne pas être embarqué par
`collectstatic` : seules les variantes ci-dessous sont déployées.

Choix de format : WebP en `src` direct plutôt qu'un `<picture>` AVIF/WebP/PNG.
  - À 96 px, l'AVIF mesuré est plus lourd que le WebP (5,5 Ko contre 2,0 Ko) :
    l'en-tête AVIF domine sur une si petite image, le format ne se justifie pas.
  - Le WebP est décodé par tous les navigateurs visés (Safari ≥ 14), donc le
    `<picture>` n'apporterait qu'un repli mort et un risque de régression de
    mise en page dans des conteneurs flex.
Les PNG restent générés pour les contextes qui ne négocient pas de format :
JSON-LD, image Open Graph, favicon et courriels (Outlook ne décode pas le WebP).

Usage : make images
"""
import pathlib

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
MASTER = ROOT / "assets" / "Logo.png"
OUT = ROOT / "static" / "images"

# Largeur de fichier -> usage. On vise le double de la taille d'affichage CSS
# pour rester net sur les écrans HiDPI.
WIDTHS = {
    96: "logos de navigation et de pied de page (32 à 48 px affichés)",
    192: "courriels et icône d'application",
    448: "visuels des pages d'authentification (w-56 = 224 px affichés)",
}


def main() -> None:
    src = Image.open(MASTER).convert("RGBA")
    print(f"master : {src.size[0]}×{src.size[1]}, {MASTER.stat().st_size / 1024:.0f} Ko")

    for width, usage in WIDTHS.items():
        im = src.copy()
        im.thumbnail((width, width), Image.LANCZOS)
        webp = OUT / f"logo-{width}.webp"
        png = OUT / f"logo-{width}.png"
        im.save(webp, quality=82, method=6)
        im.convert("RGB").save(png, optimize=True)
        print(f"  logo-{width}  {webp.stat().st_size / 1024:6.1f} Ko webp   {png.stat().st_size / 1024:6.1f} Ko png   — {usage}")

    src.resize((32, 32), Image.LANCZOS).save(OUT / "favicon-32.png", optimize=True)
    apple = src.resize((180, 180), Image.LANCZOS).convert("RGB")
    apple.quantize(colors=128, method=Image.MEDIANCUT).save(OUT / "apple-touch-icon.png", optimize=True)
    print("  favicon-32.png et apple-touch-icon.png régénérés")


if __name__ == "__main__":
    main()
