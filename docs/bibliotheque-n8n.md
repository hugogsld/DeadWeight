# Workflows n8n en mémoire pour les tests

Les **1 000 workflows les plus consultés de la catégorie AI** de la bibliothèque publique n8n.io, relevés
le 26/09/2026. Ils servent à vérifier que notre lecture des workflows n8n (nœuds d'IA, fournisseur,
modèle) tient sur des cas réels, pas seulement sur nos exemples.

- **La liste** : [`bibliotheque-n8n.csv`](bibliotheque-n8n.csv), une ligne par workflow, triée par vues :
  identifiant, nom, vues, lien n8n.io, nombre de nœuds, nœuds LLM, fournisseurs appelés, modèles lus.
- **Les workflows eux-mêmes ne sont pas dans le repo** : ils appartiennent à leurs auteurs. Chacun les
  récupère chez lui, dans `private/n8n-library/` (ignoré par git), en quatre minutes et sans clé :

      python3 -m importers.n8n library fetch --limit 1000
      python3 -m importers.n8n library coverage

  La bibliothèque bouge : relancé plus tard, `fetch` prend les 1 000 plus consultés du moment, pas
  forcément les mêmes. La liste ci-dessus fige ceux du 26/09.

Ce ne sont que des workflows, **sans historique d'exécution** : ils testent la lecture de la structure
(quels nœuds, quel modèle), pas celle des jetons ou des prompts réels. Pour ça : l'historique d'un vrai
client (`importers.n8n fetch`).

## Ce qu'ils contiennent

| | |
|---|---|
| Workflows | 999 (un retiré de la bibliothèque) |
| Avec au moins un nœud LLM | 823 |
| Nœuds LLM | 1 554 : 485 workflows en ont un, 170 deux, 168 trois ou plus |
| Vues | de 1 272 à 1 827 224, médiane 7 696 |

Fournisseurs appelés (nombre de workflows) : OpenAI 596, Gemini 146, OpenRouter 56, Anthropic 34,
Ollama 16, Groq 14, DeepSeek 9, Azure OpenAI 8, Mistral 7, Perplexity 4, Hugging Face 2, xAI 1.

Modèles les plus fréquents (nœuds) : gpt-4o-mini 341, gpt-4o 111, gemini-2.0-flash 53,
gemini-2.0-flash-exp 49, gpt-4.1-mini 42, gpt-4.1 24, gemini-1.5-flash 18, gpt-3.5-turbo 12,
claude-3-7-sonnet 11, gpt-4.1-nano 11.

## Ce que notre code en lit

| | |
|---|---|
| Fournisseur reconnu | 100 % des nœuds LLM |
| Modèle lu dans le workflow | 61 % |
| Modèle laissé au réglage par défaut | 568 nœuds |
| Modèle écrit en formule n8n | 35 |
| Modèle introuvable | 2 (champ vide : l'auteur n'a pas choisi de modèle) |

**Le réglage par défaut n'est pas écrit dans le workflow**, et ce défaut change selon la version de n8n
installée (pour le même nœud « OpenAI Chat Model » : `gpt-4o-mini`, puis `gpt-5-mini`). On ne le devine
donc pas. Sans effet sur un audit : à l'exécution, n8n enregistre le modèle réellement utilisé, et
l'import d'historique le lit en premier.

**Exclus, car ce ne sont pas des appels de modèle de langage** (facturés autrement) : génération
d'images (61), transcription et audio (47), vidéo (11), fichiers (3), lecture de documents par OCR (2).

Trous trouvés grâce à cette liste, puis corrigés : le nœud Perplexity, Hugging Face, le fournisseur des
nœuds qui appellent directement Gemini ou Anthropic, les usages image, audio et vidéo comptés à tort, et
deux faux positifs (`chat`, la fenêtre de discussion, et `modelSelector`). Les 26 façons d'écrire le
modèle observées (type de nœud × version × champ) sont figées dans `tests/test_n8n_library.py`.

## Pour aller plus loin

- La catégorie AI compte 8 691 workflows : `fetch --limit 9000` (environ 30 minutes) pour les cas rares.
- Refaire `coverage` après chaque changement de `importers/n8n/` : un pourcentage qui baisse signale
  une régression.
