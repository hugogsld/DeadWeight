# Premier banc réel (M2.2) — 26/09/2026

Les options que M2 recommande pour les deux constats « modèle trop gros » du jeu D0.3, testées sur
40 requêtes réelles chacune via OpenRouter (`python -m bench m2`). Coût total du banc : environ 0,01 $.
Le jeu D0.3 est synthétique : les requêtes sont réalistes, les réponses de référence générées.

| Constat | Option | Accord | Économie mesurée | Estimation M2 | Verdict |
|---|---|---|---|---|---|
| mail-triage (gpt-4o) | gpt-5-nano via OpenAI | 100 % | ×1,5 | ×44,8 | validé |
| mail-triage | mistral-nemo (hébergeur le moins cher) | 10 % | ×83 | ×141 | refusé |
| reviews (claude-opus-4-1) | claude-haiku-4.5 via Anthropic | 95 % | ×15,3 | ×15,0 | validé |
| reviews | mistral-nemo (hébergeur le moins cher) | 95 % | ×2 100 environ | ×962 | validé |

Ce que ce banc a montré :

- **Un modèle à raisonnement facture sa réflexion.** gpt-5-nano trie parfaitement, mais ses jetons de
  réflexion ramènent l'économie estimée de ×44,8 à ×1,5 mesuré. Sans banc, on aurait recommandé un faux gain.
- **Le format compte.** mistral-nemo répond « Etiquette: Spam » au lieu de « spam », en plus de vraies
  erreurs de tri : il ne remplace pas gpt-4o tel quel.
- **Les options souveraines n'ont pas été testées** : sur OpenRouter, la route Mistral est une route UE
  avec supplément régional (`mistral/eu`), filtrée sur un compte sans crédit.

Les facteurs viennent de `bench.pricing.cost_per_1000_calls`, arrondi à 4 décimales : pour un modèle très
bon marché (mistral-nemo), le facteur est approximatif.

Reproduire (clé dans `.env.local`, jamais dans le repo) :

    python -m bench m2 fixtures/dataset/v1/events.jsonl --finding f_mail-triage_cc8b13da25_oversized \
        --options moins_cher,meilleur_compromis --max-cases 40 --max-calls 40 --min-interval 3.2
    python -m report.audit fixtures/dataset/v1/events.jsonl --banc docs/banc

`--min-interval 3.2` : un compte OpenRouter récent est limité à 20 requêtes par minute et par modèle.
