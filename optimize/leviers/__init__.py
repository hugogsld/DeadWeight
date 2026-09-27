"""Un module par levier câblé dans optimize.propose.propose(), en plus des trois historiques
(_rules, _model, _cap, restés dans optimize/propose.py). Séparés pour que chaque nouveau levier
ne touche que son propre fichier, jamais le dispatcher de optimize.propose au-delà d'une ligne
par levier (coordination avec les autres chantiers qui touchent aussi optimize/propose.py)."""
