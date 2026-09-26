"""Detection du type de tache et score d'accord candidat / reference.

Classification (peu de reponses distinctes, comme rules.low_entropy) : egalite
stricte apres normalisation (rules.low_entropy.normalize), seuil 0.95 comme
proof.replay. Texte libre : recouvrement de tokens (F1), simple, sans dependance
et suffisant comme signal de premiere ligne. Un LLM-juge serait plus fin mais
coute et bruite le banc lui-meme : point d'extension documente, pas implemente ici.
"""
import re
import unicodedata
from collections import Counter

from rules.low_entropy import MAX_DISTINCT, normalize

CLASSIFICATION_THRESHOLD = 0.95
# Indicatif seulement, pas un seuil medical ni contractuel : voir README.
TEXT_THRESHOLD = 0.5

_WORD = re.compile(r"\w+", re.UNICODE)


def detect_task_type(cases):
    """« classification » si les references n'ont que quelques valeurs distinctes."""
    distinct = {normalize(c.reference) for c in cases if isinstance(c.reference, str)}
    return 'classification' if 0 < len(distinct) <= MAX_DISTINCT else 'text'


def threshold_for(task_type):
    return CLASSIFICATION_THRESHOLD if task_type == 'classification' else TEXT_THRESHOLD


def _tokens(text):
    return Counter(w.lower() for w in _WORD.findall(text or ''))


def token_overlap_f1(a, b):
    """F1 du recouvrement de tokens ; 0.0 si l'un des deux textes est vide."""
    ta, tb = _tokens(a), _tokens(b)
    overlap = sum((ta & tb).values())
    if overlap == 0 or not ta or not tb:
        return 0.0
    precision = overlap / sum(ta.values())
    recall = overlap / sum(tb.values())
    return 2 * precision * recall / (precision + recall)


def _label(text):
    """Étiquette comparable : normalize (casse, espaces, ponctuation) puis sans accents.
    « Négatif » et « negatif » sont la même étiquette, comme « Spam. » et « spam »."""
    decomposed = unicodedata.normalize('NFKD', normalize(text))
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))


def score_case(task_type, got, reference):
    """1.0/0.0 en classification, F1 en texte libre. got=None (erreur) -> 0.0."""
    if got is None:
        return 0.0
    if task_type == 'classification':
        return 1.0 if _label(got) == _label(reference) else 0.0
    return token_overlap_f1(got, reference)
