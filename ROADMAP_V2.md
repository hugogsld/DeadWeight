# Deadweight — roadmap v2 : samedi après-midi → dimanche après-midi

La v1 (`ROADMAP.md`) prévoyait 60 h ; on l'a quasiment bouclée en une matinée à quatre, agents compris.
Cette v2 est **recalibrée sur ce rythme** : les durées sont des heures réelles d'une personne avec son agent,
pas des estimations « à la main ». Même règles de repo que la v1 (une tâche = une issue = une branche = une PR).

Suivi en continu : issue épinglée « Avancement du weekend (automatique) ».

## Ce qui change

On a une passerelle qui marche et un rapport sur six règles. Il reste trois choses qui décident du hackathon :

1. **Être éligible.** Le règlement X-IA exige un « véritable projet agentique » (LLM + raisonnement, décision,
   orchestration) et ne note **que ce qui a été fait pendant le hackathon**. Aujourd'hui, notre audit est
   surtout du code déterministe : il faut un agent auditeur visible, et déclarer le prototype du 12/09.
2. **Prouver l'impact sur de vrais workflows** (30 % de la note). Des chiffres sur nos jeux de test ne
   suffisent pas : il faut deux ou trois workflows réels, audités, avec « voici ce que vous économisez ».
3. **Une démo de 2 minutes limpide** (15 % pitch + 15 % UX). Tout ce qui ne se voit pas dans la vidéo
   compte peu.

## Règlement X-IA — ce qui nous concerne

| Point | Ce que dit le règlement | Conséquence pour nous |
|---|---|---|
| Dépôt | **dimanche 27/09 à 23:59**, hors délai refusé | on vise **dimanche 20 h**, marge de 4 h |
| Livrables | vidéo **≤ 2 min**, description courte, lien du repo **avec instructions de test dans le README**, noms des membres | V1 à V4 ci-dessous |
| Agentique | LLM + « raisonnement, prise de décision, orchestration d'actions » ; pas un script sans LLM | lot A (agent auditeur) |
| Existant | autorisé, **à mentionner** ; seule la partie faite pendant le hackathon est évaluée ; sinon disqualification possible | A2 : section « construit ce weekend » |
| Participation | membres X-IA à jour de cotisation, équipe déclarée sur Luma | A3 : vérifier les quatre |
| Notation | 30 % impact et utilité · 20 % innovation · 20 % qualité · 15 % UX · 15 % clarté démo/pitch | l'ordre des lots suit ces poids |
| Finale | 5 finalistes, pitch live (octobre/novembre) | hors weekend |

Partenaires avec crédits : OpenAI, Pipelex (workflows agentiques déterministes), Dust (plateforme d'agents),
Gradium (voix), Jinko (voyage). Le règlement ne mentionne **pas de prix réservé** à l'usage d'un partenaire ;
les intégrer sert la note (innovation, qualité) et la visibilité, pas une éligibilité.

## Encore ouvert de la v1

| Id | Livrable | Qui | État |
|---|---|---|---|
| D1.3 | Anthropic et Gemini | Alexandre | conflit à résoudre avec main (consignes données), puis fusion |
| D2.4 | R5 boucle + R6 agent inutile | Thibaud | relu, à passer de brouillon à prêt |
| D4.2 | Installation dix minutes | Codex (Natan) | en cours |
| D4.3 | Mode miroir | Alexandre après D1.3 | à partir du code du court-circuit (D3.3) |
| D4.4 | Test par un tiers | Natan trouve le testeur | dimanche ~15 h 30 |

## Les lots

Difficulté comme en v1 : ★ mécanique → ★★★★★ on ne sait pas encore faire.

### Lot A — Éligibilité : un agent qui audite les agents (samedi, priorité 1)

- **A1 — Agent auditeur** · 3 h · ★★★. Un agent LLM (OpenAI, tool calling) qui orchestre l'audit : il a pour
  outils `lister_apps`, `lancer_regle`, `extraire_regles`, `rejouer`, `alternatives_modele`, `ecrire_rapport` ;
  il décide quels constats méritent une preuve, lance le rejeu, lit le verdict, et rédige les recommandations
  en langage clair. Les chiffres restent calculés par le code, jamais par le modèle. Fin : `make audit` passe
  par l'agent, et son raisonnement (étapes, outils appelés) apparaît dans le rapport.
- **A2 — Section « Construit pendant le hackathon »** · 30 min · ★. README : ce qui vient du prototype du 12/09
  (lecture n8n, entropie, rejeu n8n) et ce qui a été fait ce weekend (passerelle, capture, traces, six règles,
  rejeu, court-circuit, rapport, installation). Fin : relu par les quatre.
- **A3 — Inscriptions** · 15 min · non dev. Les quatre sont membres X-IA à jour et déclarés dans la même équipe
  sur Luma. Fin : capture d'écran dans le fil de l'équipe.

### Lot B — Vrais workflows (samedi soir → dimanche midi, 30 % de la note)

Trois cas selon ce qu'on reçoit ; on prépare les trois.

- **B1 — Banc n8n** · 2 h · ★★★. n8n local (docker) dont les identifiants OpenAI pointent vers la passerelle.
  On importe un export de workflow, on le lance sur N entrées d'exemple, le trafic est capturé. Fin : un
  workflow n8n importé produit un rapport sans modifier le workflow.
- **B2 — Convertisseur de logs** · 1 h · ★★. Export d'appels (JSON, CSV : prompt, réponse, modèle, date,
  jetons) → événements au schéma. Fin : un export réel donne un rapport.
- **B3 — Analyse workflow 1, puis 2** · 1 h 30 chacun · ★★★. Audit, lecture critique des constats
  (vrais / faux positifs), fiche d'une page : coût actuel, coût après, latence, ce qu'on propose. Fin : fiche
  validée par l'entreprise ou au moins relue par nous quatre.
- **B4 — Trouver un 3ᵉ workflow** · 1 h · non dev. Modèles publics n8n/Make en marketing (tri de leads,
  personnalisation d'emails, réponse aux avis), ou une entreprise du réseau. Fin : un workflow de plus en main.
- **B5 — Confidentialité** · 30 min · ★. Dossier `private/` ignoré par git, données effacées après le test,
  engagement écrit envoyé aux entreprises. **Aucun prompt client sur GitHub.**

### Lot C — Au-delà des LLM : les autres outils du workflow (dimanche matin)

Un workflow marketing appelle aussi de la recherche web, du scraping, de l'enrichissement, de l'envoi d'emails.
Ce sont souvent eux qui coûtent ou qui ralentissent.

- **C1 — Relais HTTP générique** · 2 h · ★★★. La passerelle relaie n'importe quelle API outil
  (`/x/<hôte>/…`) et mesure appels, latence, erreurs, doublons, sans jamais stocker les clés. Fin : un appel
  Tavily ou Firecrawl relayé apparaît dans les événements.
- **C2 — Constats outils** · 1 h 30 · ★★. Même requête payée plusieurs fois, appels en série qui pourraient
  être en parallèle, taux d'erreur, coût par appel (catalogue de prix des outils). Fin : un constat outil dans le
  rapport, chiffré.

### Lot D — Catalogue de modèles et recommandations (samedi soir)

- **D1 — Catalogue** · 1 h 30 · ★★. Un fichier de données versionné : prix entrée/sortie/cache, latence (TTFT,
  jetons/s), indicateur de qualité, fenêtre de contexte, **origine (FR/UE/US/CN) et hébergement UE possible**,
  compatibilité API OpenAI, avec la source et la date de chaque chiffre. Fin : chaque modèle du jeu de données
  y figure.
- **D2 — Recommandations concrètes** · 2 h · ★★★. R2 (modèle surdimensionné) et le rapport proposent une
  alternative précise avec son gain en coût et en latence, et une **option souveraine** (Mistral, hébergement
  UE) quand elle existe. Fin : chaque constat R2 affiche « passer de X à Y : −N % de coût, origine ».

### Lot E — Partenaires (dimanche, si A et B sont bouclés)

- **E1 — Export Pipelex** · 2 h · ★★★★. Le remplacement prouvé (règles + modèle de secours) exporté en
  pipeline Pipelex : c'est exactement leur promesse, des workflows agentiques déterministes. Fin : le pipeline
  exporté tourne dans Pipelex sur l'exemple mail-triage.
- **E2 — Résumé vocal Gradium** · 1 h · ★. Le rapport lu en 30 secondes. Utile dans la vidéo, sinon à couper.
- **E3 — Agent Dust** · 1 h 30 · ★★. Poser des questions à son audit depuis Dust. Le moins prioritaire.

### Lot Q — Tests

- **Q1 — Test de bout en bout en CI** · 1 h · ★★. `make demo` (faux serveur amont → passerelle → rapport)
  lancé à chaque PR. Fin : la CI casse si le parcours d'installation casse.
- **Q2 — Tests dorés sur les vrais workflows** · 1 h · ★★. Chaque workflow analysé devient un cas de test
  anonymisé : constats attendus, faux positifs interdits. Fin : un workflow réel dans les tests.
- **Q3 — Test par un tiers (D4.4)** · 2 h · non dev. Voir le protocole plus bas.

### Lot V — Démo et dépôt (dimanche)

- **V1 — Script de la vidéo** · 1 h · non dev. 2 minutes, structure proposée :
  0:00 le problème (on paie des modèles haut de gamme pour trier des mails) ·
  0:20 une ligne changée (`base_url`) · 0:35 l'agent auditeur au travail ·
  1:00 le rapport sur un vrai workflow, chiffres · 1:30 la preuve par le rejeu et le court-circuit ·
  1:50 l'appel à l'action.
- **V2 — Tournage et montage** · 2 h · non dev. Samedi soir pour les plans d'écran, dimanche pour le montage.
- **V3 — Description et README final** · 30 min · ★. Description de quelques lignes, instructions de test,
  noms des quatre, section A2.
- **V4 — Dépôt** · 15 min. **Dimanche 20 h**, jamais après 22 h.

## Planning

| | Samedi 14 h – 20 h | Dimanche 10 h – 14 h | Dimanche 14 h – 20 h |
|---|---|---|---|
| **Natan** | orchestration, relectures ; B4, B5, A3 ; testeur D4.4 | B3 avec l'équipe ; V1 | D4.4 (observer) ; V2, V3, V4 |
| **Hugo** | **A1 agent auditeur** | E1 Pipelex | corrections après D4.4 |
| **Thibaud** | D2.4 prête ; **B1 banc n8n** | C1, C2 | gel, relectures |
| **Alexandre** | D1.3 fusionné ; D4.3 miroir | D1, D2 catalogue | E2 si le temps |
| **Codex** | D4.2 | Q1 | — |
| **Claude** | relectures et fusions ; B2 convertisseur | Q2 ; A2 | relecture finale du README |

**Gel dimanche 14 h** : plus de nouvelle fonctionnalité. Ensuite, corrections, D4.4, vidéo et dépôt.

## Ordre de coupe si on déborde

1. E3, puis E2, puis E1 (partenaires).
2. C2, puis C1 (outils hors LLM) — on les garde pour la finale.
3. D2 (on garde le catalogue D1 dans le rapport).
4. B3 sur le 2ᵉ et le 3ᵉ workflow — un seul vrai workflow bien analysé suffit.

**On ne coupe jamais A1, A2, un vrai workflow (B3), D4.4, la vidéo et le dépôt.**

## D4.4 — protocole du test par un tiers

- **Qui** : quelqu'un hors de l'équipe, jamais briefé, avec un terminal, Python 3.11, sa clé OpenAI et
  idéalement une petite appli. Pas un ami proche. Prévoir un remplaçant.
- **Quand** : dimanche vers 15 h 30, 45 minutes.
- **Comment** : on lui envoie le lien du repo, rien d'autre. Un observateur note l'heure de chaque étape,
  chaque hésitation de plus de 30 s, chaque question, chaque erreur, **sans jamais aider**.
- **Critères** : il change `base_url` seul ; il fait passer du trafic ; une commande lui donne le rapport ;
  il ne nous a pas appelés ; le tout en moins de 10 minutes.
- **Après** : qu'est-ce qui t'a bloqué ? qu'as-tu compris du rapport, en une phrase ? le paierais-tu ?
  Chaque blocage devient une correction avant 18 h, README et messages d'erreur d'abord.

## Tâches hors code

| Tâche | Qui |
|---|---|
| Recevoir les workflows, demander le format (export n8n, logs, ou accès via la passerelle), envoyer l'engagement de confidentialité | Natan |
| Trouver un 3ᵉ workflow (B4) | Natan ou Hugo |
| Testeur D4.4 et remplaçant | Natan |
| Faire lire le rapport à quelqu'un hors équipe (critère de D4.1 jamais vérifié) | n'importe qui, 15 min |
| Script, tournage, montage de la vidéo | Natan + un volontaire |
| Liste des 5 entreprises pour la validation, message d'approche | Natan |
