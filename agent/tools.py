"""A1.1 — Les modules de Deadweight, vus comme des outils par l'agent auditeur.

Chaque outil rend un petit dict JSON : l'agent lit des résumés, jamais des prompts
entiers. Tous les chiffres viennent du code (règles, chiffrage, rejeu) ; l'agent
choisit quoi regarder et quoi prouver, il ne calcule rien.
"""
import json

from proof.extract import extract_rules
from proof.replay import replay
from report.audit import RULE_TEXT, _discover_detectors, _figures

EXCERPT = 160  # caractères max par extrait de conversation montré à l'agent
REPLAYABLE = {"low_entropy_output"}  # seules les règles d'aiguillage se prouvent par rejeu


def _money(v):
    return None if v is None else round(v, 2)


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
        return {"a_prouver_avant_de_publier": self.unproven(), "constats": [
            {"finding_id": f["finding_id"], "verification": RULE_TEXT.get(f["rule"], (f["rule"],))[0],
             "app_id": f["app_id"], "modele": f["model"], "appels": c["nb_appels"],
             "prouvable_par_rejeu": f["rule"] in REPLAYABLE, **_cost(c)}
            for f, c in self.findings()]}

    def detail_constat(self, finding_id):
        f, c = self._finding(finding_id)
        if f is None:
            return {"erreur": f"constat inconnu : {finding_id}"}
        samples = [self.by_id[i] for i in f["event_ids"][:3] if i in self.by_id]
        return {"finding_id": finding_id, "phrase": f["title"], "gravite": f.get("severity"),
                "preuves": {k: v for k, v in f.get("evidence", {}).items() if isinstance(v, (int, float, str))},
                "latence_mediane_ms": c["latence_mediane_ms"], "latence_p95_ms": c["latence_p95_ms"],
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
        return {"finding_id": finding_id, "verdict": proof["verdict"], "raisons": proof["reasons"][:3],
                "categories": [c["key"] for c in rules["categories"]], "methode_extraction": rules["method"],
                "appels_rejoues": proof["n_replayed"], "accord_pct": _pct(proof["agreement_rate"]),
                "couverture_regles_pct": _pct(proof["rules_coverage"]), "seuil_pct": _pct(proof["threshold"]),
                "cout_avant_mensuel_usd": _money(proof["cost_before_month_usd"]),
                "cout_apres_mensuel_usd": _money(proof["cost_after_month_usd"]),
                "facteur_cout": proof["cost_factor"],
                "economie_pct": _saving(proof["cost_before_month_usd"], proof["cost_after_month_usd"]),
                "p95_avant_ms": proof["p95_before_ms"], "p95_apres_ms": proof["p95_after_ms"]}

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
                   "detail_constat": self.detail_constat, "prouver": self.prouver}.get(name)
        if handler is None:
            return {"erreur": f"outil inconnu : {name}"}
        args = {k: v for k, v in args.items() if k != "pourquoi"}
        try:
            return handler(**args)
        except TypeError:
            return {"erreur": f"arguments invalides pour {name} : {json.dumps(args, ensure_ascii=False)}"}
        except Exception as exc:  # un outil qui casse ne doit pas casser l'audit
            return {"erreur": f"{name} a échoué ({type(exc).__name__})"}
