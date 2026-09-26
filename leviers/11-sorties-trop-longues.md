# 11. Des réponses trop longues

| | |
|---|---|
| Famille | Usage des LLM |
| Gain argent | 20 à 60 % (la sortie coûte 4 à 8 fois l'entrée) |
| Gain latence | Proportionnelle |
| Comment prouver | Calcul + banc |
| Données nécessaires | Événements |
| État | En cours (R12) |
| Règle | R12 verbose_output |

## Le signal
Beaucoup de jetons de sortie, pas de plafond, réponses tronquées ou bavardes.

## Comment le détecter
Distribution des longueurs de sortie par gabarit ; max_tokens absent ; fin par longueur.

## Ce qu'on propose au client
Plafonner, demander une sortie structurée et concise.

## Comment le prouver avant de le recommander
Banc avec plafond : la réponse utile reste-t-elle ?

## Suite
—
