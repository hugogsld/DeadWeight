"""R8 — duplicate_calls : la meme demande payee plusieurs fois, avec la meme reponse.

Difference avec no_cache (R4) : no_cache soupconne un doublon des qu'une demande normalisee
revient souvent sur un contexte volumineux (>= 1024 tokens en entree) ; la reponse elle-meme
n'est jamais comparee, donc un modele non deterministe pourrait repondre autre chose a chaque
fois sans que ce soit visible dans l'evidence. Ici, la reponse est comparee en plus de la
demande : quand la demande ET la reponse (normalisees) sont identiques, la possibilite de
servir la deuxieme depuis un cache est demontree, pas seulement soupconnee. Cette preuve plus
forte autorise de ne poser aucun seuil de taille de contexte et d'exiger moins de repetitions.

Cle de regroupement : application, modele, empreinte du systeme + messages normalises (memes
regles que no_cache : dates, heures, UUID et longs nombres masques) ET parametres de la requete
(temperature, top_p, max_tokens, stream, response_format) — deux appels avec un parametre
different ne sont pas la « meme » demande.

Fenetre : les repetitions sont regroupees en rafales, en reliant deux appels consecutifs (dans
la meme cle) separes de moins de WINDOW_SECONDS. Au-dela, un nouvel appel identique ressemble
plus a une nouvelle question posee independamment qu'a un rejeu evitable a chaud.

Seuils et raisonnement :
- MIN_DUPLICATES = 2 : contrairement a no_cache (3 repetitions, seuil choisi pour ecarter un
  doublon isole sur une simple similarite de prompt), une reponse identique est deja une preuve
  forte : deux occurrences suffisent a demontrer qu'un appel etait evitable.
- WINDOW_SECONDS = 3600 (1 h) : une fenetre de cache glissante d'une heure absorbe les rafales
  de doubles clics, relances et re-consultations de page ; des repetitions espacees de plusieurs
  jours relevent davantage d'un motif applicatif que d'un manque de cache court terme.

Chiffrage : seuls les appels EN TROP de chaque rafale (tous sauf le premier de chaque sous-groupe
de reponses identiques) sont chiffres via report.cost.chiffrer ; le premier appel de chaque
rafale reste necessaire et n'est jamais compte comme gaspillage.

Angle mort : la comparaison de reponse ignore les appels d'outils (reponse texte uniquement) et
n'est vraie qu'a la casse/l'espacement pres — un texte reformule differemment mais equivalent
(vraie proximite semantique) n'est pas detecte. proven=False : confirmer qu'un cache ne casse
rien demande un rejeu.
"""
import hashlib
import json
from collections import defaultdict
from datetime import datetime

from report.cost import chiffrer
from rules.low_entropy import normalize
from rules.no_cache import _normalize

MIN_DUPLICATES = 2
WINDOW_SECONDS = 3600

_PARAM_KEYS = ("temperature", "top_p", "max_tokens", "stream", "response_format")


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _params_key(params):
    return tuple((k, params.get(k)) for k in _PARAM_KEYS)


def _request_key(e):
    prompt = _normalize({"system": e["request"]["system"], "messages": e["request"]["messages"]})
    serialized = json.dumps(prompt, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    return digest, _params_key(e["request"]["params"])


def _clusters(evts):
    """Rafales : deux appels consecutifs separes de plus de WINDOW_SECONDS ouvrent un nouveau groupe."""
    ordered = sorted(evts, key=lambda e: e["ts_start"])
    clusters, current, prev = [], [], None
    for e in ordered:
        t = _parse(e["ts_start"])
        if current and (t - prev).total_seconds() > WINDOW_SECONDS:
            clusters.append(current)
            current = []
        current.append(e)
        prev = t
    if current:
        clusters.append(current)
    return clusters


def _duplicate_subgroups(cluster):
    """Sous-groupes de reponse identique (normalisee) dans une rafale, taille >= MIN_DUPLICATES."""
    by_response = defaultdict(list)
    for e in cluster:
        by_response[normalize(e["response"].get("content") or "")].append(e)
    return [sorted(evts, key=lambda e: e["ts_start"]) for evts in by_response.values()
            if len(evts) >= MIN_DUPLICATES]


def detect(events, pricing=None):
    request_groups = defaultdict(list)
    for e in events:
        if e.get("error") is not None or e["response"].get("content") is None:
            continue
        request_groups[(e["app_id"], e["model"], *_request_key(e))].append(e)

    by_app_model = defaultdict(lambda: {"calls": 0, "matched": [], "wasted": []})
    for (app, model, *_rest), evts in request_groups.items():
        entry = by_app_model[(app, model)]
        entry["calls"] += len(evts)
        for cluster in _clusters(evts):
            for subgroup in _duplicate_subgroups(cluster):
                entry["matched"].extend(subgroup)
                entry["wasted"].extend(subgroup[1:])

    findings = []
    for (app, model), data in sorted(by_app_model.items()):
        wasted = data["wasted"]
        if not wasted:
            continue
        cost = chiffrer(wasted, pricing)
        digest = hashlib.sha256(json.dumps([app, model], ensure_ascii=False).encode()).hexdigest()[:20]
        findings.append({
            "finding_id": f"f_{digest}_duplicate_calls",
            "rule": "duplicate_calls",
            "app_id": app,
            "model": model,
            "template": None,
            "severity": "candidate",
            "title": (f"{len(wasted)} appel(s) sur {data['calls']} ont renvoyé une réponse identique "
                      "à une demande déjà posée dans l'heure précédente : une mise en cache des "
                      "réponses éviterait ces appels."),
            "proven": False,
            "event_ids": sorted({e["event_id"] for e in data["matched"]}),
            "evidence": {
                "calls": data["calls"],
                "wasted_calls": len(wasted),
                # appels en trop uniquement (jamais le premier de chaque rafale) : ce que
                # optimize.propose._cache retire du calcul, sans recomputer les rafales.
                "wasted_event_ids": sorted({e["event_id"] for e in wasted}),
                "est_saving_month_usd": cost["cout_mensuel_usd"],
                "saving_missing": cost["manquants"],
            },
        })
    return findings
