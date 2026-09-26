"""Trafic client réaliste vers la passerelle : SDK OpenAI (simple, streaming, outils, boucle), Anthropic, Gemini."""
import json
import sys
import urllib.request

import openai

GW, KEY = sys.argv[1], "sk-e2e-NE-DOIT-JAMAIS-SORTIR"
SYSTEM = "Classe le mail en une seule etiquette : spam, facture ou support."
MAILS = ["Gagnez un iPhone maintenant", "Votre facture de septembre", "Mon compte est bloque",
         "Offre exclusive pour vous", "Facture impayee numero 42", "Je n'arrive pas a me connecter"]
mode = sys.argv[2] if len(sys.argv) > 2 else "full"
client = openai.OpenAI(base_url=GW + "/v1", api_key=KEY, max_retries=0)
counts = {"openai": 0, "stream": 0, "tools": 0, "anthropic": 0, "gemini": 0, "shortcircuit": 0}

for i in range(40):
    raw = client.chat.completions.with_raw_response.create(
        model="gpt-4o", extra_headers={"x-deadweight-app": "mail-triage"},
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"{MAILS[i % 6]} ({i})"}])
    raw.parse()
    counts["openai"] += 1
    counts["shortcircuit"] += bool(raw.headers.get("x-deadweight-shortcircuit"))
if mode == "full":
    for i in range(10):
        text = "".join(c.choices[0].delta.content or "" for c in client.chat.completions.create(
            model="gpt-4o-mini", stream=True, extra_headers={"x-deadweight-app": "chat"},
            messages=[{"role": "user", "content": f"Bonjour {i}"}]) if c.choices)
        assert text, "stream vide"
        counts["stream"] += 1
    # boucle d'agent : 8 appels qui renvoient l'historique, sans en-tête de trace
    history = [{"role": "system", "content": "Tu es un agent de recherche."},
               {"role": "user", "content": "Trouve le tarif entreprise"}]
    for step in range(8):
        r = client.chat.completions.create(model="gpt-4o", messages=history,
                                           extra_headers={"x-deadweight-app": "agent"})
        history += [{"role": "assistant", "content": r.choices[0].message.content},
                    {"role": "user", "content": f"Continue, étape {step}"}]
        counts["tools"] += 1
    for i in range(5):
        req = urllib.request.Request(GW + "/anthropic/v1/messages", method="POST",
                                     data=json.dumps({"model": "claude-sonnet-4-5", "max_tokens": 32,
                                                      "messages": [{"role": "user", "content": f"Salut {i}"}]}).encode(),
                                     headers={"x-api-key": KEY, "anthropic-version": "2023-06-01",
                                              "content-type": "application/json", "x-deadweight-app": "support"})
        json.load(urllib.request.urlopen(req))
        counts["anthropic"] += 1
        req = urllib.request.Request(GW + f"/gemini/v1beta/models/gemini-2.5-flash:generateContent?key={KEY}",
                                     method="POST", headers={"content-type": "application/json",
                                                             "x-deadweight-app": "support"},
                                     data=json.dumps({"contents": [{"role": "user", "parts": [{"text": f"Salut {i}"}]}]}).encode())
        json.load(urllib.request.urlopen(req))
        counts["gemini"] += 1
print(json.dumps(counts))
