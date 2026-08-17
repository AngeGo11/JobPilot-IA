"""Captures d'écran de l'application pour les supports de communication.

Produit des PNG en densité ×2 (rétine) exploitables dans un montage vidéo 1080p
ou 4K, en desktop 1440×900 et en mobile 390×844.

Prérequis :
    pip install playwright && python -m playwright install chromium
    make services && make serveur          (ou un serveur sur le port choisi)
    Les comptes de démonstration doivent exister : make seed

Usage :
    python scripts/captures_pub.py [--base http://127.0.0.1:8000] [--out DOSSIER]

Le compte utilisé est un compte de démonstration local (mot de passe « demo »).
Ne jamais lancer ce script sur la production : il déclenche une recherche
France Travail réelle sur la page de résultats.
"""
import argparse
import pathlib
import sys

DESKTOP = (1440, 900)
MOBILE = (390, 844)

# Compte de démonstration : trois offres débloquées, cinq crédits, prénom
# cohérent avec le scénario publicitaire.
COMPTE = ("camille.diallo1@demo.jobpilot.local", "demo")
CV_ID = 72
MATCH_ID = 284

PUBLIC = [
    ("01_accueil_desktop", "/", DESKTOP, False),
    ("02_accueil_desktop_full", "/", DESKTOP, True),
    ("03_accueil_mobile", "/", MOBILE, False),
    ("04_accueil_mobile_full", "/", MOBILE, True),
    ("05_tarifs_desktop", "/subscriptions/pricing/", DESKTOP, True),
    ("06_tarifs_mobile", "/subscriptions/pricing/", MOBILE, True),
    ("07_connexion_desktop", "/users/login/", DESKTOP, False),
]

PRIVE = [
    ("08_mes_cv_desktop", "/resumes/", DESKTOP, False),
    ("09_depot_cv_desktop", "/resumes/upload/", DESKTOP, False),
    ("10_depot_cv_mobile", "/resumes/upload/", MOBILE, False),
    ("14_tableau_de_bord", "/dashboard/", DESKTOP, False),
    ("15_tableau_de_bord_mobile", "/dashboard/", MOBILE, False),
    ("16_candidature_lettre", f"/dashboard/application/{MATCH_ID}/", DESKTOP, True),
]

# La page de résultats ouvre une modale de déblocage dès qu'il existe des offres
# en attente. On la capture séparément, puis on la retire du DOM pour révéler la
# liste : c'est cette liste, avec ses scores, qui sert de plan « preuve ».
RETIRER_MODALE = "var m=document.getElementById('unlock-jobs-modal'); if(m){m.remove();}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default=str(pathlib.Path.home() / "Desktop" / "pub jpt" / "img"))
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright absent : pip install playwright && python -m playwright install chromium")
        return 2

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def shoot(page, nom, url, vp, full):
        page.set_viewport_size({"width": vp[0], "height": vp[1]})
        page.goto(args.base + url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1200)  # laisse retomber les animations d'entrée
        page.evaluate("window.scrollTo(0,0)")
        cible = out / f"{nom}.png"
        page.screenshot(path=str(cible), full_page=full)
        print(f"  {nom:30} {cible.stat().st_size // 1024:5} Ko")

    with sync_playwright() as p:
        nav = p.chromium.launch()
        ctx = nav.new_context(device_scale_factor=2, locale="fr-FR", reduced_motion="reduce")
        page = ctx.new_page()

        print("Pages publiques")
        for a in PUBLIC:
            shoot(page, *a)

        print("Connexion")
        page.set_viewport_size({"width": DESKTOP[0], "height": DESKTOP[1]})
        page.goto(args.base + "/users/login/", wait_until="networkidle")
        page.fill("input[type=email], input[name=email]", COMPTE[0])
        page.fill("input[type=password]", COMPTE[1])
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")

        print("Pages connectées")
        for a in PRIVE:
            shoot(page, *a)

        print("Résultats de matching")
        page.set_viewport_size({"width": DESKTOP[0], "height": DESKTOP[1]})
        page.goto(args.base + f"/matching/search/{CV_ID}/", wait_until="networkidle")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(out / "11b_modale_deblocage.png"))
        page.evaluate(RETIRER_MODALE)
        page.wait_for_timeout(400)
        page.evaluate("window.scrollTo(0,0)")
        page.screenshot(path=str(out / "11_resultats_matching.png"))
        page.screenshot(path=str(out / "12_resultats_matching_full.png"), full_page=True)
        carte = page.locator("h2").first.locator("xpath=ancestor::div[contains(@class,'rounded')][1]")
        carte.screenshot(path=str(out / "17_carte_offre_score.png"))

        page.set_viewport_size({"width": MOBILE[0], "height": MOBILE[1]})
        page.wait_for_timeout(700)
        page.evaluate(RETIRER_MODALE)
        page.evaluate("window.scrollTo(0,0)")
        page.screenshot(path=str(out / "13_resultats_mobile.png"))

        ctx.close()
        nav.close()

    print("\nDossier :", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
