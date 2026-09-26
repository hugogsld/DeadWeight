"""Levier 16 — data_outside_eu : des données qui partent hors d'Europe.

Pour chaque groupe d'appels (application × modèle × gabarit × destination), la destination
réelle (upstream capturé par la passerelle, sinon déduite du format d'appel) est qualifiée
par le catalogue (fixtures/providers.json, « hotes ») : traitée dans l'UE, hors UE, ou non
garantie. Hors UE ou non garanti : constat, avec deux pistes européennes :

- le même modèle en région UE, quand l'éditeur le propose (aucun changement de qualité) ;
- un modèle d'éditeur européen sur sa propre route, seulement si R2 a jugé la tâche simple
  (catalog.recommend.sovereign_alternative) ; sinon, à choisir au banc de modèles.

Rien n'est prouvé : l'alternative se teste au banc avant de changer (proven=false).
Hôte inconnu du catalogue : pas de constat, on ne prétend rien.
"""
from collections import defaultdict

from catalog import destination, editor_index, editor_of, load_hosts, load_pricing, load_providers
from catalog.capabilities import load as load_capabilities
from catalog.recommend import sovereign_alternative
from report.cost import chiffrer
from rules import oversized_model
from rules.low_entropy import template_of


def detect(events, pricing=None, providers=None, capabilities=None):
    pricing = pricing if pricing is not None else load_pricing()
    providers = providers if providers is not None else load_providers()
    capabilities = capabilities if capabilities is not None else load_capabilities()
    hosts, index = load_hosts(), editor_index(pricing)
    simple = {i for f in oversized_model.detect(events, pricing) for i in f["event_ids"]}

    groups = defaultdict(list)
    for e in events:
        if e.get("error") is None:
            dest = destination(e, hosts)
            if dest["ue"] is not True and dest["note"] is not None:
                groups[(e["app_id"], e["model"], template_of(e), dest["hote"])].append((e, dest))

    findings = []
    for (app, model, template, host), pairs in sorted(groups.items()):
        evts, dest = [e for e, _ in pairs], pairs[0][1]
        editor = providers.get(editor_of(model, index) or dest.get("editeur")) or {}
        same_model_eu = editor.get("option_ue") if editor.get("hebergement_ue") is not True else None
        is_simple = all(e["event_id"] in simple for e in evts)
        alt = sovereign_alternative(evts, is_simple, pricing, providers, capabilities)

        where = f"vers {host}" + (f" ({dest['pays']})" if dest["pays"] else "")
        status = "sortent de l'Europe" if dest["ue"] is False else "ne sont pas garanties de rester en Europe"
        note = dest["note"][0].upper() + dest["note"][1:]
        deduced = " Destination déduite du format d'appel, non observée." if dest["certitude"] == "deduite" else ""
        options = []
        if same_model_eu:
            options.append(f"même modèle en Europe : {same_model_eu}")
        if alt:
            options.append(f"modèle européen : {alt['modele']} via {alt['hebergeur']}, à tester au banc")
        else:
            options.append("modèle européen : à choisir au banc de modèles"
                           + ("" if is_simple else " (tâche non jugée simple : pas de remplaçant désigné sans mesure)"))
        findings.append({
            "finding_id": f"f_{app}_{template}_{host}_outside_eu",
            "rule": "data_outside_eu",
            "app_id": app,
            "model": model,
            "template": template,
            "severity": "candidate",
            "title": (f"{len(evts)} appels à {model} partent {where} : les données {status}. {note}."
                      f"{deduced} Pistes : " + " ; ".join(options) + "."),
            "proven": False,
            "event_ids": [e["event_id"] for e in evts],
            "evidence": {
                "calls": len(evts),
                "hote": host,
                "traitement_ue": dest["ue"],
                "pays": dest["pays"],
                "certitude": dest["certitude"],
                "meme_modele_en_ue": same_model_eu,
                "tache_simple": is_simple,
                "alternative_europeenne": alt,
                "cout_mensuel_usd": chiffrer(evts, pricing)["cout_mensuel_usd"],
            },
        })
    return findings
