"""Structures immuables du banc de modeles : jamais mutees, toujours recreees."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Candidate:
    """Un modele candidat au remplacement, tel que decrit dans candidates.json."""
    id: str
    kind: str  # openai | openrouter | mistral | ollama
    model: str
    base_url_env: str
    default_base_url: str
    api_key_env: Optional[str]  # None : aucune cle (Ollama local)
    size_class: str  # local | small | medium
    origin: str  # FR | EU | US | CN
    note: str
    route: Optional[str] = None  # hébergeur OpenRouter imposé, sans repli (ex. « Mistral ») : on teste cette route
    max_tokens: Optional[int] = None  # limite de sortie ; sans elle, OpenRouter réserve le maximum du modèle (402)


@dataclass(frozen=True)
class BenchCase:
    """Un cas de rejeu : ce qui a ete envoye au modele d'origine, et sa reponse.

    origin_input_tokens/origin_output_tokens : usage mesure de l'appel d'origine,
    utilise seulement pour estimer un cout en --dry-run (aucun appel candidat n'a
    encore eu lieu a ce moment).
    """
    event_id: str
    messages: tuple
    reference: str
    origin_input_tokens: Optional[int] = None
    origin_output_tokens: Optional[int] = None


@dataclass(frozen=True)
class CandidateResult:
    """Resultat mesure d'un candidat sur un jeu de test, jamais un defaut inventé."""
    candidate: Candidate
    n_cases: int
    n_calls: int
    n_errors: int
    score: Optional[float]
    latency_p50_ms: Optional[float]
    latency_p95_ms: Optional[float]
    cost_per_1000_calls_usd: Optional[float]
    verdict: str  # pass | reject | not_tested
    reasons: tuple
