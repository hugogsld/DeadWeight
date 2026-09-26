# AGENTS.md — règles pour les agents de code (Claude Code, Codex)

Ce fichier s'applique à tout agent qui code dans ce repo. Il complète la
roadmap du weekend (26-27 septembre), il ne la remplace pas.

## Avant de coder

1. `git pull --rebase origin main`.
2. Tu travailles sur **un seul livrable**, celui que l'humain t'a confié.
   Tu ne choisis pas un livrable toi-même.
3. Vérifie l'issue du livrable (`gh issue view <n>`) :
   - elle porte l'étiquette de ton agent (`agent:claude` ou `agent:codex`) → tu peux y aller ;
   - elle porte l'étiquette de l'**autre** agent → tu t'arrêtes et tu le signales ;
   - elle n'en porte aucune → tu poses la tienne avant d'écrire une ligne :
     `gh issue edit <n> --add-label agent:claude` (ou `agent:codex`).

## Pendant

- Un livrable = une branche = une PR. Nommage : `feat/D2.3-raw-context-no-cache`.
- Chaque agent a son propre dossier de travail (git worktree). Ne jamais
  travailler dans le dossier de l'autre agent, ne jamais basculer sa branche.
- Ne touche qu'aux fichiers de ton livrable. Si tu dois modifier un fichier
  partagé (`schemas/`, `fixtures/`, `README.md`, `Makefile`, CI), dis-le à
  l'humain avant, et garde la modification minimale.
- Les formats de `schemas/` et `fixtures/` sont des contrats : quatre personnes
  codent contre eux. Aucun changement cassant sans accord explicite.
- Aucun secret dans le repo. Les clés vivent dans `.env.local`.

## Avant la PR

1. `git pull --rebase origin main`, puis relancer les tests.
2. PR avec `Closes #<n>` dans la description.
3. Si la PR ajoute une commande, le README est mis à jour dans la même PR.
4. Pas de fusion sur `main` par l'agent : c'est une relecture humaine.

## Étiquettes

| Étiquette | Sens |
|-----------|------|
| `agent:claude` | livrable en cours chez Claude Code |
| `agent:codex` | livrable en cours chez Codex |

Une issue sans étiquette `agent:*` et assignée à quelqu'un est faite à la main.
