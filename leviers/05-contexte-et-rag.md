# 5. Trop de contexte envoyé (historique, RAG)

| | |
|---|---|
| Famille | Forme des briques d'IA |
| Gain argent | Coût d'entrée ÷2 à ÷10 |
| Gain latence | Moyenne |
| Comment prouver | Banc (contexte réduit) |
| Données nécessaires | Événements (taille des messages) |
| État | Symptôme détecté (R3) ; causes RAG à faire |
| Règle | R3 raw_context |

## Le signal
La taille des requêtes grossit à chaque tour ; des documents entiers sont renvoyés.

## Comment le détecter
Croissance du nombre de jetons d'entrée dans une trace ; blocs répétés d'un appel à l'autre.

## Ce qu'on propose au client
Résumer l'historique ; RAG : morceaux plus petits, moins de documents, un reclasseur ; ne pas ré-encoder les documents à chaque exécution ; pas de RAG sur un petit corpus.

## Comment le prouver avant de le recommander
Banc de modèles avec le contexte réduit : la réponse reste-t-elle la même ?

## Suite
Détecter la forme du RAG (nombre et taille des extraits) dans les requêtes.
