"""R14/levier 13 : rafales nocturnes régulières, candidates à l'API batch d'un fournisseur.
Jamais « pass » : rules.batch_eligible chiffre une remise de scénario (BATCH_DISCOUNT = 50 %),
pas un prix batch vérifié par modèle, et l'éligibilité réelle (absence d'utilisateur, délai
accepté) ne s'observe pas dans l'historique — le dire mesuré serait fabriquer une valeur."""
from optimize.propose import ESTIME, NON_TESTE, _cost, _m


def batch_proposal(finding, events):
    ev = finding["evidence"]
    group = [e for e in events if e["event_id"] in set(finding["event_ids"])]
    spent = _cost(group)
    return {
        "type": "batch", "finding_id": finding["finding_id"], "app_id": finding["app_id"], "model": finding["model"],
        "changement": "Passer ces rafales nocturnes régulières par l'API batch du fournisseur "
                      f"(remise de scénario annoncée : {round(ev['assumed_discount'] * 100)} %).",
        "verdict": "non_teste",
        "raisons": ["remise batch non vérifiée par modèle", ev["eligibility_unverified"]],
        "mesures": {
            "precision": _m(None, NON_TESTE, "%",
                            "absence d'utilisateur et modèle batch du fournisseur non observables dans l'historique"),
            "cout": (_m(round(-ev["assumed_discount"] * 100, 1), ESTIME, "%",
                       "remise de scénario, jamais vérifiée par modèle") if spent is not None
                    else _m(None, NON_TESTE, "%")),
        },
        "cout_usd": ({"avant": spent, "apres": spent * (1 - ev["assumed_discount"]), "statut": ESTIME}
                    if spent is not None else None),
    }
