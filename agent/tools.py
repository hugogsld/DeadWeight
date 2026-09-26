"""A1.1 — Les modules de Deadweight, vus comme des outils par l'agent auditeur.

Chaque outil rend un petit dict JSON : l'agent lit des résumés, jamais des prompts
entiers. Tous les chiffres viennent du code (règles, chiffrage, rejeu) ; l'agent
choisit quoi regarder et quoi prouver, il ne calcule rien.
"""
import json

from catalog.recommend import recommend
from proof.extract import extract_rules
from proof.replay import replay
from report.audit import RULE_TEXT, _discover_detectors, _figures

EXCERPT = 160  # caractères max par extrait de conversation montré à l'agent
REPLAYABLE = {"low_entropy_output"}  # seules les règles d'aiguillage se prouvent par rejeu
ALTERNATIVES = {"oversized_model"}  # bloc M : autres modèles, seulement là où R2 a jugé la tâche simple
OPTION_NAMES = {"moins_cher": "le moins cher", "meilleur_compromis": "même éditeur", "souverain": "éditeur européen"}


def _money(v):
    return None if v is None else round(v, 2)


def _small_money(v):
    """Montant d'un modèle de remplacement : deux chiffres significatifs sous 1 $, sinon « 0.0 »
    cacherait l'ordre de grandeur et l'agent ne pourrait pas le citer (garde-fou A1.3)."""
    return None if v is None else round(v, 2) if v >= 1 else float(f"{v:.2g}")


def _pct(v):
    return None if v is None else round(v * 100, 1)


def _cost(figures):
    """Coût mensuel si projetable, sinon coût observé : jamais les deux mélangés."""
    if figures.get("cout_mensuel_usd") is not None:
        return {"cout_mensuel_usd": _money(figures["cout_mensuel_usd"])}
    if figures.get("cout_observe_usd") is not None:
        return {"cout_observe_usd": _money(figures["cout_observe_usd"])}
    return {"cout": "non mesurable"}


def _saving(before, after):
    return None if before is None or after is None or before <= 0 else round((before - after) / before * 100, 1)


def _cut(text):
    text = " ".join(str(text or "").split())
    return text if len(text) <= EXCERPT else text[:EXCERPT] + "…"


WHY = {"pourquoi": {"type": "string", "description": "Une phrase : pourquoi tu appelles cet outil maintenant."}}


def _spec(name, description, props=None, required=()):
    props = {**WHY, **(props or {})}
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": props, "required": ["pourquoi", *required],
                           "additionalProperties": False}}


SPECS = [
    _spec("vue_ensemble", "Applications observées : volume d'appels, modèles, coût."),
    _spec("lancer_regles", "Lance les six vérifications. Rend les constats avec leur coût, du plus cher au moins cher."),
    _spec("detail_constat", "Détail d'un constat : mesures et trois extraits de conversation tronqués.",
          {"finding_id": {"type": "string"}}, ["finding_id"]),
    _spec("alternatives_modele", "Pour un constat « modèle haut de gamme pour une tâche simple » : autres modèles "
                                 "compatibles, tous fournisseurs (le moins cher, même éditeur, éditeur européen), "
                                 "coût recalculé sur le trafic observé. Ce sont des pistes non prouvées.",
          {"finding_id": {"type": "string"}}, ["finding_id"]),
    _spec("prouver", "Pour un constat « répond toujours la même chose » : extrait des règles fixes puis les rejoue "
                     "sur l'historique. Rend le taux d'accord, le verdict (seuil 95 %) et le coût avant/après.",
          {"finding_id": {"type": "string"}}, ["finding_id"]),
    {"name": "publier_plan", "description": "Termine l'audit : plan d'action priorisé. Chaque chiffre cité doit venir d'un résultat d'outil.",
     "parameters": {"type": "object", "properties": {
         "resume": {"type": "string", "description": "Deux ou trois phrases pour un dirigeant."},
         "actions": {"type": "array", "maxItems": 5, "items": {"type": "object", "properties": {
             "priorite": {"type": "integer"}, "finding_id": {"type": "string"},
             "action": {"type": "string"}, "justification": {"type": "string"}},
             "required": ["priorite", "finding_id", "action", "justification"], "additionalProperties": False}}},
         "required": ["resume", "actions"], "additionalProperties": False}},
]


class AuditTools:
    """État partagé des outils sur un jeu d'événements. ``llm`` : client d'extraction (sinon hors ligne)."""

    def __init__(self, events, llm=None, detectors=None):
        self.events = list(events)
        self.by_id = {e["event_id"]: e for e in self.events}
        self.llm = llm
        self.detectors = detectors if detectors is not None else _discover_detectors()
        self._findings = None
        self.proofs = {}
        self.methods = {}  # méthode d'extraction par constat prouvé : « offline » ou « llm »
        self.attempted = set()  # constats passés par prouver, même en échec

    def findings(self):
        if self._findings is None:
            found = [f for _, detect in self.detectors for f in detect(self.events)]
            costed = [(f, _figures([self.by_id[i] for i in f["event_ids"] if i in self.by_id])) for f in found]
            costed.sort(key=lambda fc: -(fc[1].get("cout_mensuel_usd") or fc[1].get("cout_observe_usd") or 0))
            self._findings = costed
        return self._findings

    def _finding(self, finding_id):
        return next(((f, c) for f, c in self.findings() if f["finding_id"] == finding_id), (None, None))

    # --- outils ---
    def vue_ensemble(self):
        apps = {}
        for e in self.events:
            apps.setdefault(e["app_id"], []).append(e)
        return {"applications": [
            {"app_id": a, "appels": len(evts), "modeles": sorted({e["model"] for e in evts}),
             "erreurs": sum(e["error"] is not None for e in evts), **_cost(_figures(evts))}
            for a, evts in sorted(apps.items(), key=lambda kv: -len(kv[1]))]}

    def lancer_regles(self):
        # nb_verifications : nombre reel de verifications lancees (probleme 16, le rapport ne doit
        # pas afficher un nombre fige alors que rules/ en compte davantage ou moins).
        return {"nb_verifications": len(self.detectors), "a_prouver_avant_de_publier": self.unproven(),
                "constats": [
            {"finding_id": f["finding_id"], "verification": RULE_TEXT.get(f["rule"], (f["rule"],))[0],
             "app_id": f["app_id"], "modele": f["model"], "appels": c["nb_appels"],
             "prouvable_par_rejeu": f["rule"] in REPLAYABLE,
             "autres_modeles_disponibles": f["rule"] in ALTERNATIVES, **_cost(c)}
            for f, c in self.findings()]}

    def detail_constat(self, finding_id):
        f, c = self._finding(finding_id)
        if f is None:
            return {"erreur": f"constat inconnu : {finding_id}"}
        samples = [self.by_id[i] for i in f["event_ids"][:3] if i in self.by_id]
        return {"finding_id": finding_id, "phrase": f["title"], "gravite": f.get("severity"),
                "preuves": {k: v for k, v in f.get("evidence", {}).items() if isinstance(v, (int, float, str))},
                "latence_mediane_ms": c["latence_mediane_ms"], "temps_reponse_appels_lents_ms": c["latence_p95_ms"],
                **_cost(c),
                "extraits": [{"entree": _cut(" ".join(m.get("content") or "" for m in e["request"]["messages"]
                                                      if m["role"] == "user")),
                              "reponse": _cut(e["response"].get("content"))} for e in samples]}

    def prouver(self, finding_id):
        f, _ = self._finding(finding_id)
        if f is None:
            return {"erreur": f"constat inconnu : {finding_id}"}
        if f["rule"] not in REPLAYABLE:
            return {"erreur": "ce constat ne se prouve pas par rejeu (seuls les aiguillages le peuvent)"}
        self.attempted.add(finding_id)
        rules = extract_rules(f, self.events, llm=self.llm)
        proof = replay(f, self.events, rules)
        self.proofs[finding_id] = proof
        self.methods[finding_id] = rules["method"]
        return {"finding_id": finding_id, "verdict": proof["verdict"], "raisons": proof["reasons"][:3],
                "categories": [c["key"] for c in rules["categories"]], "methode_extraction": rules["method"],
                "appels_rejoues": proof["n_replayed"], "accord_pct": _pct(proof["agreement_rate"]),
                "couverture_regles_pct": _pct(proof["rules_coverage"]), "seuil_pct": _pct(proof["threshold"]),
                "cout_avant_mensuel_usd": _money(proof["cost_before_month_usd"]),
                "cout_apres_mensuel_usd": _money(proof["cost_after_month_usd"]),
                "facteur_cout": proof["cost_factor"],
                "economie_pct": _saving(proof["cost_before_month_usd"], proof["cost_after_month_usd"]),
                "temps_reponse_appels_lents_avant_ms": proof["p95_before_ms"], "temps_reponse_appels_lents_apres_ms": proof["p95_after_ms"]}

    def alternatives_modele(self, finding_id):
        f, _ = self._finding(finding_id)
        if f is None:
            return {"erreur": f"constat inconnu : {finding_id}"}
        if f["rule"] not in ALTERNATIVES:
            return {"erreur": "seulement pour un modèle haut de gamme sur une tâche simple : ailleurs, "
                              "changer de modèle risque de dégrader les réponses"}
        rec = recommend([self.by_id[i] for i in f["event_ids"] if i in self.by_id])
        options = []
        for key, o in rec["options"].items():
            if o:
                options.append({
                    "option": OPTION_NAMES[key], "modele": o["modele"],
                    "cout_mensuel_usd": _small_money(o["cout_mensuel_usd"]), "facteur_cout": o["facteur"],
                    "economie_pct": _saving(rec["cout_mensuel_usd"], o["cout_mensuel_usd"]),
                    "pays_editeur": o["pays"],
                    "donnees_en_europe": {True: "oui", False: "non", "sous_conditions": "sous conditions",
                                          None: "non garanti"}[o["hebergement_ue"]],
                    "cout_sous_estime": o["raisonnement"]})
        return {"finding_id": finding_id, "modele_actuel": rec["modele"],
                "cout_mensuel_actuel_usd": _small_money(rec["cout_mensuel_usd"]),
                "options": options, "raison_si_aucune": rec["raison"],
                "a_retenir": "pistes non prouvées : à tester sur une partie du trafic avant de changer ; "
                             "cout_sous_estime = modèle qui réfléchit avant de répondre, sa réflexion est facturée "
                             "en plus et n'est pas comptée ici"}

    def unproven(self):
        """Constats prouvables par rejeu que l'agent n'a pas encore tenté de prouver."""
        return [f["finding_id"] for f, _ in self.findings()
                if f["rule"] in REPLAYABLE and f["finding_id"] not in self.attempted]

    def proof_status(self, finding_id):
        """Décidé par le code, jamais par le modèle."""
        proof = self.proofs.get(finding_id)
        if proof is None:
            return "piste à vérifier"
        return "prouvé par rejeu" if proof["verdict"] == "pass" else "rejeu refusé"

    def call(self, name, args):
        """Exécute un outil (sauf publier_plan, traité par la boucle). Jamais d'exception vers l'agent."""
        handler = {"vue_ensemble": self.vue_ensemble, "lancer_regles": self.lancer_regles,
                   "detail_constat": self.detail_constat, "prouver": self.prouver,
                   "alternatives_modele": self.alternatives_modele}.get(name)
        if handler is None:
            return {"erreur": f"outil inconnu : {name}"}
        args = {k: v for k, v in args.items() if k != "pourquoi"}
        try:
            return handler(**args)
        except TypeError:
            return {"erreur": f"arguments invalides pour {name} : {json.dumps(args, ensure_ascii=False)}"}
        except Exception as exc:  # un outil qui casse ne doit pas casser l'audit
            return {"erreur": f"{name} a échoué ({type(exc).__name__})"}
