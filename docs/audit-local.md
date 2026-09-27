# Audit 100 % local (Ollama)

L'agent auditeur peut tourner sur un modèle installé sur la machine du client : aucune clé, aucun
fournisseur, aucune donnée qui sort. C'est la réponse directe à la question RGPD / souveraineté
(voir [positionnement.md](positionnement.md), point 1).

```sh
ollama serve &              # une fois
ollama pull qwen2.5:3b      # une fois, ~2 Go : le seul moment où la machine télécharge
make audit-local            # AUDIT_EVENTS=chemin/events.jsonl pour un autre trafic
```

Sortie : `out/audit-local.html` (rapport), `out/audit-local.json` (journal de l'agent),
`out/audit-local-reseau.json` (relevé réseau).

## Deux garde-fous dans le code (`agent/local.py`)

1. **Adresse du modèle** : en mode local (`--local` ou `DW_AUDIT_LOCAL=1`), une adresse de modèle
   qui n'est pas `localhost`, `127.x.x.x` ou `::1` est refusée avant le moindre appel. La clé du
   client (`DW_LLM_API_KEY`) n'est pas lue.
2. **Tout le processus** : un crochet d'audit Python (`sys.addaudithook`) refuse toute résolution DNS
   et toute connexion vers un hôte non local, quel que soit le module qui l'ouvre. Il ne se retire pas.

Testé sans Ollama (`tests/test_audit_local.py`) : dans un processus gardé, une résolution de
`api.openai.com`, une connexion à `1.1.1.1:443` et un appel HTTPS à OpenAI sont refusés, une connexion
à `127.0.0.1` passe.

Délai par appel au modèle : `DW_LOCAL_TIMEOUT` (secondes, défaut 600), à relever sur une machine lente.

## Mesure réseau : outillée, pas encore faite

`make audit-local` relève avec `lsof` (toutes les 0,5 s) les connexions réseau du processus d'audit
**et** du serveur Ollama pendant tout le run, écrit `out/audit-local-reseau.json` et échoue si une
seule connexion vise un hôte non local.

État au 27/09 : **aucun run complet mesuré**. Ce qui est vérifié, c'est le garde-fou, par les tests
ci-dessus. Le relevé `lsof` réel reste à faire, sur une machine peu chargée, avant de le citer au pitch.

Constaté sur un Mac saturé par d'autres travaux (charge ~40-50) :
- qwen2.5:7b : ~0,07 jeton/s, 4 appels en 45 min, audit arrêté sur délai dépassé ;
- qwen2.5:3b : ~10 jetons/s, deux appels réussis (10 s et 15 s) avec appels d'outils corrects, puis une
  erreur 500 d'Ollama après 78 s ; run interrompu volontairement pour soulager la machine.

Limite honnête : un relevé toutes les 0,5 s peut manquer une connexion très brève ; c'est le crochet
d'audit, lui, qui garantit qu'aucune ne peut s'ouvrir depuis l'audit. Le relevé ne couvre pas les
autres logiciels de la machine.
