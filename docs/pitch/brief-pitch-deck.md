# Brief pour générer le pitch deck Deadweight

> **Mode d'emploi** : copier tout ce fichier dans une conversation avec Claude, avec la demande :
> « Fais-moi deux pitch decks à partir de ce brief : un pour le décideur, un pour le développeur. »
> Chaque chiffre ci-dessous porte son statut. **Ne pas en inventer d'autres, ne pas les arrondir pour faire joli.**

---

## 1. Le produit en une phrase

**Deadweight se branche sur n'importe quel workflow d'agents IA, trouve ce qui coûte sans servir, prouve chaque
amélioration sur le vrai historique du client, puis la livre sous forme d'une petite PR à accepter.** Tout tourne
chez le client.

La question qu'on pose, et que personne d'autre ne pose : **« Est-ce que ça avait besoin d'être un agent ? Un gros
modèle ? Tout ce contexte ? »**

## 2. Le problème

- Les entreprises mettent des agents IA en production (n8n, code maison, Claude Code, LangChain…). La facture monte,
  et personne ne sait quels appels servent vraiment.
- Beaucoup d'appels à un gros modèle ne « réfléchissent » pas : ils **aiguillent** (trier un mail en spam, facture,
  support). Un modèle facturé au prix du raisonnement pour faire un `switch`.
- Sur les agents de code, **relire le contexte coûte plus que le travail lui-même** (mesuré, voir §5).
- Les outils existants **mesurent** (observabilité) ou **routent** (passerelles), mais aucun ne **prouve**, avant de
  changer quoi que ce soit, que la version moins chère donne les mêmes réponses sur les cas réels du client.

## 3. La solution, en quatre temps

1. **Se brancher** en 10 minutes, sans rien casser : changer une ligne (`base_url`) dans l'application, ou importer
   l'existant (historique n8n, traces OpenTelemetry, journaux Claude Code et Codex). Les clés sont relayées, jamais
   stockées.
2. **Détecter** : 20 vérifications (modèle trop gros, IA qui ne fait qu'aiguiller, contexte relu à chaque appel,
   cache non utilisé, boucles, appels payés deux fois, données qui partent hors d'Europe…).
3. **Prouver** sur le vrai historique : **rejeu** (on rejoue les appels passés avec la modification et on compare aux
   anciennes réponses, seuil 95 %) et **banc de modèles** (on teste un modèle plus petit, local ou européen sur les
   vraies entrées). Un refus est un résultat : on ne propose pas ce qui n'est pas prouvé.
4. **Livrer** : une petite PR par amélioration, relue par un humain ; un message Slack qui ne montre **que les gains
   prouvés** ; un rapport d'une page ; une page développeur qui montre tout, y compris les échecs.

**L'agent auditeur** (condition du hackathon : un vrai projet agentique) mène l'enquête : il regarde le trafic, choisit
quoi prouver en premier (le plus cher), lance les preuves, lit les verdicts, et rédige un plan d'action. **Il ne peut
citer aucun chiffre qui ne sort pas de nos outils** : un garde-fou le vérifie automatiquement.

## 4. Les deux users (une présentation chacun)

### User 1 — Le décideur (CTO, dirigeant, responsable financier d'une PME ou scale-up)

| | |
|---|---|
| Sa situation | Des agents IA en production, une facture OpenAI / Anthropic qui grimpe, pas de visibilité sur ce qui sert. |
| Sa question | « Combien je peux économiser, **sans risque pour la qualité** ? » |
| Ce qu'il voit | Le **rapport d'une page** et un **message Slack** avec uniquement les gains prouvés, chacun activable en acceptant une PR. |
| Ses objections | « Et si la qualité baisse ? » → tout est prouvé sur son propre historique avant d'être proposé. « Mes données ? » → tout tourne chez lui. |
| Options qui parlent | **RGPD** : Deadweight documente les flux pour le DPO. **Souveraineté** (en option) : chaque appel est rattaché à sa destination réelle, avec une alternative européenne. |
| Ton | Business, chiffres, zéro jargon (pas de « tokens », « p95 », « prompt »). |

### User 2 — Le développeur (dev, ops, responsable automatisation qui maintient les workflows)

| | |
|---|---|
| Sa situation | On lui demande de réduire les coûts IA sans rien casser. Il n'a pas le temps d'évaluer chaque modèle à la main. |
| Sa question | « Qu'est-ce que je change exactement, et comment je sais que ça marche ? » |
| Ce qu'il voit | La **page développeur** (tout, y compris ce qui a échoué et pourquoi), des **micro-PR testées**, les verdicts du rejeu et du banc. |
| Ce qui le convainc | Installation en une commande ; une ligne à changer ; ça lit ce qu'il utilise déjà (n8n, OpenTelemetry, Claude Code, Codex) ; tout est local ; chaque chiffre porte son statut (mesuré, estimé, non testé). |
| Ton | Technique mais concret : montrer la PR, le verdict, la commande. |

## 5. Les preuves (ce qu'on peut montrer)

**Sur de vrais workflows** (mesuré) :

| Workflow | Ce que Deadweight a trouvé |
|---|---|
| Claude Code d'un membre de l'équipe (6 049 appels, 24 jours) | **72 % du coût = relire le contexte** ; 59 000 jetons envoyés dès le premier appel |
| Usine de vidéos courtes d'un tiers (12 vidéos) | **7,21 $ par vidéo** ; les agents auteurs relisent 180 000 jetons par tour (**62 à 74 % de leur coût**) |
| Plugin claude-mem (2 652 appels) | **+43 % d'appels cachés** |
| Récap Gmail (88 vrais appels, via la passerelle) | le tri des mails est un simple aiguillage |
| Exemple officiel OpenAI de triage (54 appels) | **rien à optimiser, et c'est juste : aucun faux positif** (argument d'honnêteté) |
| Modèle n8n de tri d'emails | **98 % des appels du workflow compris** à l'import |

**Sur le jeu de test** (mesuré, données synthétiques réalistes) :
- Tri des mails : **−72 % de coût à 100 % de précision** avec des règles extraites et prouvées par rejeu.
- Court-circuit par la passerelle : réponse en **0,24 ms au lieu de 764 ms** pour les appels remplacés par des règles.
- **Le banc qui démonte une fausse bonne idée** : passer de gpt-4o à gpt-5-nano semblait **×45 moins cher** sur le
  papier. Mesuré sur 40 vraies requêtes : **×1,5 seulement, et 5 fois plus lent**, parce que ce modèle facture sa
  réflexion invisible. Sans preuve, on aurait recommandé un faux gain. *(C'est l'image la plus forte du pitch.)*

**Le travail du week-end** (mesuré, historique git) : 105 commits entre le 26/09 et le 27/09 ; 63 PR fusionnées le
26/09 ; 20 vérifications ; plus de 450 tests ; intégration continue de bout en bout.

## 6. La différence avec le marché

| Ils font… | Exemples | Deadweight |
|---|---|---|
| Mesurer (observabilité) | Langfuse, Helicone | mesure **et** prouve la correction |
| Router le futur trafic | LiteLLM, Portkey, OpenRouter | analyse l'**historique réel** avant de changer quoi que ce soit |
| Choisir le modèle à chaque appel sur un score générique | Not Diamond, Martian | prouve sur **les cas du client**, pas sur un score générique |
| Appliquer en configuration | la plupart | livre une **PR relue par un humain** |
| SaaS hébergé | la plupart | **100 % local** chez le client |

**À positionner en complémentarité, pas en remplacement** : ces outils répondent à un vrai besoin (router, observer
en continu). Deadweight répond à une autre question.

## 7. L'équipe

Quatre personnes : **Hugo Gesland, Natan, Thibaud Gregori, Alexandre Zenou**, avec des agents de code (Claude Code,
Codex) coordonnés par des règles écrites (`AGENTS.md`).

**Existant déclaré** (règlement X-IA) : un prototype d'un après-midi du 12/09/2026, limité à n8n (détection par
entropie, rejeu sur l'historique n8n, patch du workflow). **Tout le reste a été construit pendant le hackathon.**

## 8. Critères du jury X-IA (à respecter dans l'ordre des slides)

30 % impact et utilité · 20 % innovation · 20 % qualité · 15 % expérience utilisateur · 15 % clarté de la démo et du
pitch. Vidéo de **2 minutes maximum**. Le projet doit être **agentique** : montrer l'agent auditeur.

## 9. À ne PAS dire (règles de l'équipe)

- ❌ « Deadweight vous rend conforme RGPD » → ✅ « Deadweight documente vos flux pour votre DPO ».
- ❌ Un chiffre de CO₂ évité sans source ni fourchette → ✅ « un appel remplacé par une règle ne consomme plus rien ».
- ❌ Un gain de latence sans dire lequel (la médiane et les cas les plus lents ne bougent pas pareil).
- ❌ « 50 à 90 % de gaspillage » comme un fait → ce sont des ordres de grandeur de blogs commerciaux.
- ❌ Dire que les concurrents « ne servent à rien ».
- ❌ La valorisation de Martian (rumeur non confirmée).
- Chiffres de marché **à vérifier sur la source primaire avant usage** : dépense API LLM d'entreprise 3,5 Md$ fin 2024
  → 8,4 Md$ mi-2025 (Menlo Ventures, cité par CloudZero) ; 79 % des entreprises ont dépassé leur budget IA (sondage
  2026, 500 décideurs financiers US/UK).

## 10. Plan des deux decks (8 à 10 slides chacun)

| # | Deck « Décideur » | Deck « Développeur » |
|---|---|---|
| 1 | Titre + la question « Fallait-il un agent ? » | Titre + « Prouvé sur votre historique, livré en PR » |
| 2 | Le problème : la facture monte, personne ne sait ce qui sert | Le problème : réduire les coûts sans rien casser, sans temps pour évaluer |
| 3 | Un exemple qui parle : le tri de mails facturé au prix du raisonnement | Un exemple qui parle : 72 % du coût d'un agent de code = relire le contexte |
| 4 | La solution en 4 temps (se brancher, détecter, prouver, livrer) | Comment ça se branche : `base_url`, OpenTelemetry, n8n, Claude Code / Codex |
| 5 | **La preuve** : le banc (×45 promis, ×1,5 réel) | **La preuve** : rejeu (seuil 95 %) et banc, un refus est un résultat |
| 6 | Ce que vous recevez : message Slack des seuls gains prouvés + rapport d'une page | Ce que vous recevez : page développeur + micro-PR testée (montrer une PR) |
| 7 | Vos données restent chez vous ; RGPD et souveraineté en option | Tout est local ; clés jamais stockées ; chaque chiffre a son statut |
| 8 | L'agent auditeur mène l'enquête (et ne peut pas inventer un chiffre) | L'agent auditeur : outils, garde-fou sur les chiffres, journal |
| 9 | Résultats sur de vrais workflows | Résultats sur de vrais workflows, y compris « rien à optimiser » |
| 10 | Différence avec le marché + équipe | Différence avec le marché + équipe + « construit ce week-end » |

## 11. Direction visuelle

- Épuré : **un message et un chiffre par slide**, peu de texte.
- Chaque chiffre avec sa petite étiquette de statut : **mesuré**, **jeu de test**, **estimé**.
- Slide 5 (la preuve) en point d'orgue visuel : deux barres, « promis ×45 » et « mesuré ×1,5 ».
- Pour le décideur : visuels business (message Slack, rapport). Pour le développeur : captures techniques (PR, terminal).
- Langue : français.
