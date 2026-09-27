"""R9/levier 12 : coût déjà facturé des relances (même demande, même échec facturé, relancée
en moins de rules.paid_errors.RETRY_WINDOW_SECONDS). Corriger la cause de l'échec ne change pas
la réponse gardée (celle de la relance, déjà obtenue) : seule la dépense du premier essai raté
disparaît, la précision n'est pas affectée. Les échecs facturés jamais relancés (rate seul au-
dessus du seuil) ne sont pas comptés ici : supprimer leur cause changerait la réponse obtenue,
ce que rien ici ne mesure — cette proposition ne porte que sur le doublon prouvé."""
from optimize.propose import MESURE, NON_TESTE, _cost, _m, _pct_change


def errors_proposal(finding, events):
    retry_ids = set(finding["evidence"]["retry_event_ids"])
    if not retry_ids:
        return None
    group = [e for e in events if e["event_id"] in set(finding["event_ids"])]
    kept = [e for e in group if e["event_id"] not in retry_ids]
    before, after = _cost(group), _cost(kept)
    return {
        "type": "erreurs", "finding_id": finding["finding_id"], "app_id": finding["app_id"], "model": finding["model"],
        "changement": f"Corriger la cause de l'échec avant de relancer ({len(retry_ids)} relance(s) "
                      "facturée(s) évitée(s)).",
        "verdict": "pass", "raisons": [],
        "mesures": {
            "precision": _m(100.0, MESURE, "%",
                            "la réponse gardée est celle de la relance, déjà obtenue : rien ne change pour l'utilisateur"),
            "relances_evitees": _m(len(retry_ids), MESURE),
            "cout": (_m(_pct_change(before, after), MESURE, "%") if before is not None
                    else _m(None, NON_TESTE, "%")),
        },
        "cout_usd": {"avant": before, "apres": after, "statut": MESURE} if before is not None else None,
    }
