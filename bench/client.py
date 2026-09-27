"""Client OpenAI-compatible generique pour appeler un modele candidat.

Meme format que proof.extract.OpenAICompatibleLLM (urllib, /chat/completions),
etendu pour ne jamais supposer de cle (Ollama n'en a pas) et pour renvoyer la
latence mesuree. N'echoue jamais par exception : une erreur devient un champ
`error` court et generique, jamais le texte brut de l'exception (il peut
recopier la cle, comme le fait le 401 d'OpenAI).
"""
import json
import time
import urllib.error
import urllib.request
from typing import NamedTuple, Optional

DEFAULT_TIMEOUT_S = 30


class CallResult(NamedTuple):
    content: Optional[str]
    latency_ms: float
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    error: Optional[str]


class CandidateLLM:
    """base_url inclut le prefixe API (ex. /v1). api_key peut etre None."""

    def __init__(self, base_url, api_key, model, timeout_s=DEFAULT_TIMEOUT_S, route=None, max_tokens=None,
                 extra=None):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self.route = route  # OpenRouter : hébergeur imposé, sans repli vers un autre
        self.max_tokens = max_tokens
        self.extra = dict(extra) if extra else {}  # ex. {'reasoning_effort': 'low'} (bench.reasoning)

    def complete(self, messages):
        # temperature 0 pour des réponses stables ; les modèles à raisonnement (gpt-5, o-series)
        # la refusent (400) : on relance alors une fois sans.
        # getattr : un candidat construit sans passer par __init__ (tests/test_bench_runner.py,
        # __new__ + attributs choisis) n'a pas forcément .extra ; défaut vide, jamais une exception.
        extra = getattr(self, 'extra', None) or {}
        result = self._call({'model': self.model, 'temperature': 0, 'messages': list(messages), **extra})
        if result.error == 'http_400':
            result = self._call({'model': self.model, 'messages': list(messages), **extra})
        return result

    def _call(self, body):
        if self.route:
            body = {**body, 'provider': {'order': [self.route], 'allow_fallbacks': False}}
        if self.max_tokens:
            body = {**body, 'max_tokens': self.max_tokens}
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = 'Bearer ' + self.api_key
        request = urllib.request.Request(
            self.base_url + '/chat/completions',
            data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
            headers=headers, method='POST',
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            return CallResult(None, self._elapsed_ms(t0), None, None, f'http_{exc.code}')
        except TimeoutError:
            return CallResult(None, self._elapsed_ms(t0), None, None, 'timeout')
        except Exception:
            return CallResult(None, self._elapsed_ms(t0), None, None, 'transport')

        latency_ms = self._elapsed_ms(t0)
        try:
            content = payload['choices'][0]['message'].get('content')
        except (KeyError, IndexError, TypeError, AttributeError):
            return CallResult(None, latency_ms, None, None, 'malformed_response')
        usage = payload.get('usage') or {}
        return CallResult(content, latency_ms, usage.get('prompt_tokens'),
                          usage.get('completion_tokens'), None)

    @staticmethod
    def _elapsed_ms(t0):
        return (time.perf_counter() - t0) * 1000
