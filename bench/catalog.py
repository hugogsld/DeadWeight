"""Chargement du catalogue de candidats (bench/candidates.json) et resolution
de leur point de terminaison : la variable d'environnement prime, sinon le
defaut du fichier (utile pour Ollama, qui n'a besoin de rien d'autre)."""
import json
import os
from pathlib import Path

from bench.models import Candidate

CANDIDATES_PATH = Path(__file__).resolve().parent / 'candidates.json'


def load_candidates(path=None, kinds=None, size_classes=None):
    """kinds/size_classes : iterables de filtres ; None = pas de filtre."""
    data = json.loads(Path(path or CANDIDATES_PATH).read_text(encoding='utf-8'))
    candidates = [Candidate(**c) for c in data['candidates']]
    if kinds:
        keep = set(kinds)
        candidates = [c for c in candidates if c.kind in keep]
    if size_classes:
        keep = set(size_classes)
        candidates = [c for c in candidates if c.size_class in keep]
    return candidates


def resolve_base_url(candidate):
    return os.environ.get(candidate.base_url_env) or candidate.default_base_url


def resolve_api_key(candidate):
    """None pour Ollama (pas de variable declaree) : aucun en-tete Authorization envoye."""
    if candidate.api_key_env is None:
        return None
    return os.environ.get(candidate.api_key_env)
