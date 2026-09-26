# 18. Images en haute résolution, relecture par un LLM juge

| | |
|---|---|
| Famille | Usage des LLM |
| Gain argent | Images : ÷5 à ÷10 ; relecture : ×2 évité |
| Gain latence | Moyenne |
| Comment prouver | Calcul + banc |
| Données nécessaires | Événements |
| État | Détection faite (R15, R16), qualité et gains à confirmer |
| Règle | R15 image_heavy ; R16 llm_judge |

## Le signal
Vision en détail haut pour lire un titre ; un deuxième LLM qui juge chaque réponse.

## Comment le détecter
Paramètres d'image ; paires d'appels « génération puis jugement ».

## Ce qu'on propose au client
Basse résolution ; relecture par échantillon ou par règle.

## Comment le prouver avant de le recommander
Banc de modèles.

## Suite
—
