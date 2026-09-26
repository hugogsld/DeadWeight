# 6. Des étapes en série qui pourraient tourner en parallèle

| | |
|---|---|
| Famille | Forme du workflow |
| Gain argent | Aucun |
| Gain latence | Le plus gros gain : ×2 à ×5 sur le workflow |
| Comment prouver | Horaires d'exécution |
| Données nécessaires | Historique n8n (B1) |
| État | À faire (R10, après B1) |
| Règle | R10 (à venir) |

## Le signal
Deux étapes qui ne dépendent pas l'une de l'autre s'exécutent l'une après l'autre.

## Comment le détecter
Graphe du workflow (dépendances de données) + horaires réels de chaque nœud dans l'historique.

## Ce qu'on propose au client
Brancher les étapes indépendantes en parallèle.

## Comment le prouver avant de le recommander
Chemin critique recalculé à partir des vraies durées : latence avant / après.

## Suite
Seul argument latence sur la forme du workflow : priorité dès que B1 fonctionne.
