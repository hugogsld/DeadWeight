"""R9 — paid_errors : payer pour un echec, puis payer encore pour la relance.

Une erreur upstream pure (429, 500, 529...) n'est pas facturee : usage.output_tokens vaut null
et le cout est deja exclu par report/cost.py (voir fixtures/dataset/gen_dataset.py::upstream_errors,
deja un cas negatif du chiffrage general). Ce n'est PAS ce que vise cette regle. Elle vise les
echecs qui COUTENT quand meme :
- finish_reason == "length" : la reponse a ete tronquee par max_tokens, mais tous les tokens
  produits jusque-la sont factures (usage.output_tokens present).
- finish_reason == "content_filter" ou error present alors que usage.output_tokens est present :
  le fournisseur a facture une generation partielle avant de la refuser.
- http_status >= 400 avec usage present (rare, mais mesure telle quelle, jamais supposee).

Regroupement : application x modele (comme no_cache/raw_context, un constat par couple, pas par
gabarit — un echec facture n'est pas attache a une seule formulation de prompt).

Deux signaux combines :
1. Taux d'echecs factures : billed_failures / calls.
2. Relances : un echec facture suivi, dans RETRY_WINDOW_SECONDS, d'un nouvel appel a la MEME
   demande normalisee (memes regles de masquage que no_cache : dates, heures, UUID, longs
   nombres). Ne compte que les relances qui suivent un echec DEJA FACTURE : relancer un appel
   qui n'a rien coute (upstream_errors) n'est pas un gaspillage, c'est le fonctionnement normal
   d'un client qui reessaie apres un 429.

Seuils et raisonnement :
- MIN_CALLS = 20 : plus bas que le seuil de 30 des regles de frequence (low_entropy,
  oversized_model), car les echecs sont plus rares par nature ; vingt appels evitent de signaler
  un incident isole (un seul echec sur deux appels) tout en restant atteignable sur une
  application a trafic modeste.
- MIN_BILLED_FAILURE_RATE = 0.05 : au-dela d'un echec facture sur vingt, ce n'est plus un
  incident ponctuel (troncature rare, filtre de contenu exceptionnel) mais un reglage a revoir
  (max_tokens trop bas, prompt qui declenche trop souvent un filtre).
- RETRY_WINDOW_SECONDS = 30 : une relance de la meme demande dans les 30 secondes qui suivent un
  echec facture est un retry automatique (client ou orchestrateur), pas une nouvelle question
  independante qui ressemblerait par coincidence a la precedente.
- MIN_RETRY_STORM = 3 : trois relances rapprochees ecartent la coincidence d'un double clic
  isole et signalent un motif recurrent, meme si le taux d'echec global reste sous 5 %.

Chiffrage : cout des relances via report.cost.chiffrer, en ne comptant QUE les tokens reellement
factures de l'appel de relance (jamais un forfait). Latence perdue = somme des latency_ms des
appels en echec qui ont ete relances (le temps de l'echec est un temps mort, meme s'il est
gratuit).

Angle mort : la fenetre de 30 s ne detecte pas les relances plus lentes (nouvel essai relance a
la main, minutes plus tard) ; ces cas restent invisibles ici. proven=False : confirmer qu'une
relance est bien une consequence de l'echec (et pas une coincidence de contenu) demanderait de
suivre un identifiant de requete cote client, absent du schema.
"""
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime

from report.cost import chiffrer
from rules.no_cache import _normalize

# DW_MIN_CALLS : seuil unique, abaissable pour une démo sur peu d'exécutions (défaut inchangé : 20).
MIN_CALLS = int(os.environ.get("DW_MIN_CALLS", "20"))
MIN_BILLED_FAILURE_RATE = 0.05
RETRY_WINDOW_SECONDS = 30
MIN_RETRY_STORM = 3


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _request_signature(e):
    prompt = _normalize({"system": e["request"]["system"], "messages": e["request"]["messages"]})
    return json.dumps(prompt, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _is_billed_failure(e):
    billed = e["usage"].get("output_tokens") is not None
    failed = (e.get("error") is not None or e.get("http_status", 200) >= 400
              or e["response"].get("finish_reason") in ("length", "content_filter"))
    return billed and failed


def _retries(evts):
    """Pour chaque echec facture, l'appel suivant (meme demande, fenetre courte) qui le suit."""
    ordered = sorted(evts, key=lambda e: e["ts_start"])
    pairs = []
    for i, e in enumerate(ordered):
        if not _is_billed_failure(e):
            continue
        end = _parse(e.get("ts_end") or e["ts_start"])
        sig = _request_signature(e)
        for other in ordered[i + 1:]:
            if (_parse(other["ts_start"]) - end).total_seconds() > RETRY_WINDOW_SECONDS:
                break
            if _request_signature(other) == sig:
                pairs.append((e, other))
                break
    return pairs


def detect(events, pricing=None):
    groups = defaultdict(list)
    for e in events:
        groups[(e["app_id"], e["model"])].append(e)

    findings = []
    for (app, model), evts in sorted(groups.items()):
        if len(evts) < MIN_CALLS:
            continue
        billed_failures = [e for e in evts if _is_billed_failure(e)]
        rate = len(billed_failures) / len(evts)
        pairs = _retries(evts)
        if rate < MIN_BILLED_FAILURE_RATE and len(pairs) < MIN_RETRY_STORM:
            continue
        retry_events = [other for _, other in pairs if other["usage"].get("output_tokens") is not None]
        cost = chiffrer(retry_events, pricing) if retry_events else {"cout_mensuel_usd": None, "manquants": []}
        latency_lost = sum(e["latency_ms"] for e, _ in pairs)
        digest = hashlib.sha256(json.dumps([app, model], ensure_ascii=False).encode()).hexdigest()[:20]
        retry_txt = (f", dont {len(pairs)} relancé(s) en moins de {RETRY_WINDOW_SECONDS} s "
                     "avec la même demande, payés une seconde fois." if pairs else ".")
        findings.append({
            "finding_id": f"f_{digest}_paid_errors",
            "rule": "paid_errors",
            "app_id": app,
            "model": model,
            "template": None,
            "severity": "cut" if pairs else "trim",
            "title": (f"{len(billed_failures)} échec(s) facturé(s) sur {len(evts)} appels "
                      f"({rate * 100:.1f} %){retry_txt}"),
            "proven": False,
            "event_ids": sorted({e["event_id"] for e in billed_failures} | {o["event_id"] for _, o in pairs}),
            "evidence": {
                "calls": len(evts),
                "billed_failures": len(billed_failures),
                "billed_failure_rate": round(rate, 3),
                "retries": len(pairs),
                "est_retry_cost_month_usd": cost["cout_mensuel_usd"],
                "retry_cost_missing": cost["manquants"],
                "latency_lost_ms": latency_lost,
            },
        })
    return findings
