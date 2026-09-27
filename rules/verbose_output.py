"""R12 — verbose_output : des reponses bien plus longues qu'il ne faudrait, sans plafond reel.

Regroupement : application x modele x gabarit de prompt (meme decoupage que low_entropy /
oversized_model / excess_reasoning : le gabarit masque les nombres du prompt systeme, meme
tache = meme gabarit).

Trois signaux mesures sur les appels reussis d'un groupe :
- Aucun plafond pose : params.max_tokens absent sur la quasi-totalite des appels.
- Longueur mediane elevee ET tres dispersee : le 90e centile depasse largement la mediane,
  signe qu'une minorite d'appels tire le cout vers le haut alors que la tache « typique » du
  groupe reste plus courte — un plafond proche de la mediane les couperait sans abimer la
  reponse habituelle.
- (evidence seulement, ne declenche pas a lui seul) part des appels tronques par une limite deja
  posee (finish_reason == "length") : signale que meme un plafond existant est systematiquement
  sature, mais determiner le bon nouveau plafond dans ce cas demanderait de savoir ce que la
  reponse aurait ete sans coupure — hors de portee sans rejeu, donc non utilise pour chiffrer.

Seuils et raisonnement :
- MIN_CALLS = 30 : meme seuil que low_entropy/oversized_model/excess_reasoning, une mediane et
  un centile ne sont fiables qu'a partir de ce volume.
- MIN_MEDIAN_OUTPUT_TOKENS = 300 : en dessous, la reponse est deja courte ; le gain d'un plafond
  serait marginal au regard du risque de tronquer une reponse legitime.
- UNCAPPED_SHARE = 0.9 : au moins neuf appels sur dix sans max_tokens ; un plafond deja pose sur
  une partie significative du trafic releve d'un choix produit existant, pas d'un oubli.
- MIN_P90_MEDIAN_RATIO = 2.0 : le 90e centile au moins double de la mediane traduit une queue de
  distribution large ; en dessous, la variabilite est ordinaire et un plafond serrerait la
  majorite des reponses utiles.
- CAP_MULTIPLIER = 1.2 : plafond suggere = 1,2x la mediane observee, une marge de 20 % au-dessus
  du cas typique du groupe pour ne pas couper les reponses un peu plus longues que d'habitude.

Chiffrage : compare le cout actuel a un cout hypothetique ou chaque appel qui depasse le plafond
suggere est retaille a ce plafond (report.cost.chiffrer sur une copie). Hypothese non verifiee :
rien ne garantit qu'une reponse coupee a ce plafond reste utilisable, d'ou proven=False.

Angle mort : le plafond suggere est une regle simple (mediane x 1,2), pas une analyse du besoin
reel de chaque tache ; une tache qui a legitimement besoin de longues reponses (documentation
generee, traduction longue) tombera dans le meme filet si elle est bruyante et sans plafond.
"""
import copy
import math
import os
from collections import defaultdict
from statistics import median

from report.cost import chiffrer
from rules.low_entropy import template_of

# DW_MIN_CALLS : seuil unique, abaissable pour une demo sur peu d'executions (defaut inchange : 30).
MIN_CALLS = int(os.environ.get("DW_MIN_CALLS", "30"))
MIN_MEDIAN_OUTPUT_TOKENS = 300
UNCAPPED_SHARE = 0.9
MIN_P90_MEDIAN_RATIO = 2.0
CAP_MULTIPLIER = 1.2


def _p90(values):
    ordered = sorted(values)
    return ordered[math.ceil(0.9 * len(ordered)) - 1]


def _saving(evts, cap, pricing):
    current = chiffrer(evts, pricing)
    capped = []
    for e in evts:
        s = copy.deepcopy(e)
        s["usage"]["output_tokens"] = min(s["usage"]["output_tokens"], cap)
        capped.append(s)
    alternative = chiffrer(capped, pricing)
    a, b = current["cout_mensuel_usd"], alternative["cout_mensuel_usd"]
    if a is None or b is None:
        reasons = sorted({m.split(": ", 1)[-1] for m in current["manquants"] + alternative["manquants"]})
        return None, reasons
    return a - b, []


def detect(events, pricing=None):
    groups = defaultdict(list)
    for e in events:
        if e.get("error") is None and e["usage"].get("output_tokens") is not None:
            groups[(e["app_id"], e["model"], template_of(e))].append(e)

    findings = []
    for (app, model, template), evts in sorted(groups.items()):
        if len(evts) < MIN_CALLS:
            continue
        outputs = [e["usage"]["output_tokens"] for e in evts]
        med = median(outputs)
        if med < MIN_MEDIAN_OUTPUT_TOKENS:
            continue
        uncapped = sum(e["request"]["params"].get("max_tokens") is None for e in evts) / len(evts)
        if uncapped < UNCAPPED_SHARE:
            continue
        p90 = _p90(outputs)
        if p90 / med < MIN_P90_MEDIAN_RATIO:
            continue
        truncated = sum(e["response"].get("finish_reason") == "length" for e in evts) / len(evts)
        cap = math.ceil(med * CAP_MULTIPLIER)
        saving, missing = _saving(evts, cap, pricing)
        saving_txt = (f" Plafonner autour de {cap} jetons économiserait environ {saving:.2f} $ par mois, "
                      "non démontré sans rejeu."
                      if saving is not None else " Économie non chiffrable et non démontrée.")
        findings.append({
            "finding_id": f"f_{app}_{template}_verbose_output",
            "rule": "verbose_output",
            "app_id": app,
            "model": model,
            "template": template,
            "severity": "trim",
            "title": (f"{len(evts)} appels à {model} sans plafond de longueur : réponse typique "
                      f"d'environ {med:.0f} jetons, mais le 90e centile atteint {p90:.0f}."
                      f"{saving_txt}"),
            "proven": False,
            "event_ids": [e["event_id"] for e in evts],
            "evidence": {
                "calls": len(evts),
                "median_output_tokens": med,
                "p90_output_tokens": p90,
                "uncapped_share": round(uncapped, 3),
                "truncated_share": round(truncated, 3),
                "suggested_cap_tokens": cap,
                "est_saving_month_usd": saving,
                "saving_missing": missing,
            },
        })
    return findings
