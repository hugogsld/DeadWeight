# Recherche — Patterns de workflows agentiques, quand les choisir, et ce que disent les études récentes

> **Piste secondaire, pour plus tard** (décision du 26/09) : recommander la manière optimale de construire un workflow selon son type et son usage. Pas une priorité du weekend : on se concentre sur les micro-modifications prouvées. Les chiffres viennent d'études citées ; le papier « The Harness Effect » est sponsorisé par Writer (conflit d'intérêt), et les chiffres de surcoût multi-agent viennent d'études ponctuelles.


Contexte : alimente la réflexion long terme de Deadweight ("quelle est la manière optimale de construire tel workflow pour tel usage", pas seulement du micro-fix). Sources croisées : guides fournisseurs (Anthropic, OpenAI, Google), papiers académiques 2024-2026, un papier industriel (Writer) à traiter avec prudence.

---

## 1. Taxonomie des patterns de workflows agentiques

### A. Les 5 patterns "workflow" d'Anthropic (déterministes, code contrôle le flux)
Source : Anthropic, *Building Effective Agents*, déc. 2024 — https://www.anthropic.com/research/building-effective-agents

| Pattern | Description | Quand l'utiliser | Coût/latence/qualité | Signal observable en trace |
|---|---|---|---|---|
| **Prompt chaining** | Décompose une tâche en étapes séquentielles, chaque appel LLM traite la sortie du précédent, avec checks programmatiques intermédiaires possibles | Tâche décomposable en sous-étapes fixes et fiables (ex: générer plan → écrire → traduire) | Coût = somme des N appels ; latence cumulative (séquentiel) ; qualité généralement meilleure qu'un seul gros prompt car chaque étape est plus simple | N appels LLM successifs sur la même session/thread, chaque prompt contient la sortie brute du précédent (souvent verbeuse, non filtrée) |
| **Routing** | Un classifieur dirige l'input vers un traitement spécialisé | Catégories d'input bien définies et distinctes, nécessitant des prompts/modèles différents | Coût de l'étape de routage souvent négligeable si bien dimensionné, mais gaspillage fréquent : LLM cher utilisé juste pour classifier | Un premier appel LLM très court en sortie (juste une étiquette/catégorie) suivi d'un appel différent — c'est LE signal typique de gaspillage détectable par Deadweight (modèle sur-dimensionné pour classifier) |
| **Parallelization** | Appels indépendants en parallèle (sectioning) ou répétition du même appel pour vote/consensus | Sous-tâches indépendantes ou besoin de diversité/vote pour fiabilité | Coût = N appels mais latence = max(N) au lieu de somme ; bon ratio qualité/latence si sous-tâches vraiment indépendantes | Plusieurs appels avec timestamps quasi-identiques (même fenêtre), pas de dépendance de données entre eux |
| **Orchestrator-workers** | Un LLM central décompose la tâche à l'exécution et distribue des sous-tâches dynamiques à des workers, puis synthétise | Sous-tâches non prévisibles à l'avance (dépend de l'input) | Plus flexible que parallelization mais plus cher (appel orchestrateur + N workers + synthèse) ; risque de sur-ingénierie si les sous-tâches sont en fait toujours les mêmes (auquel cas → prompt chaining suffit) | Appel "planificateur" en tête de trace dont la sortie structure les appels suivants (nombre variable selon les runs) |
| **Evaluator-optimizer** | Un générateur + un critique séparé qui boucle jusqu'à seuil de qualité | Critères d'évaluation clairs et articulables, et itérer apporte une valeur mesurable | Coût imprévisible (dépend du nombre de boucles) — risque de boucles longues/coûteuses si le critère de sortie est mal calibré | Paires générateur/évaluateur répétées, avec un compteur d'itérations visible ; loops sans borne max = signal d'alerte |

Ces patterns sont **composables** : routing peut alimenter un chaining ; orchestrator-workers peut envelopper un evaluator-optimizer au niveau des workers.

### B. Single-agent vs multi-agent (boucle autonome)
Source : OpenAI, *A Practical Guide to Building Agents*, 2025 — https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf

- **Single-agent loop** : un seul modèle avec outils + instructions exécute en boucle (le modèle décide lui-même des prochains appels, pas de code figé). Recommandé par défaut : ajouter des outils incrémentalement plutôt que de passer trop tôt au multi-agent.
- **Multi-agent (manager pattern)** : un agent manager fait des tool-calls vers des agents spécialisés (edges = appels d'outils).
- **Multi-agent (décentralisé/handoff)** : les agents se passent l'exécution (edges = handoffs), topologie de graphe.
- Recommandation OpenAI : complexifier seulement quand un seul agent devient difficile à évaluer/maintenir — pas par défaut.

Signal en trace : boucle autonome = nombre d'appels LLM non prévisible à l'avance, avec des tool-calls interlacés et pas de structure de code fixe entre les appels (contrairement au chaining où le nombre d'étapes est fixe dans le code).

### C. Patterns Google ADK (proches d'Anthropic, orientés implémentation)
Source : Google, ADK docs / *Developer's guide to multi-agent patterns in ADK* — https://developers.googleblog.com/developers-guide-to-multi-agent-patterns-in-adk/

Sequential (assembly line, déterministe), Parallel (fan-out/fan-in), Loop (raffinement itératif), Coordinator/dispatcher, Hiérarchique. Conceptuellement recouvre les mêmes patterns qu'Anthropic mais formalisés comme primitives de framework — utile si Deadweight veut mapper une trace n8n/LangChain vers un pattern nommé.

### D. Taxonomie académique récente (référence si Deadweight veut un cadre plus formel)
- *The Hitchhiker's Guide to Agentic AI: From Foundations to Systems*, Haggai Roitman, arXiv:2606.24937 (juin 2026) — https://arxiv.org/abs/2606.24937 — reprend et étend la taxonomie Anthropic + ajoute topologies multi-agents (centralisée/décentralisée/hiérarchique), MCP, A2A. Bon point d'entrée bibliographique unique.
- *A Two-Dimensional Framework for AI Agent Design Patterns: Cognitive Function × Execution Topology*, arXiv:2605.13850 — classe les patterns selon deux axes (fonction cognitive vs topologie d'exécution) ; potentiellement utile comme grille de classification automatique pour Deadweight, mais non vérifié en détail (juste le titre/abstract croisé, pas lu en profondeur).

---

## 2. Guide de décision — type de workflow × usage → manière optimale de construire

| Critère d'usage | Signal typique | Construction recommandée | Pourquoi / source |
|---|---|---|---|
| **Temps réel** (utilisateur attend une réponse) | Latence perçue critique | Appels synchrones, éviter les boucles evaluator-optimizer non bornées ; parallelization pour réduire la latence si sous-tâches indépendantes | Anthropic (patterns), latence = max(N) en parallel vs somme en chaining |
| **Batch / non urgent** (rapports, scoring en masse, enrichissement) | Réponse acceptable sous 24h | **Batch API** (OpenAI, Anthropic) : -50% sur le prix input/output, limite de rate séparée plus généreuse | OpenAI Batch API docs ; Anthropic Message Batches API — 50% de réduction sur tous les modèles actifs, cumulable avec le prompt caching |
| **Volume élevé, tâche répétitive et peu variable** (classification, extraction, résumé standardisé) | Faible variance d'input, peu de "raisonnement général" requis | **Petit modèle spécialisé** (SLM) plutôt que LLM généraliste, éventuellement fine-tuné | NVIDIA, *Small Language Models are the Future of Agentic AI*, arXiv:2506.02153 — SLM "10 à 30x moins chers" à exécuter, latence plus faible, fine-tuning possible "en une nuit" |
| **Volume élevé, variabilité forte des inputs** (mélange de requêtes faciles/difficiles) | Distribution bimodale de difficulté | **Cascade** (essayer le modèle le moins cher d'abord, escalader si score de confiance insuffisant) ou **routing appris** | FrugalGPT, arXiv:2305.05176 — jusqu'à 98% de réduction de coût à qualité égale ou +4% de qualité à coût égal (sur HEADLINES) ; RouteLLM, arXiv:2406.18665 — routeur appris sur préférences humaines : -85% de coût sur MT-Bench, -45% sur MMLU, -35% sur GSM8K pour 95% de la performance GPT-4 |
| **Tâche nécessitant conversation générale / capacités larges** | Instructions ouvertes, contexte conversationnel riche | Modèle généraliste (LLM) reste justifié — système hétérogène (SLM pour tâches répétitives + LLM pour le reste) | NVIDIA arXiv:2506.02153 : "quand les capacités conversationnelles générales sont essentielles, les systèmes hétérogènes (plusieurs modèles) sont le choix naturel" |
| **Tâches fixes, prévisibles à l'écriture du code** | Le nombre d'étapes et leur ordre ne dépendent pas de l'input | **Chaîne fixe (prompt chaining) ou pipeline séquentiel** — pas besoin d'un agent autonome | Anthropic : préférer le pattern le plus simple qui suffit ; overhead de boucle autonome non justifié si le flux est déterministe |
| **Tâches où la décomposition dépend de l'input, imprévisible à l'avance** | Sous-tâches variables selon le cas | **Orchestrator-workers** ou **boucle agent autonome avec outils** | Anthropic + OpenAI guide — mais vérifier d'abord qu'un simple routing ne suffit pas (moins cher) |
| **Confidentialité / souveraineté forte** | Données sensibles, contraintes réglementaires | Modèle local/petit ou classifieur à base de règles plutôt qu'API cloud, si le cas d'usage le permet | Cohérent avec la note mémoire Deadweight sur le positionnement RGPD/souveraineté (Anthropic sans résidence UE en API directe) — voir `docs/research/positionnement.md` |
| **Contexte long réutilisé (relecture répétée d'un même gros document/historique)** | Beaucoup de tokens input répétés d'un appel à l'autre | Réduire la longueur effective (résumé/compaction, prompt caching) plutôt que renvoyer tout le contexte brut à chaque appel | *Context Length Alone Hurts LLM Performance Despite Perfect Retrieval*, ACL Findings EMNLP 2025 — dégradation de performance de 13,9% à 85% avec l'augmentation de la longueur d'input, **même quand la récupération est parfaite** et même quand les tokens non pertinents sont masqués ; mitigation proposée : faire réciter par le modèle les extraits pertinents avant de résoudre |
| **Orchestration lourde vs légère (harnais)** | Traces longues, replays de contexte, nombreux tool-calls | Réduire la conception du harnais lui-même (moins de tours, contexte assemblé plus efficacement) avant de changer de modèle | *The Harness Effect*, arXiv:2607.06906 (papier sponsorisé par Writer — **à traiter comme source industrielle, pas indépendante**) — sur des tâches contrôlées, un changement de harnais seul (modèle identique) réduit le coût de 41%, le temps de 44%, les tokens de 38%, à qualité de tâche égale |
| **Multi-agent "pour faire mieux"** | Ajout d'agents spécialisés sans borne | Vérifier le ROI qualité/coût avant d'ajouter des agents : la coordination a un coût qui croît plus vite que le gain de qualité au-delà d'un certain nombre d'agents | Étude citée (via recherche croisée, papier précis non confirmé au-delà de citations secondaires — **à vérifier avant de citer un chiffre exact**) : passage de 1 à 2 à 3 agents multiplie les tokens (ex. ~166 → 552 → 896 tokens/échantillon dans un cas mesuré) et la latence (x3 à x6) ; gain de qualité réel mais décroissant au-delà de 5-6 agents spécialisés |

**So what pour Deadweight** : la logique "routing = LLM cher utilisé comme classifieur = gaspillage" que l'outil détecte déjà est confirmée et quantifiée par la littérature (RouteLLM, FrugalGPT). Deadweight peut ajouter deux détections supplémentaires à fort ROI, bien sourcées : (1) détecter les workflows "batch-able" (pas de contrainte temps réel visible dans les logs, ex. traitement nocturne/rapport) qui n'utilisent pas la Batch API → -50% direct et quasi gratuit à recommander ; (2) détecter le contexte répété/gonflé d'un appel à l'autre (relecture de gros historique) comme un gaspillage même si le modèle et le pattern sont corrects, car la littérature montre que la longueur seule dégrade la qualité en plus de coûter cher.

---

## 3. Ce que disent les études récentes — chiffres et sources

- **FrugalGPT** (Chen, Zaharia, Zou — Stanford, arXiv:2305.05176, 2023, publié TMLR) : cascade de LLM (du moins cher au plus cher) → jusqu'à **98% de réduction de coût** à qualité égale au meilleur modèle individuel (GPT-4) sur HEADLINES, ou **+4% de qualité** à coût identique. Stratégies : adaptation de prompt, approximation de LLM, cascade.
- **RouteLLM** (Ong, Almahairi, Wu et al., LMSYS/UC Berkeley, arXiv:2406.18665, juil. 2024) : routeur appris sur données de préférence (Chatbot Arena) → **-85% de coût sur MT-Bench, -45% sur MMLU, -35% sur GSM8K**, pour ~95% de la performance de GPT-4 seul. Code et données publiés en open source.
- **NVIDIA — Small Language Models are the Future of Agentic AI** (Belcak et al., arXiv:2506.02153, 2025) : position paper affirmant que pour les tâches agentiques répétitives et peu variées, les SLM sont **10 à 30x moins chers** à l'inférence, latence plus faible, fine-tuning en une nuit vs semaines pour un LLM. Recommande des systèmes hétérogènes (SLM + LLM ponctuel) plutôt que tout-LLM.
- **Context Length Alone Hurts LLM Performance Despite Perfect Retrieval** (ACL Findings EMNLP 2025) : sur 5 LLM open/closed source, tâches maths/QA/code — dégradation de **13,9% à 85%** de performance quand la longueur d'input augmente, indépendamment de la qualité de récupération (même avec masquage des tokens non pertinents). Contredit l'idée que "plus de contexte pertinent = toujours mieux".
- **Batch API — pricing officiel** : OpenAI (docs officielles, développeur, 2026) et Anthropic (Message Batches API, 2026) offrent chacun **-50%** sur les prix input/output pour les requêtes asynchrones traitées sous 24h, cumulable avec le prompt caching côté Anthropic. Limites : 50 000 requêtes/batch (OpenAI), 100 000 requêtes ou 256 Mo (Anthropic).
- **The Harness Effect** (arXiv:2607.06906, papier **sponsorisé par Writer**, à traiter comme source industrielle et non indépendante) : à modèle constant, changer uniquement la couche d'orchestration (harnais) réduit le coût de **41%** ($0,21→$0,12/tâche), le temps de **44%** (48s→27s), les tokens de **38%** (14,2k→8,8k), qualité de tâche équivalente. Les gains d'efficacité sont "model-invariant" (-33% à -61% selon le modèle testé), les gains de qualité dépendent de la capacité de base du modèle. **Non vérifié de façon indépendante** — méthodologie contrôlée par l'éditeur du harnais testé (conflit d'intérêt évident, à citer avec cette réserve explicite).
- **Multi-agent overhead** : plusieurs sources convergentes (papiers académiques + articles techniques croisés, ex. token economics survey arXiv:2605.09104, articles dérivés) indiquent que le coût token croît plus vite que linéairement avec le nombre d'agents (ex. un cas mesuré : ~166 → 552 → 896 tokens pour 1 → 2 → 3 agents), et la latence peut ralentir de 3x à 6x en configuration 3 agents vs 1 agent. Le gain de qualité existe mais devient marginal au-delà de ~5-6 agents spécialisés (coordination overhead dépasse le gain de spécialisation). **Chiffres à considérer comme des ordres de grandeur observés dans des études ponctuelles, pas des constantes universelles** — non retrouvé de méta-analyse consolidée sur ce point précis.
- **"Lost in the middle"** (Liu et al., Stanford, arXiv:2307.03172, 2023) : référence historique (>2 ans mais fondatrice et toujours citée) — courbe en U de rappel selon la position de l'info pertinente dans le contexte ; complète le résultat EMNLP 2025 ci-dessus.

**Non trouvé / non vérifié** :
- Pas de méta-analyse académique consolidée et récente chiffrant précisément "à partir de combien d'agents la coordination devient contre-productive" toutes tâches confondues — les chiffres ci-dessus viennent d'études ponctuelles sur des benchmarks spécifiques.
- Aucune étude indépendante (hors papier Writer) mesurant précisément le delta coût/qualité "harnais lourd (Claude Code, Codex) vs harnais minimal (type Pi) vs appels API bruts" — à traiter comme question ouverte, pas de chiffre fiable disponible actuellement.

---

## 4. Comment rester à jour — sources à surveiller

- **Anthropic Engineering blog** (anthropic.com/research, anthropic.com/engineering) — publie régulièrement des retours d'expérience patterns/coûts (ex. *Building Effective Agents*, *Claude Code: best practices*).
- **OpenAI Cookbook** (github.com/openai/openai-cookbook) et guides business (cdn.openai.com/business-guides-and-resources) — patterns d'orchestration et exemples à jour avec l'API.
- **arXiv cs.CL / cs.AI**, recherche par mots-clés "agentic", "LLM routing", "LLM cascade", "token economics" — les papiers cités ici (FrugalGPT, RouteLLM, NVIDIA SLM, Harness Effect, Token Economics survey) sont tous sur arXiv ; un living repo existe pour le survey Token Economics : github.com/SuDIS-ZJU/Token-Economics.
- **LMSYS blog** (lmsys.org/blog) — origine de RouteLLM, suit les benchmarks de routing/coût.
- **Simon Willison's newsletter** (simonw.substack.com / simonwillison.net, tag "agentic-engineering") — veille pratique et critique sur les patterns d'ingénierie agentique, souvent très concret sur les coûts réels observés.
- **Latent Space** (latent.space) — podcast/newsletter AI Engineer, couvre agents/devtools/infra, bon signal sur les nouveaux frameworks (ADK, A2A, MCP).
- **Google ADK docs / Google Developers Blog** (google.github.io/adk-docs, developers.googleblog.com) — évolution rapide des primitives d'orchestration (Sequential/Parallel/Loop → Workflow engine graph-based en 2026).
- **Repo GitHub "awesome-agentic-engineering-resources"** (EthicalML) — liste curatée d'articles, papiers, benchmarks, newsletters sur le sujet, bon point de départ périodique.

---

Voir aussi : `docs/positionnement.md`, `docs/research/positionnement.md`.
