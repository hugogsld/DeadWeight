# Vérification des voies de connexion (27/09)

Chaque voie annoncée dans le README a été suivie **à la lettre** sur un clone neuf du repo
(`git clone` depuis GitHub, `main` @ `347973d`, nouvel environnement Python), avec de vraies
applications. Temps mesurés, messages d'erreur relevés tels quels.

Machine : macOS, Python 3.13.5, Node 26, n8n 2.40.7. « Machine propre » au sens d'un clone et d'un
environnement neufs : les caches `pip` et `npx` de la machine étaient chauds, les temps
d'installation d'une vraie machine vierge seront plus longs (premier `npx n8n` mesuré la veille :
environ 12 minutes).

## Résultat

| Voie | Commande suivie | Résultat | Temps |
| --- | --- | --- | --- |
| Démo sans clé | `make install` puis `make demo` | ✅ 36 appels fictifs, rapport écrit | 11 s + 2 s |
| **Passerelle** : application Python (SDK `openai`) | `make dev`, `base_url` changé | ✅ appel simple et streaming, vrais appels OpenAI, jetons du streaming captés | passerelle prête en 1 s |
| **Passerelle** : application Node.js (SDK `openai`) | exemple JavaScript du README | ✅ appel simple et streaming | 2 s |
| **Passerelle** : SDK Anthropic (`/anthropic`) | `Anthropic(base_url=…/anthropic)` | ✅ relais et capture ; testé avec une clé invalide : le 401 d'Anthropic est relayé, la clé n'apparaît pas dans l'événement | 2 s |
| **Passerelle** : rapport | `make audit` | ✅ `out/audit.html` | < 1 s |
| **OpenTelemetry**, fichier | `python -m connectors.otel traces.json` | ✅ vrais appels `gpt-4o-mini` instrumentés : 3 appels sur 4 spans, niveaux 1 à 3, le span parent ignoré à raison | 1 s |
| **OpenTelemetry**, en direct depuis Node.js | exportateur `@opentelemetry/exporter-trace-otlp-http` → `/v1/traces` | ✅ 2 spans reçus, 2 événements | — |
| **OpenTelemetry**, en direct depuis Python | exportateur officiel `opentelemetry-exporter-otlp-proto-http` 1.45 → `/v1/traces` | ❌ `Failed to export spans batch code: 415, reason: Unsupported Media Type`, même avec `OTEL_EXPORTER_OTLP_PROTOCOL=http/json`. 0 événement. **Corrigé par #118** : 9/9 appels captés, vérifié avec la même application | — |
| **Claude Code**, dossier | `python3 -m connectors.agent_logs ~/.claude/projects` | ✅ 7 fichiers, 5 sessions, 2 651 appels lus, 4 ignorés (messages fabriqués par Claude Code) | 4 s |
| **Claude Code**, zip d'un projet | `python3 -m connectors.agent_logs run.zip` | ✅ 344 appels lus, 0 ignoré | 1 s |
| **Codex** | `python3 -m connectors.agent_logs …` | non testé : aucun journal Codex sur la machine | — |
| **n8n** | `importers.n8n check`, `fetch`, `convert`, puis `report.audit` | ✅ instance vierge, workflow webhook → Basic LLM Chain → OpenAI Chat Model, 35 exécutions : 35/35 lues, 100 % comprises, jetons réels | < 1 s par étape ; n8n prêt en 11 s |
| **n8n par la passerelle** | identifiant OpenAI de n8n, champ *Base URL* et en-tête `x-deadweight-app` | ✅ vérifié le 27/09 matin : 42/42 appels (voir `retours-tests-workflows.md`) | — |
| **Make** | — | n'existe pas : ne pas l'annoncer | — |

Pour n8n, l'amont était le faux OpenAI du projet : aucune vraie clé saisie dans n8n. Le test vaut
pour la connexion et l'import, pas pour la qualité des réponses.

## Messages d'erreur relevés

| Situation | Message obtenu | Jugement |
| --- | --- | --- |
| `make dev`, port 8080 déjà pris | trace Python complète, se terminant par `OSError: [Errno 48] error while attempting to bind on address ('127.0.0.1', 8080): [errno 48] address already in use` puis `make: *** [dev] Error 1` | à améliorer : la solution est dans le README (« Si ça ne marche pas »), le message devrait y renvoyer en une ligne |
| n8n, clé refusée | `erreur : clé API refusée par l'instance (401)` | clair |
| n8n, mauvaise adresse | `erreur : instance injoignable (http://127.0.0.1:5999/api/v1) : [Errno 61] Connection refused` | clair |
| n8n, pas de clé | `erreur : clé API manquante : variable d'environnement N8N_API_KEY` | clair |
| n8n, workflow inconnu | `erreur : introuvable (404) : /workflows/inexistant` | clair |
| `agent_logs`, chemin inexistant | `erreur : [Errno 2] No such file or directory: '…/nexistepas.zip'` | correct |
| `agent_logs`, fichier qui n'est pas un journal | `erreur : aucun journal Claude Code ou Codex reconnu dans ces sources` | clair |
| `connectors.otel`, fichier inexistant | `Lecture impossible de nexistepas.json : FileNotFoundError` | correct |
| `connectors.otel`, fichier texte | `Lecture impossible de README.md : JSONDecodeError` | correct |
| `connectors.otel`, JSON qui n'est pas de l'OTLP | `0 appel(s) lus sur 0 span(s), niveaux []`, code de sortie 0 | à améliorer : aucun avertissement, l'utilisateur croit que son trafic est vide |
| `/v1/traces`, corps illisible | `{"message": "export OTLP/JSON illisible"}` | clair |
| `make audit`, base absente | `Base absente : out/vide.db. Lancez make dev, réglez le base_url … puis relancez make audit.` | clair |

## Ce qui reste à corriger

1. ~~**OpenTelemetry en direct depuis Python**~~ (problème 18) : corrigé par #118, `/v1/traces` lit
   aussi le protobuf.
2. **SDK Agents d'OpenAI, API Responses** (problème 11) : non capturée. Le README dit bien que seule
   `/v1/chat/completions` est capturée, mais le tableau des voies range le SDK d'agents OpenAI sous
   OpenTelemetry sans le préciser.
3. **Port occupé** : attraper l'erreur dans `gateway/proxy.py` et afficher « Port 8080 déjà utilisé :
   réglez GATEWAY_PORT dans .env.local » au lieu de la trace.
4. **OTLP vide** : avertir quand un fichier ne contient aucun `resourceSpans`.
5. **`agent_logs ~/.claude/projects`** lit **tous** les projets Claude Code de la machine (ici 6, dont
   des projets personnels sans rapport). Conseiller de pointer un seul dossier de projet, ou un zip,
   comme le fait le README.

## Non vérifié

Codex (journaux et direct), Claude Code et Codex en direct par la passerelle (`ANTHROPIC_BASE_URL`,
`OPENAI_BASE_URL` : CLI absentes de la machine), Ollama et modèles locaux, Azure OpenAI, Bedrock,
Vertex, collecteur OpenTelemetry. Make et Zapier n'ont pas de voie.
