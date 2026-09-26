"""Bibliothèque publique n8n (n8n.io/workflows) : récupérer des workflows réels, mesurer notre couverture.

    python -m importers.n8n library fetch --limit 1000        # les plus consultés de la catégorie AI
    python -m importers.n8n library coverage                  # ce que notre code sait lire

API publique, sans clé : ``api.n8n.io/api/templates/search`` (liste triée par vues) puis
``api.n8n.io/api/templates/workflows/<id>`` (workflow complet). On ne garde que ce qui sert aux tests
(nœuds, connexions, nom, catégories, vues) : ni description, ni image, ni ``pinData`` (données
d'exemple). Stockage dans ``private/n8n-library/`` (ignoré par git) : ces workflows appartiennent à
leurs auteurs, on ne les republie pas.

Les workflows publics n'ont pas d'historique : ils testent la lecture du **workflow** (types de nœuds,
où est rangé le modèle), pas celle des exécutions.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from .convert import PROVIDERS, _short, model_of
from .nodes import DIRECT, NOT_TEXT_NODES, is_llm_node

API = "https://api.n8n.io/api/templates"
USER_AGENT = "deadweight-audit/0.1 (hackathon; couverture des workflows n8n)"
KEEP = ("id", "name", "totalViews", "categories", "createdAt")

# fragments qui signalent un nœud d'IA, même inconnu de nous : sert à trouver nos trous
AI_HINTS = ("langchain", "openai", "anthropic", "gemini", "mistral", "ollama", "groq", "deepseek", "perplexity",
            "cohere", "huggingface", "bedrock", "vertex", "xai", "openrouter", "llm", "chatmodel")
# nœuds d'IA qui n'appellent pas eux-mêmes un modèle : mémoire, outils, déclencheurs, découpage, et
# nœuds racines (agent, chaînes, classifieurs) qui passent par leur sous-nœud « Chat Model »
NOT_LLM = ("memory", "tool", "trigger", "textsplitter", "document", "vectorstore", "embeddings", "outputparser",
           "retriever", "code", "mcp", "agent", "chain", "classifier", "extractor", "sentiment", "guardrail",
           "rerank", "modelselector")
# nœuds dont le nom contient un indice d'IA mais qui n'en appellent pas (fenêtre de discussion)
NOT_LLM_TYPES = {"@n8n/n8n-nodes-langchain.chat"}


def _get(url: str, timeout: float = 30) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code < 500 and e.code != 429:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(2 ** attempt)
    return None


def list_ids(limit: int, category: str = "AI", get=_get) -> list[int]:
    """Identifiants des workflows les plus consultés de la catégorie."""
    ids, page = [], 1
    while len(ids) < limit:
        data = get(f"{API}/search?page={page}&rows=100&category={category}&sort=views:desc")
        rows = (data or {}).get("workflows") or []
        if not rows:
            break
        ids.extend(w["id"] for w in rows if w["id"] not in ids)
        page += 1
    return ids[:limit]


def slim(full: dict) -> dict:
    """Réponse de l'API → ce qui sert aux tests."""
    meta = full.get("workflow") or {}
    body = meta.get("workflow") or {}
    out = {k: meta.get(k) for k in KEEP}
    out["categories"] = [c.get("name") for c in meta.get("categories") or [] if isinstance(c, dict)]
    out["nodes"] = body.get("nodes") or []
    out["connections"] = body.get("connections") or {}
    return out


def fetch(out_dir: str | Path = "private/n8n-library", limit: int = 1000, category: str = "AI",
          rate: float = 5.0, get=_get, log=print) -> dict:
    """Télécharge les workflows manquants ; relancée, reprend sans retélécharger."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ids = list_ids(limit, category, get)
    missing = [i for i in ids if not (out / f"{i}.json").exists()]
    log(f"{len(ids)} workflow(s) retenus, {len(ids) - len(missing)} déjà là, {len(missing)} à télécharger")
    fetched, gone = 0, 0
    for n, wid in enumerate(missing, 1):
        started = time.monotonic()
        full = get(f"{API}/workflows/{wid}")
        if full and (full.get("workflow") or {}).get("workflow"):
            tmp = out / f"{wid}.json.part"
            tmp.write_text(json.dumps(slim(full), ensure_ascii=False), encoding="utf-8")
            tmp.replace(out / f"{wid}.json")
            fetched += 1
        else:
            gone += 1
        if n % 100 == 0:
            log(f"  {n}/{len(missing)}")
        if rate:  # rythme poli : au plus `rate` requêtes par seconde (0 = sans limite, pour les tests)
            wait = 1 / rate - (time.monotonic() - started)
            if wait > 0:
                time.sleep(wait)
    total = sum(1 for p in out.glob("*.json") if p.stem.isdigit())
    log(f"terminé : {fetched} téléchargé(s), {gone} indisponible(s), {total} dans {out}")
    return {"ids": len(ids), "fetched": fetched, "gone": gone, "total": total}


def looks_ai(node_type: str) -> bool:
    t = node_type.lower()
    return any(h in t for h in AI_HINTS)


def coverage(folder: str | Path = "private/n8n-library") -> dict:
    """Ce que notre code reconnaît dans des workflows réels : nœuds LLM, fournisseur, modèle."""
    files = sorted(p for p in Path(folder).glob("*.json") if p.stem.isdigit())  # pas coverage.json
    workflows = with_llm = 0
    llm_nodes = with_model = with_provider = 0
    missing_model: Counter = Counter()
    default_models: Counter = Counter()
    non_text: Counter = Counter()
    unknown_provider: Counter = Counter()
    unknown_ai: Counter = Counter()
    models: Counter = Counter()
    expression_models = 0
    examples: dict[str, int] = {}
    for path in files:
        wf = json.loads(path.read_text(encoding="utf-8"))
        workflows += 1
        found = False
        for node in wf.get("nodes") or []:
            t = node.get("type") or ""
            if is_llm_node(node):
                found = True
                llm_nodes += 1
                short = _short(t)
                if short not in PROVIDERS:
                    unknown_provider[short] += 1
                    examples.setdefault(short, wf.get("id"))
                else:
                    with_provider += 1
                model = model_of(node, {})
                params = node.get("parameters") or {}
                present = [params[k] for k in ("model", "modelId", "modelName") if k in params]
                raw = present[0].get("value") if present and isinstance(present[0], dict) else (present or [None])[0]
                if model:
                    with_model += 1
                    models[model] += 1
                elif not present:
                    # réglage laissé par défaut : n8n ne l'enregistre pas, et ce défaut change selon la
                    # version de n8n installée ; l'historique d'exécution, lui, donne le vrai modèle
                    default_models[f"{short} v{node.get('typeVersion')}"] += 1
                elif isinstance(raw, str) and raw.startswith("="):
                    expression_models += 1
                else:
                    key = f"{short} v{node.get('typeVersion')}"
                    missing_model[key] += 1
                    examples.setdefault(key, wf.get("id"))
            elif t in DIRECT:
                non_text[f"{_short(t)} : {(node.get('parameters') or {}).get('resource')}"] += 1
            elif t in NOT_TEXT_NODES:
                non_text[f"{_short(t)} : document (OCR)"] += 1
            elif looks_ai(t) and t not in NOT_LLM_TYPES and not any(x in _short(t).lower() for x in NOT_LLM):
                unknown_ai[t] += 1
                examples.setdefault(t, wf.get("id"))
        with_llm += found

    def pct(a, b):
        return round(a / b, 3) if b else None

    return {
        "workflows": workflows,
        "workflows_avec_llm": with_llm,
        "noeuds_llm": llm_nodes,
        "fournisseur_reconnu": pct(with_provider, llm_nodes),
        "modele_lu": pct(with_model, llm_nodes),
        "modele_par_defaut_n8n": sum(default_models.values()),
        "modele_en_formule": expression_models,
        "modele_introuvable": sum(missing_model.values()),
        "fournisseurs_inconnus": dict(unknown_provider.most_common()),
        "modele_introuvable_par_type": dict(missing_model.most_common(20)),
        "modele_par_defaut_par_type": dict(default_models.most_common(20)),
        "ia_non_texte": dict(non_text.most_common()),
        "noeuds_ia_non_reconnus": dict(unknown_ai.most_common(30)),
        "modeles_les_plus_frequents": dict(models.most_common(15)),
        "exemples": examples,
    }


def render(r: dict) -> str:
    def p(v):
        return "—" if v is None else f"{v:.0%}"
    lines = [
        f"{r['workflows']} workflow(s), dont {r['workflows_avec_llm']} avec au moins un nœud LLM reconnu",
        f"{r['noeuds_llm']} nœud(s) LLM : fournisseur reconnu {p(r['fournisseur_reconnu'])}, "
        f"modèle lu {p(r['modele_lu'])}",
        f"  sinon : {r['modele_par_defaut_n8n']} laissé(s) au défaut de n8n (connu seulement à l'exécution), "
        f"{r['modele_en_formule']} en formule, {r['modele_introuvable']} introuvable(s)",
    ]
    for title, key in (("fournisseurs inconnus", "fournisseurs_inconnus"),
                       ("modèle introuvable (type, version)", "modele_introuvable_par_type"),
                       ("modèle laissé au défaut de n8n (type, version)", "modele_par_defaut_par_type"),
                       ("usages non textuels exclus (image, audio…)", "ia_non_texte"),
                       ("nœuds d'IA non reconnus comme LLM", "noeuds_ia_non_reconnus"),
                       ("modèles les plus fréquents", "modeles_les_plus_frequents")):
        if r[key]:
            lines.append(f"\n{title} :")
            lines += [f"  {n:>5}  {k}" + (f"   (ex. workflow {r['exemples'][k]})" if k in r["exemples"] else "")
                      for k, n in r[key].items()]
    return "\n".join(lines)
