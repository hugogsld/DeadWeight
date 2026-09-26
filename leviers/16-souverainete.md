# 16. Des données qui partent hors d'Europe

| | |
|---|---|
| Famille | Conformité |
| Gain argent | — |
| Gain latence | — |
| Comment prouver | Catalogue (origine, hébergement) |
| Données nécessaires | Événements + catalogue M1 |
| État | Fait (data_outside_eu, catalogue M1/M2) |
| Règle | data_outside_eu |

## Le signal
Appels vers un fournisseur sans hébergement UE (API directe d'Anthropic, par exemple).

## Comment le détecter
Destination réelle de chaque appel (upstream capturé par la passerelle, sinon déduite du format), qualifiée par le catalogue : UE, hors UE, ou non garantie.

## Ce qu'on propose au client
D'abord le même modèle en région UE quand l'éditeur la propose (aucun changement de qualité) ; sinon un modèle d'éditeur européen, nommé seulement pour une tâche simple (R2), à tester au banc.

## Comment le prouver avant de le recommander
Banc de modèles sur l'alternative.

## Suite
Argument fort pour les clients français.
