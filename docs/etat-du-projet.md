# Deadweight : où on en est (samedi 26/09, fin de soirée)

## En une phrase

Deadweight se branche sur n'importe quel workflow d'agents IA, trouve ce qui coûte sans servir, **prouve**
chaque amélioration sur le vrai historique du client, puis la livre sous forme de **petite PR** à accepter,
avec un message Slack qui ne montre que les gains prouvés (en mode démo, il affiche aussi les propositions refusées). Tout tourne chez le client.

**Au 27/09 : 123 commits et 82 PR fusionnées les 26 et 27/09, 20 vérifications, plus de 850 tests, CI de bout en bout verte.**

---

## 1. Ce qu'on a construit aujourd'hui

### Les portes d'entrée : on se branche partout

| Connexion | Pour qui | État |
|---|---|---|
| **Passerelle** (on change une ligne, `base_url`) | toute application codée | fait, testée sur un vrai workflow |
| **OpenTelemetry** (le standard de traces) | LangChain, SDK d'agents OpenAI, Vercel AI… | fait (import de fichier et réception en direct) |
| **Journaux Claude Code et Codex** | équipes qui automatisent avec ces outils | fait, testé sur les vrais journaux de Natan |
| **Historique n8n** | workflows no-code | fait, testé sur un vrai modèle n8n |

Méthode commune : `docs/analyser-un-workflow.md` (trois niveaux de données : usage, contenu, structure).

### Le cœur d'analyse : 20 vérifications

- **Le modèle** : une IA qui ne fait qu'aiguiller, un modèle trop gros, un modèle qui réfléchit trop, des réponses
  trop longues.
- **Le contexte** : tout l'historique renvoyé, le cache non utilisé, **le contexte relu à chaque appel** (le premier
  poste de coût des agents de code), un cadre d'exécution trop lourd, des définitions d'outils inutiles.
- **La forme du workflow** : des boucles, un agent là où une chaîne suffit, des étapes qui pourraient tourner en
  parallèle, un appel par élément, des étapes fusionnables, une IA qui relit chaque réponse.
- **Le reste** : les mêmes appels payés deux fois, des erreurs payées, ce qui pourrait passer en API batch, des images
  trop coûteuses, **les données qui partent hors d'Europe**.

### La preuve, ce qui nous distingue

- **Rejeu** : on rejoue les vrais appels passés avec la modification, et on compare aux anciennes réponses.
- **Banc de modèles** : on teste un modèle plus petit, local ou européen, sur les vraies entrées.
- **Mode miroir, court-circuit** : on observe les règles en production sans risque, puis on les active.

### Ce qu'on livre au client

- **Le rapport d'une page**, avec des chiffres justes : coût mesuré sur les prix réels (catalogue OpenRouter, cache
  compris), pas de projection mensuelle sous une journée d'observation, coût partiel plutôt que « non disponible ».
- **L'agent auditeur** (condition du hackathon : un vrai agent) : il enquête, choisit quoi prouver, et rédige un plan
  d'action. Il ne peut citer aucun chiffre qui ne vient pas de nos outils, et chaque chiffre doit porter le bon nom.
- **Les propositions testées et les petites PR** (`python -m optimize`) : pour chaque constat, une modification, testée,
  et la PR qui l'active. Chaque chiffre est étiqueté « mesuré », « estimé » ou « non testé ».
- **Le message Slack** : uniquement les gains prouvés (en mode démo, il affiche aussi les propositions refusées). **La page développeur** : tout, y compris ce qui a échoué.

---

## 2. Les tests sur de vrais workflows (et ce qu'ils nous ont appris)

| Workflow | Connexion | Ce que Deadweight a trouvé | Ce que ça a corrigé dans le produit |
|---|---|---|---|
| **Claude Code de Natan** (6 049 appels, 24 jours) | journaux | 72 % du coût = relire le contexte ; 59 000 jetons dès le premier appel | nouvelle vérification « contexte relu » ; projection juste (les constats dépassaient le total) |
| **claude-mem** (plugin, 2 652 appels) | journaux | +43 % d'appels cachés en plus de Carlo | vérification « étapes parallèles » regroupée (313 constats → 1) |
| **Usine de shorts de Miguel** (run 28, 12 shorts) | fichier d'usage par agent | 7,21 $ par short ; les agents auteurs relisent 180 000 jetons par tour (62 à 74 % de leur coût) | recette « modèle par alias » en cours ; recommandations corrigées après vérification du code |
| **Récap Gmail** (Thibault, 88 vrais appels) | passerelle | tri des mails = aiguillage | 4 problèmes corrigés : projection sur les workflows par lots, banc sans instructions, chiffres mal attribués par l'agent, modèle sans clé affiché « refusé » |
| **Triage officiel OpenAI** (54 appels) | passerelle | rien à optimiser, et c'est juste (aucun faux positif) | trous repérés : aiguillage par appel d'outil, conversations non regroupées |
| **Tri d'emails n8n** (modèle n8n.io #7399) | historique n8n | un appel par email ; classifieur à 4 réponses | seuil de 30 appels non atteint avec 25 emails : relance avec 60 emails en cours |

Leçon principale : **sur les agents de code, le contexte coûte plus que le travail lui-même.** Et **rien ne doit
être affirmé sans avoir été vérifié** : chaque chiffre porte maintenant son statut.

---

## 3. Où on en est exactement

### Fait et fusionné
Tout ce qui précède, sur `main`.

### En cours ce soir
| Tâche | Qui |
|---|---|
| n8n avec 60 emails → la **petite PR qui modifie le workflow n8n**, avec les gains mesurés ; recette « modèle par alias » essayée en local sur le dépôt de Miguel (**rien n'est poussé chez lui**) | agent |
| **Abonnement ou paiement à l'usage** : le détecter, afficher le vrai coût et les limites ; gains **tâche par tâche** dans le rapport | agent |
| Détection : aiguillage par appel d'outil, classifieurs qui répondent en JSON, conversations sans en-tête (issue #105) | Codex (prompt donné) |
| PR #97 d'Alexandre : 1 000 workflows n8n de n8n.io pour les tests | à relire |

### Pas commencé
- L'exemple officiel « service client » branché par OpenTelemetry (la troisième connexion en démo).
- Le test avec un modèle local (Ollama) de bout en bout.

---

## 4. Demain (dimanche 27/09)

**Gel des nouvelles fonctionnalités à 14 h. Dépôt visé à 20 h (limite 23 h 59).**

### Le matin (jusqu'à 14 h)
| Priorité | Tâche | Qui | Temps |
|---|---|---|---|
| 1 | Relire et fusionner les PR de la nuit (n8n, abonnement, détection, #97) | Claude | 1 h |
| 2 | **Démo complète sur un vrai workflow** : rapport, proposition prouvée, petite PR, message Slack | Claude + Natan | 1 h |
| 3 | La troisième connexion en démo : service client OpenAI par OpenTelemetry | agent | 1 h |
| 4 | **A2** : section « construit pendant le hackathon » dans le README (obligatoire) | Claude | 30 min |
| 5 | **A3** : cotisations X-IA et équipe sur Luma (condition d'éligibilité) | Natan | 15 min |
| 6 | Positionnement : test avec un modèle local (Ollama) ; anonymisation et purge par défaut | équipe | 2 h |

### L'après-midi (après le gel)
| Tâche | Qui |
|---|---|
| **D4.4** : un testeur extérieur installe seul en moins de 10 min, sans aide (vers 15 h 30) | Natan observe |
| Corrections après le test | équipe |
| **Vidéo de 2 minutes** : script, tournage, montage | Natan + un volontaire |
| **Description courte, README final, noms des quatre** | Claude + Natan |
| **Dépôt X-IA** à 20 h | Natan |

### Toujours en attente
- Réponse de Miguel au message (audit local, test des agents mécaniques sur Sonnet).
- Slide dans le Canva de présentation (à faire **samedi**).

---

## 5. Décisions prises aujourd'hui

- **Tout tourne chez le client** : clés jamais stockées, données dans `private/`, jamais versionnées.
- **Chaque chiffre porte son statut** (mesuré, estimé avec l'hypothèse, non testé). Pas de chiffre arrondi pour faire joli.
- **Slack : gains prouvés seulement** ; la page développeur montre tout ; la démo peut montrer les échecs.
- **Une seule période d'observation par rapport**, et **pas de projection mensuelle sous une journée**.
- **Le dépôt de Miguel** : lecture seule, rien n'est poussé, il décide.
- La manière optimale de construire un workflow : **piste pour plus tard** (`docs/research/patterns-workflows.md`).
- Nom : **Deadweight**, pour l'instant.

## 6. À ne pas dire dans le pitch

- « Deadweight vous rend conforme RGPD » → dire : « Deadweight documente vos flux pour votre DPO ».
- Un chiffre de CO₂ évité sans source ni fourchette.
- Un gain de latence sans préciser lequel (médiane ou cas les plus lents : ils ne bougent pas pareil).
- Les statistiques de marché « 50 à 90 % de gaspillage » comme des faits : ce sont des ordres de grandeur de blogs.

Détails : `docs/positionnement.md`, `docs/research/positionnement.md`, `ROADMAP_V2.md`.
