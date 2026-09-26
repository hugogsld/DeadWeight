"""R7 — excess_reasoning : un modele de raisonnement qui reflechit longtemps pour ecrire trois mots.

Signal : parmi les appels a un modele qui facture usage.reasoning_tokens (OpenAI o1/o3/gpt-5...),
un groupe (application x modele x gabarit de prompt, meme decoupage que low_entropy/oversized_model)
ou la part de raisonnement dans les tokens factures est ecrasante alors que la reponse visible
tient en quelques tokens. Le raisonnement invisible est facture au tarif de sortie (voir
schemas/EVENT.md : completion_tokens_details.reasoning_tokens est un sous-ensemble documente de
usage.output_tokens chez OpenAI) : ce n'est pas un cout cache, c'est un cout mesurable.

Portee volontairement limitee au format openai : c'est le seul fournisseur ou reasoning_tokens
est garanti etre un sous-ensemble de output_tokens. Chez Anthropic le champ est toujours null
(exclu en amont). Chez Gemini, thoughtsTokenCount est facture A PART de candidatesTokenCount
(reasoning_tokens n'est pas soustractible de output_tokens sans se tromper) ; le retirer quand
meme produirait un chiffre faux presente comme une mesure, ce que ce projet interdit. Ces appels
sont donc ignores plutot que mal estimes — angle mort assume, documente dans README/PR.

Seuils et raisonnement :
- MIN_CALLS = 30 : meme seuil que low_entropy/oversized_model ; en dessous, une mediane n'est
  pas representative.
- MIN_REASONING_SHARE = 0.6 : au moins trois tokens factures sur cinq consacres a un
  raisonnement jamais visible, c'est le raisonnement qui domine la facture, pas la reponse.
- MAX_MEDIAN_VISIBLE_TOKENS = 40 : meme ordre de grandeur que le plafond de oversized_model
  (50 tokens) ; une reponse visible (output_tokens - reasoning_tokens) de 40 tokens ou moins est
  une phrase, pas une demonstration qui justifierait un long raisonnement prealable.
- MAX_DISTINCT_OUTPUTS = 4 (repris de low_entropy.CUT_DISTINCT) : alternative si la reponse
  visible n'est pas courte en tokens mais tres peu variee (aiguillage deguise en reponse longue).

Chiffrage : l'economie estimee est un plafond haut, jamais une mesure. Elle simule la
suppression TOTALE des tokens de raisonnement (usage.output_tokens - usage.reasoning_tokens,
usage.reasoning_tokens mis a zero) et compare le cout via report.cost.chiffrer. En pratique,
reduire l'effort de raisonnement (et non le supprimer) recuperera moins que ce plafond.

Angle mort : le contenu du raisonnement n'est jamais visible (les fournisseurs le masquent) ;
un raisonnement legitimement necessaire (verification multi-etapes) peut ressembler, une fois
chiffre, au meme profil qu'un raisonnement gaspille sur une question triviale. D'ou
proven=False : seul un rejeu a effort de raisonnement reduit peut confirmer l'economie.
"""
import copy
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

from report.cost import chiffrer
from rules.low_entropy import normalize, template_of

PRICING_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "pricing.json"

MIN_CALLS = 30
MIN_REASONING_SHARE = 0.6
MAX_MEDIAN_VISIBLE_TOKENS = 40
MAX_DISTINCT_OUTPUTS = 4


def _load_pricing():
    return json.loads(PRICING_PATH.read_text(encoding="utf-8"))


def _eligible(evts):
    """Appels openai factures (usage present), issus d'un modele de raisonnement, reponse textuelle."""
    ok = [e for e in evts if not e.get("error") and e["provider"] == "openai"
          and e["usage"].get("output_tokens") is not None
          and e["usage"].get("reasoning_tokens") is not None
          and e["usage"]["reasoning_tokens"] > 0
          and e["usage"]["output_tokens"] > 0
          and e["response"].get("content") is not None]
    return ok if len(ok) >= MIN_CALLS else None


def _saving(evts, pricing):
    """Plafond haut : cout si le raisonnement etait entierement retire de la facture."""
    current = chiffrer(evts, pricing)
    trimmed = []
    for e in evts:
        s = copy.deepcopy(e)
        s["usage"]["output_tokens"] = max(s["usage"]["output_tokens"] - s["usage"]["reasoning_tokens"], 0)
        s["usage"]["reasoning_tokens"] = 0
        trimmed.append(s)
    alternative = chiffrer(trimmed, pricing)
    a, b = current["cout_mensuel_usd"], alternative["cout_mensuel_usd"]
    if a is None or b is None:
        reasons = sorted({m.split(": ", 1)[-1] for m in current["manquants"] + alternative["manquants"]})
        return None, reasons
    return a - b, []


def detect(events, pricing=None):
    pricing = _load_pricing() if pricing is None else pricing
    groups = defaultdict(list)
    for e in events:
        groups[(e["app_id"], e["model"], template_of(e))].append(e)

    findings = []
    for (app, model, template), evts in sorted(groups.items()):
        ok = _eligible(evts)
        if not ok:
            continue
        share = median(e["usage"]["reasoning_tokens"] / e["usage"]["output_tokens"] for e in ok)
        if share < MIN_REASONING_SHARE:
            continue
        visible = [max(e["usage"]["output_tokens"] - e["usage"]["reasoning_tokens"], 0) for e in ok]
        med_visible = median(visible)
        outputs = [normalize(e["response"]["content"]) for e in ok]
        distinct = len(set(outputs))
        if med_visible > MAX_MEDIAN_VISIBLE_TOKENS and distinct > MAX_DISTINCT_OUTPUTS:
            continue
        saving, missing = _saving(ok, pricing)
        saving_txt = (f" Plafond d'économie si le raisonnement était supprimé : {saving:.2f} $ par mois, "
                      "non démontré sans rejeu à effort de raisonnement réduit."
                      if saving is not None else " Économie non chiffrable et non démontrée.")
        findings.append({
            "finding_id": f"f_{app}_{template}_excess_reasoning",
            "rule": "excess_reasoning",
            "app_id": app,
            "model": model,
            "template": template,
            "severity": "candidate",
            "title": (f"{len(ok)} appels à {model} facturent {share * 100:.0f} % de leurs jetons de sortie "
                      f"en raisonnement invisible, pour une réponse visible d'environ {med_visible:.0f} jetons."
                      f"{saving_txt}"),
            "proven": False,
            "event_ids": [e["event_id"] for e in ok],
            "evidence": {
                "calls": len(ok),
                "median_reasoning_share": round(share, 3),
                "median_visible_output_tokens": med_visible,
                "distinct_outputs": distinct,
                "est_saving_month_usd": saving,
                "saving_missing": missing,
            },
        })
    return findings
