import re
from typing import Dict

# Mêmes regex que PDFParser (email/téléphone FR), réutilisées ici pour la pseudonymisation.
_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
_PHONE_RE = re.compile(r'(?:(?:\+|00)33|0)\s*[1-9](?:[\s.-]*\d{2}){4}')
# Heuristique nom : "Prénom NOM" en tête de CV (2-3 mots capitalisés, pas de chiffres).
_NAME_LINE_RE = re.compile(r'^[A-ZÀ-Ý][a-zà-ÿ\-]+(?:\s+[A-ZÀ-Ý][A-ZÀ-Ýa-zà-ÿ\-]+){1,2}$')


class Pseudonymizer:
    """
    Remplace email/téléphone/nom par des tokens neutres ([EMAIL_1], [TEL_1], [NOM_1])
    avant tout envoi du texte à un service tiers (Gemini) ou tout logging.
    La correspondance token -> valeur réelle n'existe qu'en mémoire, le temps du
    traitement (jamais persistée), pour permettre une dé-pseudonymisation locale si besoin.
    """

    def __init__(self):
        self._mapping: Dict[str, str] = {}

    def pseudonymize(self, text: str) -> str:
        if not text:
            return text

        lines = text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if _NAME_LINE_RE.match(stripped):
                lines[i] = line.replace(stripped, self._token_for(stripped, 'NOM'))
            break
        text = '\n'.join(lines)

        text = _EMAIL_RE.sub(lambda m: self._token_for(m.group(0), 'EMAIL'), text)
        text = _PHONE_RE.sub(lambda m: self._token_for(m.group(0), 'TEL'), text)
        return text

    def depseudonymize(self, text: str) -> str:
        if not text:
            return text
        for token, original in self._mapping.items():
            text = text.replace(token, original)
        return text

    def _token_for(self, value: str, kind: str) -> str:
        for token, original in self._mapping.items():
            if original == value:
                return token
        index = sum(1 for token in self._mapping if token.startswith(f'[{kind}_')) + 1
        token = f'[{kind}_{index}]'
        self._mapping[token] = value
        return token
