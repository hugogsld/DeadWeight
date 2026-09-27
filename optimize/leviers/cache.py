"""R8/levier 07 : les appels en trop d'une rafale de doublons stricts (même demande normalisée,
même réponse, dans l'heure). Aucun risque de qualité : rules.duplicate_calls a déjà vérifié que
la réponse servie une deuxième fois est identique à celle qu'un cache aurait renvoyée ; la
précision de 100 % est la définition même du constat, pas une hypothèse."""
from optimize.propose import MESURE, NON_TESTE, _cost, _m, _pct_change


def cache_proposal(finding, events):
    ids = set(finding["event_ids"])
    wasted_ids = set(finding["evidence"]["wasted_event_ids"])
    group = [e for e in events if e["event_id"] in ids]
    kept = [e for e in group if e["event_id"] not in wasted_ids]
    before, after = _cost(group), _cost(kept)
    return {
        "type": "cache", "finding_id": finding["finding_id"], "app_id": finding["app_id"], "model": finding["model"],
        "changement": f"Mettre en cache les réponses aux demandes déjà posées dans l'heure précédente "
                      f"({len(wasted_ids)} appel(s) en trop évité(s) sur {len(group)}).",
        "verdict": "pass", "raisons": [],
        "mesures": {
            "precision": _m(100.0, MESURE, "%",
                            "réponse déjà vérifiée identique par le détecteur : servir le cache ne change rien"),
            "appels_evites": _m(len(wasted_ids), MESURE),
            "cout": (_m(_pct_change(before, after), MESURE, "%") if before is not None
                    else _m(None, NON_TESTE, "%")),
        },
        "cout_usd": {"avant": before, "apres": after, "statut": MESURE} if before is not None else None,
    }
