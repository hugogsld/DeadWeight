"""A1.2 et A1.3 — La boucle de l'agent auditeur, et son garde-fou sur les chiffres.

L'agent tourne chez le client, avec sa clé (DW_LLM_API_KEY) : ses données ne passent
jamais par nous. Il enquête avec les outils de agent.tools, puis publie un plan
d'action. Un plan qui cite un chiffre absent des résultats d'outils est refusé : le
modèle doit se corriger. Tout est journalisé pour le rapport.
"""
import json
import re
import urllib.request

from agent.tools import SPECS
from report.cost import PRICING_PATH, lookup

MAX_STEPS = 25          # appels au modèle
MAX_RESULT_CHARS = 4000  # un résultat d'outil trop long est tronqué pour l'agent
FREE_INTEGERS = range(0, 11)  # priorités, « trois actions » : pas des mesures

SYSTEM = """Tu es l'auditeur de Deadweight. Tu audites les appels d'IA d'une entreprise pour trouver
ce qui coûte cher sans servir : des modèles qui ne font qu'aiguiller, des modèles trop gros, des
boucles, du contexte ou du cache mal utilisés.

Méthode :
1. vue_ensemble, puis lancer_regles.
2. Commence par les constats les plus chers. Regarde le détail de ceux qui comptent.
3. Pour chaque constat prouvable par rejeu, appelle prouver : c'est obligatoire avant de publier. Si le verdict est « reject », lis les
   raisons : dis honnêtement que le remplacement n'est pas prouvé, et propose d'observer plus
   longtemps (mode miroir) plutôt que de l'appliquer.
4. Pour un constat où « autres_modeles_disponibles » est vrai, appelle alternatives_modele : ce sont
   des pistes, jamais des preuves. Si « cout_sous_estime » est vrai, dis que ce modèle facture aussi sa
   réflexion et que l'économie réelle reste à mesurer.
5. Termine par publier_plan : cinq actions au plus, la plus rentable d'abord.

Règles absolues :
- Tu ne calcules rien. Chaque chiffre que tu écris doit apparaître tel quel dans un résultat d'outil.
- Tu écris en français clair, pour un dirigeant, sans jargon technique.
- Un constat non prouvé est une piste : n'écris jamais « preuve » ou « prouvé » pour lui. Seul un
  verdict « pass » de l'outil prouver est une preuve.
- Pas de sigles, d'anglicismes ni de termes techniques (A/B, logs, p95, prompt, tokens, mémoïsation) :
  écris « temps de réponse des appels les plus lents », « test sur une partie du trafic »,
  « historique de la conversation », « volume de texte envoyé », « garder en mémoire les réponses ».
- Pour chaque outil, remplis « pourquoi » : une phrase qui explique ton choix au lecteur du rapport."""

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_THOUSANDS = re.compile(r"(?<![\w.,])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?!\d)")  # « 315 220 », pas « p95 764 »

# Problème 16 : un chiffre cité à côté de ces mots doit être le champ du même nom d'un résultat
# de prouver(), pas une autre grandeur (l'économie confondue avec la couverture, par exemple).
_LABEL_FIELD = {"couverture": "couverture_regles_pct", "accord": "accord_pct",
                "économie": "economie_pct", "economie": "economie_pct"}
_LABEL_THEN_NUMBER = re.compile(r"(couverture|accord|économie|economie)\D{0,40}?(\d+(?:[.,]\d+)?)\s*%",
                                re.IGNORECASE)
_NUMBER_THEN_LABEL = re.compile(r"(\d+(?:[.,]\d+)?)\s*%\D{0,40}?(couverture|accord|économie|economie)",
                                re.IGNORECASE)
_CACHE_MENTION = re.compile(r"cache|m[ée]moire\D{0,20}r[ée]ponses|r[ée]ponses\D{0,20}m[ée]moire", re.IGNORECASE)


class OpenAIChatTools:
    """Client /chat/completions avec appel d'outils ; base_url inclut /v1."""

    def __init__(self, base_url, api_key, model, timeout=120):
        self.base_url, self.api_key, self.model, self.timeout = base_url.rstrip("/"), api_key, model, timeout

    def chat(self, messages, tools):
        body = {"model": self.model, "messages": messages,
                "tools": [{"type": "function", "function": t} for t in tools]}
        request = urllib.request.Request(
            self.base_url + "/chat/completions", method="POST",
            data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.load(response)
        return payload["choices"][0]["message"], payload.get("usage") or {}


def _numbers(text):
    return [float(n.replace(",", ".")) for n in _NUMBER.findall(_THOUSANDS.sub(lambda m: re.sub(r"\D", "", m.group()), str(text)))]


def _known(value, seen):
    """Le chiffre écrit correspond-il à un chiffre rendu par un outil, au plus à son arrondi près ?"""
    if value in FREE_INTEGERS or value in seen:  # tel quel, même avec plus de deux décimales
        return True
    for x in seen:
        for digits in (0, 1, 2):
            if round(x, digits) == value:
                return True
    return False


def _plan_texts(plan):
    """Tous les textes libres du plan : résumé, puis action et justification de chaque action."""
    return [plan.get("resume", "")] + [a.get(k, "") for a in plan.get("actions", []) for k in ("action", "justification")]


def unknown_numbers(plan, tool_outputs):
    """Chiffres du plan introuvables dans les résultats d'outils."""
    seen = {n for out in tool_outputs for n in _numbers(json.dumps(out, ensure_ascii=False))}
    return sorted({n for t in _plan_texts(plan) for n in _numbers(t) if not _known(n, seen)})


def _field_known(field, value, tool_outputs):
    """La valeur citée correspond-elle, au plus à son arrondi près, à ce champ précis d'un résultat d'outil ?"""
    for out in tool_outputs:
        if isinstance(out, dict) and out.get(field) is not None:
            for digits in (0, 1, 2):
                if round(out[field], digits) == value:
                    return True
    return False


def mislabeled_numbers(plan, tool_outputs):
    """Problème 16 : un chiffre cité à côté de « couverture », « accord » ou « économie » doit être
    la valeur du champ correspondant (couverture_regles_pct, accord_pct, economie_pct) d'un résultat
    d'outil — sinon le modèle a rattaché un chiffre réel à la mauvaise grandeur (l'économie prise
    pour la couverture, par exemple). Rend une liste de (libellé, valeur citée, champ attendu)."""
    pairs = []
    for text in _plan_texts(plan):
        pairs += [(m.group(1), m.group(2)) for m in _LABEL_THEN_NUMBER.finditer(text)]
        pairs += [(m.group(2), m.group(1)) for m in _NUMBER_THEN_LABEL.finditer(text)]
    mismatches = []
    for label, number in pairs:
        field = _LABEL_FIELD[label.lower()]
        value = float(number.replace(",", "."))
        if not _field_known(field, value, tool_outputs):
            mismatches.append((label.lower(), value, field))
    return mismatches


def unjustified_cache_recommendation(plan, tools):
    """Problème 16 : une action qui recommande de garder les réponses en mémoire (un cache) n'a de
    sens que sur des entrées identiques répétées. Sans constat « mêmes demandes payées plusieurs
    fois » (no_cache) ni « même question payée plusieurs fois, mot pour mot » (duplicate_calls), le
    modèle a proposé un cache pour des entrées différentes (des mails différents, par exemple) : la
    recommandation ne sert à rien et doit être justifiée par un constat, pas par le bon sens du modèle."""
    if any(f["rule"] in ("no_cache", "duplicate_calls") for f, _ in tools.findings()):
        return None
    for action in plan.get("actions", []):
        text = f"{action.get('action', '')} {action.get('justification', '')}"
        if _CACHE_MENTION.search(text):
            return ("plan refusé : une action recommande de garder les réponses en mémoire (un cache), mais "
                    "aucun constat « mêmes demandes payées plusieurs fois » ni « même question payée plusieurs "
                    "fois, mot pour mot » n'a été trouvé sur ce trafic : un cache ne sert qu'à des entrées "
                    "identiques répétées. Retire cette recommandation, ou appuie-la sur un tel constat, puis republie.")
    return None


def _agent_cost(model, usage):
    try:
        price = lookup(json.loads(open(PRICING_PATH, encoding="utf-8").read()), model)
        return round((usage["prompt_tokens"] * price["in"] + usage["completion_tokens"] * price["out"]) / 1e6, 4)
    except Exception:
        return None


def run_agent(tools, llm, model_name=None, max_steps=MAX_STEPS):
    """Rend {plan, journal, statut, appels_modele, cout_audit_usd}. plan vaut None si l'agent n'a pas conclu."""
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": "Audite le trafic capturé et publie ton plan d'action."}]
    journal, outputs = [], []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    nudged, steps = False, 0
    for steps in range(1, max_steps + 1):
        try:
            message, used = llm.chat(messages, SPECS)
        except Exception as exc:  # ne jamais recopier le message : il peut contenir la clé
            return _result(None, journal, f"modèle injoignable ({type(exc).__name__})", steps, model_name, usage)
        for k in usage:
            usage[k] += used.get(k) or 0
        messages.append({k: v for k, v in message.items() if k in ("role", "content", "tool_calls")})
        calls = message.get("tool_calls") or []
        if not calls:
            if nudged:
                return _result(None, journal, "l'agent s'est arrêté sans publier de plan", steps, model_name, usage)
            nudged = True
            messages.append({"role": "user", "content": "Termine en appelant publier_plan."})
            continue
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except ValueError:
                args = None
            if args is None:
                result = {"erreur": "arguments JSON illisibles"}
            elif name == "publier_plan" and tools.unproven():
                # la preuve est le cœur de l'audit : elle ne dépend pas du bon vouloir du modèle
                result = {"erreur": "plan refusé : ces constats se prouvent par rejeu et ne l'ont pas été "
                                    f"{tools.unproven()}. Appelle prouver sur chacun, puis republie."}
            elif name == "publier_plan":
                missing = unknown_numbers(args, outputs)
                mislabeled = [] if missing else mislabeled_numbers(args, outputs)
                cache = None if missing or mislabeled else unjustified_cache_recommendation(args, tools)
                if missing:
                    result = {"erreur": "plan refusé : ces chiffres ne viennent d'aucun outil "
                                        f"{missing}. Corrige-les ou retire-les, puis republie."}
                elif mislabeled:
                    result = {"erreur": "plan refusé : chiffres rattachés à la mauvaise grandeur "
                                        + "; ".join(f"« {lab} {val:g} % » ne correspond à aucun champ {fld}"
                                                    for lab, val, fld in mislabeled)
                                        + ". Cite chaque chiffre avec le nom de son champ, puis republie."}
                elif cache:
                    result = {"erreur": cache}
                else:
                    for action in args.get("actions", []):
                        action["statut"] = tools.proof_status(action.get("finding_id"))
                    journal.append(_entry(message, name, args, {"statut": "plan publié"}))
                    return _result(args, journal, "terminé", steps, model_name, usage, tools)
            else:
                result = tools.call(name, args)
                outputs.append(result)
            journal.append(_entry(message, name, args, result))
            content = json.dumps(result, ensure_ascii=False)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": content[:MAX_RESULT_CHARS]})
    return _result(None, journal, f"budget de {max_steps} étapes épuisé", steps, model_name, usage)


def _entry(message, name, args, result):
    why = (args or {}).get("pourquoi") if isinstance(args, dict) else None
    return {"pensee": why or (message.get("content") or "").strip() or None, "outil": name,
            "arguments": {k: v for k, v in (args or {}).items() if k != "pourquoi"}, "resultat": result}


def _result(plan, journal, statut, steps, model_name, usage, tools=None):
    # preuves faites par l'agent, pour que la carte du constat les affiche (problème 16)
    proofs = {fid: {"verdict": p["verdict"], "accord_pct": round(p["agreement_rate"] * 100, 1),
                    "methode": (tools.methods or {}).get(fid)}
              for fid, p in (tools.proofs if tools else {}).items()}
    return {"plan": plan, "journal": journal, "statut": statut, "appels_modele": steps,
            "modele": model_name, "jetons": usage, "cout_audit_usd": _agent_cost(model_name, usage),
            "preuves": proofs}
