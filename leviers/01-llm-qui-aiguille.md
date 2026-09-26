# 1. Un LLM qui ne fait qu'aiguiller

| | |
|---|---|
| Famille | Usage des LLM |
| Gain argent | 90 à 100 % de l'étape |
| Gain latence | ×1 000 (700 ms → 0,2 ms) |
| Comment prouver | Rejeu, seuil 95 % |
| Données nécessaires | Événements passerelle |
| État | Fait (R1, D3.1, D3.2, D3.3, D4.3) |
| Règle | R1 low_entropy_output |

## Le signal
Des centaines d'appels, une poignée de réponses différentes : le modèle classe, il ne raisonne pas.

## Comment le détecter
Entropie de Shannon des sorties normalisées, par application × modèle × gabarit de prompt.

## Ce qu'on propose au client
Remplacer par des règles fixes (mots-clés extraits de l'historique), le modèle gardé en secours pour les cas non couverts. Mode miroir d'abord, court-circuit ensuite.

## Comment le prouver avant de le recommander
Extraction des règles puis rejeu sur tout l'historique hors exemples ; refus sous 95 % d'accord. En production : mode miroir.

## Suite
Tester aussi un classifieur léger ou des embeddings quand les règles couvrent mal (banc de modèles).
