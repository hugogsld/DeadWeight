# Analyser n'importe quel workflow d'agents

Chaque client a sa stack : du code avec un SDK, n8n, Make, Claude Code et Codex (Miguel), LangChain, un
framework maison. On ne refait jamais l'analyse pour chacun. **Un seul cœur d'analyse, des connecteurs
d'entrée** : le connecteur traduit les traces du client en événements au format commun, et tout le reste
(vérifications, chiffrage, rejeu, banc de modèles, agent auditeur, rapport) est le même pour tous.

```
 passerelle (base_url) ─┐
 OpenTelemetry ─────────┤
 Claude Code / Codex ───┤──►  événements au schéma commun  ──►  cœur : 14 vérifications, chiffrage,
 historique n8n ────────┤     (schemas/event.schema.json)        rejeu, banc, agent auditeur, rapport
 exports d'usage ───────┤
 fichier de coûts ──────┘   (coûts hors IA : GPU, voix, API)
```

Un connecteur, c'est quelques heures. Le cœur, c'est ce qu'on améliore pour tout le monde.

## Trois niveaux de données

Tous les connecteurs ne donnent pas la même chose. Plutôt que d'exiger tout, on travaille avec ce qu'on
a, et le rapport dit ce qui n'a pas pu être vérifié faute de données.

| Niveau | Ce qu'on a | Ce que ça permet | Exemples de sources |
|---|---|---|---|
| **1. Usage** | modèle, fournisseur, jetons (entrée, sortie, cache, raisonnement), heure, durée, statut, **un identifiant d'application ou d'étape** | coût et latence par étape ; modèle trop gros (R2, partiel) ; raisonnement excessif (R7) ; erreurs payées (R9) ; sorties trop longues (R12) ; API batch (R14) ; cache non utilisé (R4, partiel) ; souveraineté (levier 16) | exports d'usage OpenAI / Anthropic ; OpenTelemetry par défaut ; tableau de coûts |
| **2. Contenu** | + messages, réponse, instructions système, outils déclarés, nombre d'images | LLM qui aiguille (R1) ; contexte brut (R3) ; cache (R4 complet) ; appels identiques (R8) ; outils déclarés (R13) ; images (R15) ; **toutes les preuves** : rejeu, banc de modèles, miroir, court-circuit ; agent auditeur complet | passerelle ; OpenTelemetry avec capture du contenu ; journaux Claude Code et Codex ; historique n8n |
| **3. Structure** | + identifiant d'exécution (trace), enchaînement des appels, appels d'outils, étapes du workflow, recherches documentaires | boucles (R5) ; agent ou chaîne (R6) ; relecture par un LLM (R16) ; étapes parallélisables (R10) ; boucle sur les éléments (R11) ; forme du RAG | passerelle (traces déduites) ; OpenTelemetry (spans) ; journaux Claude Code et Codex ; historique n8n |

**Le minimum pour faire tourner notre process : le niveau 1 plus un identifiant d'application ou d'étape.**
Sans contenu, on chiffre et on repère des pistes ; on ne prouve rien. Pour prouver, il faut le niveau 2 sur
au moins un échantillon.

Les coûts hors IA (GPU, voix, API d'outils) arrivent par un simple fichier de coûts : une ligne par dépense,
avec l'étape, le service, le montant. Le `costs.jsonl` de Miguel en est un bon modèle.

## Les connecteurs

| Connecteur | Niveau atteint | Pour qui | État |
|---|---|---|---|
| **Passerelle** (`base_url`) | 3, en direct | toute application codée | fait |
| **OpenTelemetry** (conventions GenAI) | 1 par défaut, 2 si le client active la capture du contenu, 3 par les spans | LangChain, SDK d'agents OpenAI, Vercel AI, LiteLLM, Langfuse… un seul connecteur pour des dizaines de frameworks | fait : import de fichier ; réception en direct (`/v1/traces`) en **JSON seulement**, ce que l'exportateur Python n'envoie pas (voir ci-dessous) |
| **Journaux Claude Code et Codex** | 3 | équipes qui automatisent avec ces outils | fait (`connectors.agent_logs`) |
| **Historique n8n** | 2 à 3 selon les nœuds | workflows no-code | fait (`importers.n8n`) |
| **Exports d'usage des fournisseurs** | 1 | tout le monde : premier diagnostic sans rien installer | après le weekend |
| **Fichier de coûts** | coûts hors IA | GPU, voix, API d'outils | après le weekend |

### Ce qui a été vérifié pour de vrai (27/09)

Chaque ligne : une vraie application, lancée sur un Mac, son trafic passé par Deadweight, puis le rapport.
Détails, chiffres et problèmes : `docs/retours-tests-workflows.md`, fiche « Sources de workflows ».

| Source | Voie | Résultat |
|---|---|---|
| Script Python, SDK `openai` | passerelle | ✅ récap Gmail, 88 appels réels, streaming compris |
| SDK Agents d'OpenAI, en `chat_completions` | passerelle | ✅ story flow, 77 appels réels |
| SDK Agents d'OpenAI, réglage par défaut (API Responses) | passerelle | ❌ relayé, **0 événement capturé** (problème 11) |
| LangChain (`langchain-openai` 1.6, `ChatOpenAI(base_url=…)`) | passerelle | ✅ appels simples et streaming, `app_id` par en-tête |
| **n8n 2.40**, nœud OpenAI Chat Model, champ *Base URL* de l'identifiant | passerelle | ✅ 42/42 appels, `app_id` posé par l'en-tête personnalisé de l'identifiant n8n |
| **n8n 2.40**, même workflow | import de l'historique | ✅ 42/42 exécutions, 100 % des appels LLM compris, jetons réels, une trace par exécution |
| **Claude Code**, journaux de session d'un vrai projet | `connectors.agent_logs` | ✅ 300 appels lus, 0 ignoré, niveaux 1 à 3 |
| Application Python instrumentée OpenTelemetry, exportateur OTLP/HTTP officiel | réception en direct | ❌ **415** : l'exportateur Python envoie du protobuf, même avec `OTEL_EXPORTER_OTLP_PROTOCOL=http/json` (problème 18) |

Non vérifié faute d'outil ou de compte : Claude Code et Codex **en direct** par la passerelle
(`ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`), Codex en journaux, Ollama et modèles locaux, Make, Zapier,
Azure OpenAI, Bedrock, Vertex.

OpenTelemetry, à savoir : les conventions GenAI sont encore au statut « Development ». Les attributs utiles
sont `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`,
`gen_ai.usage.reasoning.output_tokens`, `gen_ai.response.finish_reasons`, `gen_ai.conversation.id`. Le
contenu (`gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`,
`gen_ai.tool.definitions`) est **en option chez le client** : par défaut on reçoit le niveau 1. Les spans
d'outils (`execute_tool`), d'agents et de recherche documentaire donnent le niveau 3.
Source : github.com/open-telemetry/semantic-conventions-genai.

### Le contrat d'un connecteur

1. `lire(source) -> événements` au schéma commun, et **un rapport de compréhension** : combien d'appels lus,
   combien ignorés et pourquoi, **quel niveau atteint**.
2. Aucune clé lue ni stockée ; le contenu n'est gardé que s'il sert (niveau 2) ; données client dans
   `private/`, jamais sur GitHub.
3. Un test sur un extrait réel anonymisé.
4. Rien d'autre à changer : si le cœur a besoin d'une adaptation pour un connecteur, c'est le schéma commun
   qui manque quelque chose, et on le discute.

## Pour chaque nouveau workflow

### 1. Cinq questions de tri (5 minutes, avant de toucher à quoi que ce soit)

1. **Où sont les appels d'IA ?** Dans du code, dans un outil no-code, dans un agent de code (Claude Code,
   Codex), chez un prestataire ?
2. **Avec quel outil ?** C'est lui qui désigne le connecteur.
3. **Existe-t-il un historique ?** Journaux, exécutions enregistrées, traces, exports d'usage. Sinon : la
   passerelle, et on laisse tourner.
4. **Coût au jeton ou abonnement ?** À l'abonnement, l'économie se dit en limites atteintes plus tard, pas en
   dollars.
5. **Les données sont-elles sensibles ?** Si oui : anonymisation, stockage local, suppression après, et un
   engagement écrit.

### 2. Ce qu'on demande au client : le plus simple possible

| Sa situation | Notre demande, en une phrase |
|---|---|
| Application codée | « Changez `base_url` vers la passerelle et laissez tourner une journée. » |
| Déjà instrumenté en OpenTelemetry | « Ajoutez notre adresse comme destination de vos traces. » (activer la capture du contenu pour les preuves) |
| n8n | « Exportez l'historique des exécutions : une commande, votre clé n8n reste chez vous. » |
| Claude Code, Codex | « Zippez les journaux de session d'un run : une commande. » |
| Rien de tout ça | « Exportez l'usage de votre compte OpenAI ou Anthropic. » (niveau 1 : premier diagnostic) |

Jamais ses clés d'API. Jamais plus qu'une commande ou un réglage.

### 3. La carte du workflow

Les étapes, les appels d'IA et les autres coûts par étape, sur une page. On écrit **nos hypothèses** (ce
qu'un expert changerait) **avant** de lancer l'audit : c'est la référence pour juger le système.

### 4. Les données

Via le connecteur. On note le **taux de compréhension** et le **niveau atteint**.

### 5. L'audit

Le même pour tous : vérifications, chiffrage, preuves quand le niveau 2 le permet, agent auditeur, rapport.

### 6. La revue et la fiche client

Chaque constat : vrai ou faux positif. Comparaison avec les hypothèses de l'étape 3. **Ce qu'on a manqué
devient une nouvelle règle ; ce qu'on n'a pas su lire devient un nouveau connecteur ou un champ du schéma.**
C'est comme ça que le cœur s'améliore pour tous les clients à chaque workflow analysé.
