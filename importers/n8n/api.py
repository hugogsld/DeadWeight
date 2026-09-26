"""Client minimal de l'API publique n8n v1 (bibliothèque standard seulement).

Le client la lance chez lui : aucune dépendance à installer, la clé reste dans
son environnement (N8N_API_KEY) et n'est jamais écrite nulle part.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

PAGE = 250  # maximum accepté par l'API


class N8nError(Exception):
    """Erreur lisible par le client, sans trace Python."""


class N8nClient:
    def __init__(self, url: str, api_key: str, timeout: float = 60, retries: int = 3):
        if not url:
            raise N8nError("adresse de l'instance manquante : --url ou N8N_URL")
        if not api_key:
            raise N8nError("clé API manquante : variable d'environnement N8N_API_KEY")
        self.base = url.rstrip("/")
        if not self.base.endswith("/api/v1"):
            self.base += "/api/v1"
        self._key = api_key
        self.timeout = timeout
        self.retries = retries

    def get(self, path: str, **params) -> dict:
        query = {k: _param(v) for k, v in params.items() if v is not None}
        url = self.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        req = urllib.request.Request(url, headers={"X-N8N-API-KEY": self._key, "accept": "application/json"})
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    raise N8nError("clé API refusée par l'instance (401)") from None
                if e.code == 403:
                    raise N8nError("clé API sans droit de lecture sur cette ressource (403)") from None
                if e.code == 404:
                    raise N8nError(f"introuvable (404) : {path}") from None
                if e.code < 500 or attempt == self.retries:
                    raise N8nError(f"l'instance a répondu {e.code} sur {path}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == self.retries:
                    raise N8nError(f"instance injoignable ({self.base}) : {getattr(e, 'reason', e)}") from None
            time.sleep(min(2 ** attempt, 10))
        raise AssertionError("inatteignable")

    def paginate(self, path: str, **params):
        """Parcourt toutes les pages (curseur), de la plus récente à la plus ancienne."""
        cursor = None
        while True:
            page = self.get(path, limit=PAGE, cursor=cursor, **params)
            yield from page.get("data", [])
            cursor = page.get("nextCursor")
            if not cursor:
                return

    def workflows(self):
        return self.paginate("/workflows")

    def workflow(self, workflow_id: str) -> dict:
        return self.get(f"/workflows/{workflow_id}")

    def executions(self, workflow_id: str | None = None, status: str | None = None):
        """Liste sans les données (léger) : id, statut, dates."""
        return self.paginate("/executions", workflowId=workflow_id, status=status, includeData=False)

    def execution(self, execution_id: str) -> dict:
        return self.get(f"/executions/{execution_id}", includeData=True)


def _param(v):
    return str(v).lower() if isinstance(v, bool) else v
