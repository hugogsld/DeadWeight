# Trois workflows où l'IA fait un travail qu'un code ferait

Trois workflows de la [bibliothèque n8n](bibliotheque-n8n.md), choisis parce qu'ils sont gros, très
consultés, et qu'une partie des appels à l'IA y fait un travail **déterministe** : recopier, calculer,
mettre en forme. Un bout de code le ferait gratuitement, sans erreur possible.

**Les montants sont des estimations.** Ces workflows n'ont pas d'historique d'exécution : les jetons
sont supposés (taille des consignes lue dans le workflow, taille des données devinée), les prix
viennent de `fixtures/pricing.json`. L'ordre de grandeur compte, pas le centime.

| | Workflow | Vues | Nœuds / appels IA | Gaspillage estimé |
|---|---|---|---|---|
| 1 | [3490](https://n8n.io/workflows/3490) Prospection LinkedIn avec score | 19 k | 96 / 7 | ~21 $ sur 23 $ pour 1 000 prospects (94 %) |
| 2 | [2783](https://n8n.io/workflows/2783) Rapport marketing hebdomadaire | 54 k | 51 / 5 | ~6 $ par an sur 6 $ (99 %) |
| 3 | [3791](https://n8n.io/workflows/3791) Prospects LinkedIn (Apollo) | 26 k | 66 / 5 | 0,03 $ pour 1 000 prospects, mais un appel IA par prospect pour rien |

## 1. [3490](https://n8n.io/workflows/3490) : prospection LinkedIn avec score

**Ce qu'il fait :** il cherche des prospects sur LinkedIn, résume leurs posts et ceux de leur
entreprise, puis donne une note d'intérêt de 1 à 10.

**Ce que l'IA fait pour rien :**

- **Un « répéteur ».** Un nœud a pour consigne *« repeat this sentence »*, avec le rôle
  *« You are repeater »*, et tourne sur gpt-4o. Il recopie mot pour mot la sortie de l'agent
  précédent. → **À supprimer** : on branche directement la sortie de l'agent. Environ 0,004 $ à
  chaque passage.
- **Trois résumés sur gpt-4o** pour chaque prospect (posts du prospect, actualités de l'entreprise,
  posts de l'entreprise), avec une consigne d'une ligne (*« Make summary of this text »*). → Un
  résumé court n'a pas besoin du plus gros modèle : **gpt-4o-mini**, 16 fois moins cher.
- **Une note de 1 à 10 sur gpt-4o.** Environ 1 500 jetons lus pour renvoyer un seul chiffre.
  → **gpt-4o-mini** suffit.

**Estimation pour 1 000 prospects :**

| | Par prospect | Pour 1 000 |
|---|---|---|
| Aujourd'hui (tout sur gpt-4o) | 0,023 $ | **23 $** |
| Résumés et note sur gpt-4o-mini | 0,0014 $ | **1,4 $** |

*Hypothèses : posts d'un prospect ≈ 2 000 jetons, actualités ≈ 800 jetons, résumé ≈ 250 jetons
en sortie.*

## 2. [2783](https://n8n.io/workflows/2783) : rapport marketing hebdomadaire

**Ce qu'il fait :** chaque lundi, il récupère les chiffres Google Analytics (5 sites), Google Ads
et Meta Ads, les compare à l'an dernier, puis envoie un rapport par e-mail et sur Telegram.

**Ce que l'IA fait pour rien :**

- **Remplir un tableau et calculer des pourcentages, 7 fois par semaine sur gpt-4o.** Les chiffres
  sont déjà calculés par le workflow et insérés dans la consigne. L'IA recopie les chiffres, calcule
  la variation en % et les écrit au format européen (`4.000`, `3,4 €`). → **Un code** fait le
  tableau et les % sans jamais se tromper. Seul le résumé de 3 phrases demande de l'IA.
- **Un agent qui assemble l'e-mail HTML.** Il appelle les 7 sous-workflows l'un après l'autre et
  relit tout le contexte à chaque tour, sur gpt-4o. → **Un modèle d'e-mail** (template) où l'on
  insère les 7 tableaux.
- **Convertir du HTML en texte pour Telegram**, sur gpt-4o-mini. → **Un code** qui retire les
  balises.

**Estimation :**

| | Par semaine | Par an |
|---|---|---|
| Aujourd'hui | 0,12 $ | **6,4 $** |
| Code + un seul résumé sur gpt-4o-mini | 0,0003 $ | **0,02 $** |

*Hypothèses : tableau ≈ 500 jetons lus, 400 écrits ; l'agent fait 8 tours et lit ≈ 24 000
jetons au total.*

**Le coût est faible, le vrai sujet est la fiabilité** : une IA qui recopie des chiffres et calcule
des % peut se tromper, et ce rapport sert à piloter un budget pub. Un code ne se trompe pas.

## 3. [3791](https://n8n.io/workflows/3791) : prospects LinkedIn (Apollo)

**Ce qu'il fait :** il trouve des prospects avec Apollo, récupère leur profil et leurs posts
LinkedIn, puis prépare des e-mails personnalisés.

**Ce que l'IA fait pour rien :**

- **Couper une adresse web.** Pour chaque prospect, gpt-3.5-turbo reçoit la consigne *« remove
  the http or https://www.linkedin.com/in/ from this »*. → **Une ligne de code** :
  `url.replace(/^https?:\/\/(www\.)?linkedin\.com\/in\//, '')`.

**Estimation :** environ 0,03 $ pour 1 000 prospects. Le coût est négligeable ; le problème, c'est
un appel réseau par prospect (lenteur, risque de panne, réponse parfois reformulée) pour une
opération qui prend une microseconde en code.

**C'est l'exemple le plus parlant pour une démo** : tout le monde comprend en 3 secondes qu'on n'a
pas besoin d'une IA pour couper le début d'une adresse.

## Ce qu'on en retient

- Le gaspillage en dollars vient surtout du **modèle trop gros** (n° 1) : c'est le levier
  [02](../leviers/02-modele-surdimensionne.md).
- Le travail déterministe confié à l'IA (n° 2 et 3) coûte souvent peu, mais il **rend le workflow
  plus lent et moins fiable**. Un appel à l'IA peut se tromper là où un code ne se trompe jamais.
