"""
Lecture des derniers logs applicatifs pour la page de supervision.

En production (Azure App Service) les handlers écrivent sur la sortie standard :
il n'y a pas de fichier à lire, et la vue l'indique explicitement plutôt que
d'afficher une liste vide qui laisserait croire qu'il n'y a aucune erreur.
"""
import os
import re
from collections import Counter

from django.conf import settings

# Format du handler « file » défini dans settings.LOGGING :
# {levelname} {asctime} {name} {module} {funcName} {lineno} {message}
LINE_RE = re.compile(
    r"^(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
    r"(?P<timestamp>\d{4}-\d{2}-\d{2} [\d:,]+)\s+"
    r"(?P<logger>\S+)\s+(?P<module>\S+)\s+(?P<func>\S+)\s+(?P<line>\d+)\s+"
    r"(?P<message>.*)$"
)

MAX_BYTES = 512 * 1024  # on ne relit que la fin du fichier


def log_files():
    """Chemins des fichiers de logs, s'ils sont utilisés par la configuration."""
    handlers = settings.LOGGING.get("handlers", {})
    files = {}
    for key in ("error_file", "file"):
        filename = handlers.get(key, {}).get("filename")
        if filename:
            files[key] = str(filename)
    return files


def _read_tail(path, max_bytes=MAX_BYTES):
    size = os.path.getsize(path)
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
            handle.readline()  # on jette la ligne partielle
        return handle.readlines()


def tail_entries(which="error_file", limit=50):
    """
    Retourne (entrées, note) où `note` explique une éventuelle absence de données.

    Les lignes de traceback (qui ne matchent pas le format) sont rattachées à
    l'entrée précédente pour rester lisibles.
    """
    path = log_files().get(which)
    if not path:
        return [], "Les logs sont envoyés sur la sortie standard (production) : consultez le flux de votre hébergeur."
    if not os.path.exists(path):
        return [], f"Aucun fichier {os.path.basename(path)} pour le moment."

    try:
        lines = _read_tail(path)
    except OSError as exc:
        return [], f"Lecture impossible : {exc}"

    entries = []
    for raw in lines:
        match = LINE_RE.match(raw.rstrip("\n"))
        if match:
            entries.append({**match.groupdict(), "traceback": ""})
        elif entries and raw.strip():
            entries[-1]["traceback"] += raw
    entries.reverse()
    return entries[:limit], ""


def error_summary(limit=200):
    """Compte les erreurs récentes par module — fait ressortir un point chaud."""
    entries, note = tail_entries("error_file", limit=limit)
    counter = Counter(entry["module"] for entry in entries)
    return counter.most_common(5), len(entries), note
