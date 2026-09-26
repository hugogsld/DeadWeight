"""M2 — Recommandations de modèles.

R2 propose un petit modèle de la même famille. M2 cherche dans tout le catalogue, seulement
pour les tâches que R2 a jugées simples (garde-fou qualité), sous trois contraintes vérifiables :

- capacités : outils, sortie JSON, images et contexte (plus gros appel observé) ;
- éditeur documenté : seules les fiches sourcées par la recherche (source « recherche ») ;
- coût : recalculé par report.cost sur les jetons réels du client, pas sur un prix affiché.

Trois options : la moins chère ; le meilleur compromis, c'est-à-dire la moins chère chez le
même éditeur, par son API (hors poids ouverts, servis par des hébergeurs tiers) ; la souveraine
(éditeur européen).
Sans indice de qualité (M1.2), rien n'est prouvé : la preuve est le rejeu (M2.2).
"""
import copy

from catalog import editor_index, editor_of, info, load_pricing, load_providers
from catalog.capabilities import load as load_capabilities
from report.cost import chiffrer, lookup
from rules import oversized_model

JSON_FORMATS = {"json_object", "json_schema"}
# Poids ouverts publiés par un éditeur qui a sa propre API : servis par des hébergeurs tiers,
# ils n'héritent ni de l'API ni de l'hébergement UE de l'éditeur.
OPEN_WEIGHTS = ("openai/gpt-oss", "google/gemma")


def needs(events):
    """Ce que le trafic observé exige du modèle."""
    ok = [e for e in events if e.get("error") is None]
    sizes = [(e["usage"].get("input_tokens") or 0) + (e["usage"].get("output_tokens") or 0)
             for e in ok if e["usage"].get("input_tokens") is not None]
    return {
        "outils": any(e["request"].get("tools") or e["response"].get("tool_calls") for e in ok),
        "json": any((e["request"].get("params") or {}).get("response_format") in JSON_FORMATS for e in ok),
        "images": any(m.get("n_images") for e in ok for m in e["request"].get("messages", [])),
        "contexte_min": max(sizes) if sizes else None,
    }


def compatible(caps, need):
    if caps is None or need["contexte_min"] is None:
        return False  # capacités ou taille inconnues : on ne peut pas vérifier
    return (caps["contexte"] >= need["contexte_min"]
            and (caps["outils"] or not need["outils"])
            and (caps["json"] or not need["json"])
            and (caps["images"] or not need["images"]))


def _cost_with(events, model, pricing):
    swapped = []
    for e in events:
        e = copy.copy(e)
        e["model"] = model
        swapped.append(e)
    return chiffrer(swapped, pricing)["cout_mensuel_usd"]


def recommend(events, pricing=None, providers=None, capabilities=None):
    """Trois options pour un groupe d'appels au même modèle. Toujours « non prouvé »."""
    pricing = pricing if pricing is not None else load_pricing()
    providers = providers if providers is not None else load_providers()
    capabilities = capabilities if capabilities is not None else load_capabilities()
    index = editor_index(pricing)
    current = events[0]["model"]
    current_editor = editor_of(current, index)
    current_price = lookup(pricing, current)
    need = needs(events)
    before = chiffrer(events, pricing)["cout_mensuel_usd"]
    result = {"modele": current, "editeur": current_editor, "appels": len(events),
              "cout_mensuel_usd": before, "besoins": need, "options": {}, "prouve": False,
              "raison": None}
    if before is None:
        result["raison"] = "coût actuel non mesurable : pas de comparaison possible"
        return result
    if need["contexte_min"] is None:
        result["raison"] = "jetons non capturés : taille de contexte nécessaire inconnue"
        return result

    candidates = []
    for name in pricing:
        if "/" not in name or name.startswith("~") or ":" in name:
            continue
        sheet = providers.get(name.split("/", 1)[0])
        if not sheet or sheet["source"] != "recherche" or pricing[name] == current_price:
            continue
        if not compatible(capabilities.get(name), need):
            continue
        cost = _cost_with(events, name, pricing)
        if cost is not None and cost < before:
            candidates.append((cost, name))
    candidates.sort()

    def option(pool):
        if not pool:
            return None
        cost, name = pool[0]
        sheet = info(name, pricing, providers, index)
        if name.startswith(OPEN_WEIGHTS):
            sheet.update(hebergement_ue=None, option_ue="poids ouverts : dépend de l'hébergeur choisi")
        return {"modele": name, "cout_mensuel_usd": cost, "economie_usd": before - cost,
                "facteur": round(before / cost, 1) if cost > 0 else None,
                **{k: sheet[k] for k in ("editeur", "pays", "hebergement_ue", "souverain", "option_ue")}}

    result["options"] = {
        "moins_cher": option(candidates),
        "meilleur_compromis": option([c for c in candidates if c[1].split("/", 1)[0] == current_editor
                                      and not c[1].startswith(OPEN_WEIGHTS)]),
        "souverain": option([c for c in candidates if providers[c[1].split("/", 1)[0]]["souverain"]]),
    }
    if not candidates:
        result["raison"] = "aucun modèle compatible moins cher au catalogue"
    return result


def alternatives_modele(events, pricing=None, providers=None, capabilities=None, top=5):
    """Outil de l'agent A1 et entrée du rapport.

    Garde-fou qualité : on ne cherche un remplaçant que là où R2 (oversized_model) a jugé
    la tâche simple (réponses courtes, pas d'outils, entrée modeste). Un vrai raisonnement
    n'est jamais envoyé vers un petit modèle, même beaucoup moins cher. Plus chers d'abord.
    """
    pricing = pricing if pricing is not None else load_pricing()
    providers = providers if providers is not None else load_providers()
    capabilities = capabilities if capabilities is not None else load_capabilities()
    by_id = {e["event_id"]: e for e in events}
    out = []
    for finding in oversized_model.detect(events, pricing):
        evts = [by_id[i] for i in finding["event_ids"]]
        rec = recommend(evts, pricing, providers, capabilities)
        out.append({"app_id": finding["app_id"], "finding_id": finding["finding_id"],
                    "suggestion_r2": finding["evidence"]["suggested_model"], **rec})
    out.sort(key=lambda r: -(r["cout_mensuel_usd"] or 0))
    return out[:top]
