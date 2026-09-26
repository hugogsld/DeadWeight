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
3. Pour chaque constat prouvable par rejeu, appelle prouver. Si le verdict est « reject », lis les
   raisons : dis honnêtement que le remplacement n'est pas prouvé, et propose d'observer plus
   longtemps (mode miroir) plutôt que de l'appliquer.
4. Termine par publier_plan : cinq actions au plus, la plus rentable d'abord.

Règles absolues :
- Tu ne calcules rien. Chaque chiffre que tu écris doit apparaître tel quel dans un résultat d'outil.
- Tu écris en français clair, pour un dirigeant, sans jargon technique.
- Un constat non prouvé est présenté comme une piste, jamais comme une certitude."""

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_THOUSANDS = re.compile(r"(?<![\w.,])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?!\d)")  # « 315 220 », pas « p95 764 »


class OpenAIChatTools:
    """Client /chat/completions avec appel d'outils ; base_url inclut /v1."""

    def __init__(self, base_url, api_key, model):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model

    def chat(self, messages, tools):
        body = {"model": self.model, "messages": messages,
                "tools": [{"type": "function", "function": t} for t in tools]}
        request = urllib.request.Request(
            self.base_url + "/chat/completions", method="POST",
            data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
        return payload["choices"][0]["message"], payload.get("usage") or {}


def _numbers(text):
    return [float(n.replace(",", ".")) for n in _NUMBER.findall(_THOUSANDS.sub(lambda m: re.sub(r"\D", "", m.group()), str(text)))]


def _known(value, seen):
    """Le chiffre écrit correspond-il à un chiffre rendu par un outil, au plus à son arrondi près ?"""
    if value in FREE_INTEGERS:
        return True
    for x in seen:
        for digits in (0, 1, 2):
            if round(x, digits) == value:
                return True
    return False


def unknown_numbers(plan, tool_outputs):
    """Chiffres du plan introuvables dans les résultats d'outils."""
    seen = {n for out in tool_outputs for n in _numbers(json.dumps(out, ensure_ascii=False))}
    texts = [plan.get("resume", "")] + [a.get(k, "") for a in plan.get("actions", []) for k in ("action", "justification")]
    return sorted({n for t in texts for n in _numbers(t) if not _known(n, seen)})


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
            elif name == "publier_plan":
                missing = unknown_numbers(args, outputs)
                if not missing:
                    journal.append(_entry(message, name, args, {"statut": "plan publié"}))
                    return _result(args, journal, "terminé", steps, model_name, usage)
                result = {"erreur": "plan refusé : ces chiffres ne viennent d'aucun outil "
                                    f"{missing}. Corrige-les ou retire-les, puis republie."}
            else:
                result = tools.call(name, args)
                outputs.append(result)
            journal.append(_entry(message, name, args, result))
            content = json.dumps(result, ensure_ascii=False)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": content[:MAX_RESULT_CHARS]})
    return _result(None, journal, f"budget de {max_steps} étapes épuisé", steps, model_name, usage)


def _entry(message, name, args, result):
    return {"pensee": (message.get("content") or "").strip() or None, "outil": name, "arguments": args,
            "resultat": result}


def _result(plan, journal, statut, steps, model_name, usage):
    return {"plan": plan, "journal": journal, "statut": statut, "appels_modele": steps,
            "modele": model_name, "jetons": usage, "cout_audit_usd": _agent_cost(model_name, usage)}
