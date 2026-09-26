# 10. Un appel LLM par élément au lieu d'un appel groupé

| | |
|---|---|
| Famille | Forme du workflow |
| Gain argent | ÷5 à ÷20 |
| Gain latence | ÷5 à ÷20 |
| Comment prouver | Banc (lot vs unitaire) |
| Données nécessaires | Historique n8n (B1) |
| État | À faire (R11, après B1) |
| Règle | R11 (à venir) |

## Le signal
Une étape LLM dans une boucle sur les lignes d'un tableau.

## Comment le détecter
Graphe n8n (nœud LLM dans une boucle) ou rafales d'appels du même gabarit.

## Ce qu'on propose au client
Regrouper les éléments dans un seul appel structuré, ou l'API batch.

## Comment le prouver avant de le recommander
Banc de modèles sur l'appel groupé.

## Suite
—
