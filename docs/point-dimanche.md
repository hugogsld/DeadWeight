# Deadweight · dimanche 27/09

> **Il est 15 h 40. Dépôt visé à 20 h** (limite du règlement : 23 h 59).
> Il reste environ **4 heures utiles**. Tout ce qui n'est pas dans ce document attend la finale.

---

## 1. Ce qu'on a fait, en 30 secondes

**Deadweight se branche sur n'importe quel workflow d'agents IA, trouve ce qui coûte sans servir, le prouve
sur le vrai historique, et livre la correction sous forme de petite PR à accepter.**
Tout tourne chez le client : ses clés ne sont jamais stockées, ses données ne sortent pas.

&nbsp;

| | |
|---|---|
| **Se brancher** | passerelle (une ligne à changer) · OpenTelemetry · journaux Claude Code et Codex · historique n8n |
| **Analyser** | 20 vérifications : modèle trop gros, IA qui ne fait qu'aiguiller, contexte relu à chaque appel, boucles, données hors d'Europe… |
| **Prouver** | on rejoue les vrais appels passés et on compare aux anciennes réponses |
| **Livrer** | rapport d'une page · agent auditeur · petites PR prêtes à accepter · message Slack (gains prouvés seulement) |

&nbsp;

**Samedi, en chiffres** : 63 PR fusionnées · 454 fonctions de test · une CI qui rejoue tout le parcours de la démo
à chaque modification.

**Testé sur de vrais workflows** : le Claude Code de Natan (72 % du coût = relire le contexte), l'usine de shorts de
Miguel (7,21 $ par short), le récap Gmail de Thibaud, le triage officiel d'OpenAI (aucun faux positif), un modèle
n8n de tri d'emails. Chacun de ces tests a corrigé quelque chose dans le produit.

Le détail complet : `docs/etat-du-projet.md`.

---

## 2. Qui fait quoi cet après-midi

&nbsp;

### Alexandre · deux workflows n8n pour la démo
Des modèles **très utilisés en entreprise**, avec **plusieurs appels de modèles** (c'est là qu'on a de la marge),
et **le moins possible d'API payantes ou exotiques**.
➜ À livrer **vers 16 h 15** : sans eux, pas de démo mesurée. Critère simple : au moins une étape qui classe ou trie,
et au moins 30 éléments à faire passer (en dessous, la vérification « IA qui aiguille » ne se déclenche pas).

&nbsp;

### Hugo · deux personnes pour le test utilisateur filmé
On les filme en train d'installer Deadweight et de voir ce qu'il trouve sur un workflow téléchargé avant.

> ⚠️ **Ne pas dire qu'on les a trouvées sur Reddit.** Le règlement exclut une équipe pour fraude, et un faux
> témoignage en est un : si un juré demande le message d'origine, on est pris. **Même vidéo, cadrage honnête** :
> « mise en situation inspirée de vraies plaintes », en montrant 2 ou 3 vrais messages Reddit sur le coût des jetons.

&nbsp;

### Thibaud · vérifier que chaque voie de connexion marche
| Voie | Existe ? | Commande |
|---|---|---|
| Passerelle (`base_url`) | ✅ | `make dev` puis changer `base_url` |
| OpenTelemetry | ✅ | `python -m connectors.otel traces.json` ou `/v1/traces` |
| Claude Code, Codex | ✅ | `python -m connectors.agent_logs ~/.claude/projects` |
| n8n | ✅ | `python -m importers.n8n check / fetch / convert` |
| **Make** | ❌ **n'existe pas** | ne pas l'annoncer |

➜ Chaque voie testée sur une machine propre, le temps noté, les messages d'erreur relevés.

&nbsp;

### Natan · coordination, vidéo, dépôt
Voir la section 3 : c'est là que sont les tâches oubliées.

&nbsp;

### Claude · relire, fusionner, préparer la démo
Les PR en attente, la démo mesurée sur les workflows d'Alexandre, la section obligatoire du README.

---

## 3. Les tâches qu'on risque d'oublier

### 🔴 Obligatoires pour le dépôt
| Tâche | Qui | Temps |
|---|---|---|
| **Vérifier les cotisations X-IA des quatre** et l'équipe déclarée sur Luma (sinon, pas éligibles) | Natan | 5 min |
| **Section « construit pendant le hackathon »** dans le README : le prototype du 12/09 déclaré (sinon, disqualification possible) | Claude | 20 min |
| **README de démarrage** à jour : installation, les quatre voies, `optimize` (le règlement demande des instructions de test) | Claude | 20 min |
| **Description courte** du projet (quelques lignes) + **noms des quatre** | Natan | 10 min |
| **Vidéo de 2 minutes maximum** | Natan + Hugo | 1 h 30 |
| **Dépôt** sur le formulaire X-IA | Natan | 10 min |

### 🟠 Pour que la démo tienne
| Tâche | Qui | Temps |
|---|---|---|
| Relire et fusionner les PR en attente : #108 (petites PR sur n8n et par alias), #109 (pitch de Hugo), #97 (bibliothèque n8n d'Alexandre) | Claude | 30 min |
| **La démo mesurée** : un workflow d'Alexandre → rapport → proposition prouvée → petite PR → message Slack | Claude + Alexandre | 1 h |
| Vérification finale sur une copie neuve du dépôt : installation, tests, parcours de démo | Claude | 15 min |
| **Contrôle de sécurité** avant dépôt : aucun secret dans le dépôt, aucune donnée client (le fichier de Miguel et les journaux restent hors du dépôt) | Claude | 10 min |

### 🟡 Seulement s'il reste du temps
- Détection des aiguillages par appel d'outil et des classifieurs en JSON (le prompt Codex est prêt, issue #105).
- Terminer « abonnement ou paiement à l'usage » (le travail est sauvé sur sa branche, tests verts).
- Test avec un modèle local (Ollama) pour dire « aucune donnée ne sort, même pour l'audit ».

### ⏸️ Après le hackathon
- Réponse à Miguel (audit local, correctif pour ses 6 agents mécaniques, uniquement s'il le veut).
- Recherche « manière optimale de construire un workflow » (`docs/research/patterns-workflows.md`).

---

## 4. Le planning

| Heure | Quoi |
|---|---|
| **15 h 40 – 16 h 15** | Alexandre choisit les workflows · Claude fusionne les PR · Natan vérifie les cotisations |
| **16 h 15 – 17 h 15** | Démo mesurée sur les workflows choisis · Thibaud teste les voies · Hugo prépare le test filmé |
| **17 h 15 – 18 h** | Test utilisateur filmé · README et section obligatoire |
| **18 h – 19 h 15** | Montage de la vidéo · description courte · vérification finale |
| **19 h 15 – 20 h** | Contrôle de sécurité · **dépôt** |
| 20 h – 23 h 59 | Marge. On ne commence rien de nouveau. |

---

## 5. Ce qu'on ne dit pas dans la vidéo ni au pitch

- « Deadweight vous rend conforme RGPD » ➜ dire « documente vos flux pour votre DPO ».
- Un gain de latence sans dire lequel (la médiane et les cas les plus lents ne bougent pas pareil).
- Un chiffre de CO₂ évité sans source ni fourchette.
- « 50 à 90 % de gaspillage sur le marché » comme un fait : ce sont des ordres de grandeur de blogs.
- Make, ou toute voie de connexion non testée.
- Des utilisateurs « trouvés sur Reddit ».
