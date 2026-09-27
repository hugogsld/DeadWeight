"""Seuil de précision mesurée, partagé entre les propositions d'optimize/propose.py.

0,95 est déjà la valeur choisie indépendamment par ``proof.replay.THRESHOLD`` (rejeu des
règles extraites, D3.2) et ``bench.scoring.CLASSIFICATION_THRESHOLD`` (banc de modèles,
M2.2). Cette constante ne les remplace pas : ce sont des seuils historiques, chacun propre
à sa preuve, et les changer casserait des rejeux déjà publiés. Elle évite seulement de
redéfinir une troisième fois la même valeur à chaque nouveau levier ajouté à ``propose()``.
"""
PRECISION_THRESHOLD = 0.95
