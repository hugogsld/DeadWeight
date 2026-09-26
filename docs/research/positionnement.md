# Recherche positionnement : RGPD, souveraineté, écologie, efficacité

> **À lire avant de citer quoi que ce soit** : recherche web du 26/09/2026. Les faits juridiques les plus récents (arrêt *Trump v. Slaughter* du 29/06/2026, courrier noyb du 30/06/2026, qualification SecNumCloud d'OVHcloud au 01/09/2026, Cloud and AI Development Act du 03/06/2026) et les statistiques de marché viennent en partie de sources secondaires : **à vérifier sur la source primaire avant tout usage dans le pitch ou devant un client**. Les pièges à éviter de chaque section font partie du résultat.

---

## 1. RGPD / vie privée

### Faits clés (sourcés)

- **Tout prompt contenant une donnée personnelle (nom, email, n° client) est un traitement RGPD**, y compris
  à l'inférence — pas seulement à l'entraînement. Position confirmée par les fiches pratiques IA de la CNIL
  (13 fiches, dont une dédiée à la qualification responsable/sous-traitant/responsable conjoint d'un
  fournisseur d'IA). Source : [CNIL — Les fiches pratiques IA](https://www.cnil.fr/fr/les-fiches-pratiques-ia) ;
  [CNIL — Développement des systèmes d'IA : recommandations pour respecter le RGPD](https://www.cnil.fr/fr/developpement-des-systemes-dia-les-recommandations-de-la-cnil-pour-respecter-le-rgpd).
- **Base légale** : la CNIL admet l'intérêt légitime comme base possible (surtout pour l'entraînement sur
  données publiques), sous réserve d'une mise en balance rigoureuse et de garanties. Pour un usage
  professionnel « prompt → fournisseur LLM », la base la plus courante en pratique reste l'exécution du
  contrat ou l'intérêt légitime de l'entreprise cliente, à documenter au cas par cas — non trouvé de position
  CNIL générique unique pour ce cas précis (à traiter au cas par cas selon le contexte du client).
- **Minimisation** : la CNIL recommande explicitement l'anonymisation ou l'usage de données synthétiques
  quand elles donnent des résultats comparables, et de limiter le traitement au strict nécessaire. C'est un
  principe directement invocable par Deadweight.
- **AIPD (analyse d'impact)** obligatoire pour les traitements à risque élevé (RH, santé, scoring, décision
  automatisée, évaluation systématique de personnes) — pas systématique pour tout usage de LLM, mais
  fréquente dès qu'il y a profilage ou volume important.
- **Qualification du fournisseur** : la CNIL a une fiche dédiée pour déterminer si le fournisseur d'IA est
  sous-traitant, responsable conjoint ou responsable de traitement — point clé pour savoir si un DPA
  classique (art. 28 RGPD) suffit ou s'il faut un accord de responsabilité conjointe.
- **Sous-traitants publiés** : OpenAI et Anthropic publient tous deux une liste de sous-traitants (subprocessors).
  OpenAI : page officielle `openai.com/policies/sub-processor-list/` (non accessible en lecture directe pendant
  cette recherche — 403 — à revérifier avant publication finale, contenu non confirmé de première main).
  Anthropic : liste disponible dans son Trust Center (`trust.anthropic.com`), avec ajout documenté de
  Microsoft Azure comme sous-traitant depuis le 2026-01-07 pour les intégrations Microsoft Foundry/Copilot.
  Sources : [OpenAI sub-processor list](https://openai.com/policies/sub-processor-list/) ;
  [Anthropic Trust Center](https://trust.anthropic.com/) ; [CompanyScope — Anthropic DPA review](https://companyscope.io/vendors/anthropic).
- **Transferts hors UE / EU-US Data Privacy Framework (DPF)** : la décision d'adéquation de 2023 reste
  valide au 26/09/2026. Le Tribunal de l'UE a rejeté le recours Latombe en septembre 2025 et confirmé la
  validité du DPF *au regard de la situation de fait et de droit de 2023* — un pourvoi est pendant devant la
  CJUE (affaire C-703/25 P). Un nouveau risque est apparu en juin 2026 : la Cour suprême américaine (arrêt
  *Trump v. Slaughter*, 29 juin 2026) a jugé inconstitutionnelles les protections d'indépendance des
  commissaires de la FTC ; l'association noyb (Max Schrems) argue dans un courrier du 30 juin 2026 que cela
  fragilise un pilier de l'adéquation (indépendance de l'autorité de recours américaine), ouvrant la voie à
  un potentiel « Schrems III ». **Statut au 26/09/2026 : le DPF est en vigueur et juridiquement valide, mais
  contesté et fragile — à traiter comme un risque documenté, pas comme une garantie définitive.**
  Sources : [IAPP — Schrems on the DPF](https://iapp.org/news/a/schrems-addresses-emerging-questions-around-eu-us-data-privacy-framework) ;
  [activeMind.legal — DPF at risk following Supreme Court ruling](https://www.activemind.legal/guides/dpf-supreme-court/) ;
  [Passcreator — Schrems III 2026](https://www.passcreator.com/en/blog/schrems-iii-2026-is-your-data-in-the-us-cloud-still-secure).
- **AI Act — obligations des déployeurs en 2026** : l'essentiel des obligations restantes entre en
  application le **2 août 2026**. Un déployeur (l'entreprise qui utilise un système d'IA à titre
  professionnel, par opposition à l'utilisateur final) a des obligations **seulement s'il déploie un système
  à haut risque** (supervision humaine, respect des instructions du fournisseur, tenue de logs) — une
  entreprise qui appelle simplement l'API d'un modèle GPAI (GPT, Claude, Gemini, Mistral) dans un outil
  interne non classé « haut risque » n'a en général pas ces obligations lourdes. En revanche, **l'article 50
  (transparence)** s'applique plus largement dès le 2 août 2026 : informer les utilisateurs finaux qu'ils
  interagissent avec une IA (chatbots) et étiqueter le contenu généré/synthétique dans certains cas. Les
  obligations les plus lourdes sur les modèles GPAI eux-mêmes (documentation technique, gestion du risque
  systémique) pèsent sur le **fournisseur du modèle** (OpenAI, Anthropic, Mistral...), pas sur le client qui
  l'utilise via API. Sources : [DLA Piper — Deployer obligations under the AI Act](https://knowledge.dlapiper.com/dlapiperknowledge/globalemploymentlatestdevelopments/2026/deployer-obligations-under-the-ai-act-implications-for-employers-from-2-august-2026) ;
  [artificialintelligenceact.eu — High-level summary](https://artificialintelligenceact.eu/high-level-summary/) ;
  [Orrick — 6 Steps Before 2 August 2026](https://www.orrick.com/en/Insights/2025/11/The-EU-AI-Act-6-Steps-to-Take-Before-2-August-2026).

### Ce que Deadweight peut documenter pour un DPO client

- **Registre des traitements** : pour chaque appel LLM détecté par l'audit, Deadweight peut lister le
  fournisseur appelé, le modèle, et (si niveau 2 « contenu ») si des données personnelles semblent présentes
  dans le prompt (heuristique, pas une garantie de détection exhaustive).
- **Cartographie des flux de données** : quel fournisseur, quelle région d'hébergement quand elle est
  documentée (ex. `eu.api.openai.com`, régions Vertex AI europe-west, absence de résidence UE native chez
  Anthropic en API directe — cf. `docs/research/modeles.md`), et donc quels flux sortent de l'UE.
- **Durée de conservation** : à documenter *fournisseur par fournisseur* d'après leurs propres politiques
  (Deadweight n'a pas de visibilité directe sur la rétention côté fournisseur — seulement sur ce que le
  client lui-même conserve dans son historique n8n/OTel/logs).
- **Sous-traitants** : renvoyer vers les pages officielles de sous-traitants de chaque fournisseur (cf.
  ci-dessus) plutôt que de les recopier, car elles changent souvent.

### Ce qui ferait de Deadweight un outil « privacy by design »

- Traitement local : l'analyse tourne sur la machine du client, aucune clé API n'est lue ni stockée par
  Deadweight (déjà une règle du projet, cf. `docs/analyser-un-workflow.md` — « contrat d'un connecteur »).
  C'est un vrai argument défendable : Deadweight lui-même n'est pas un nouveau sous-traitant RGPD pour les
  contenus, puisqu'il ne les fait pas transiter par ses propres serveurs.
- Anonymisation/purge : à construire — non trouvé de preuve dans le repo qu'un mécanisme de purge ou
  d'anonymisation du contenu (niveau 2) est déjà implémenté. C'est un chantier, pas un acquis.
- Minimisation : le mode « niveau 1 usage seul » (pas de contenu) est déjà, par construction, une forme de
  minimisation — argument honnête et déjà vrai aujourd'hui selon la doc du repo.

### Pièges à éviter

- Ne jamais dire « Deadweight est conforme RGPD » de façon générale — la conformité dépend du traitement du
  *client*, pas de l'outil. Dire plutôt : « Deadweight documente les flux pour que le DPO du client puisse
  évaluer sa conformité ».
- Ne pas affirmer que passer par la passerelle Deadweight supprime une obligation de DPA avec OpenAI/Anthropic
  — ces obligations restent, Deadweight ne se substitue pas à un accord contractuel avec le fournisseur du
  modèle.
- Ne pas présenter le DPF comme une garantie inattaquable de transfert : au 26/09/2026 il est valide mais
  contesté (pourvoi CJUE pendant, risque « Schrems III » documenté par noyb depuis le 30/06/2026). Formuler
  en « transfert actuellement licite sous le DPF, à surveiller ».
- Ne pas confondre obligations du *fournisseur* de GPAI (OpenAI, Anthropic, Mistral) et obligations du
  *déployeur* (le client) — la plupart des obligations lourdes de l'AI Act 2026 pèsent sur le fournisseur.

---

## 2. Souveraineté

### Faits clés (sourcés)

- **Résidence UE par fournisseur** (repris et confirmé de `docs/research/modeles.md`, avec vérification
  croisée cette session) :
  - OpenAI : résidence de données UE native disponible (`eu.api.openai.com`) depuis 2025, extension du
    calcul en Europe début 2026.
  - Anthropic : **pas de résidence UE en API directe** — tout appel à `api.anthropic.com` est traité aux
    US quel que soit le pays du client. Option UE uniquement via AWS Bedrock (Francfort, Irlande, Paris,
    Stockholm) ou Google Vertex AI.
  - Google Gemini : résidence UE mature (europe-west1 Belgique, europe-west4 Pays-Bas, europe-north1
    Finlande, europe-west3 Francfort).
  - Mistral AI : nativement français/UE, y compris hébergement via Scaleway/OVHcloud pour un besoin de
    souveraineté renforcée.
- **SecNumCloud (ANSSI)** — qualification française, gage le plus élevé de souveraineté d'hébergement en
  France (référentiel technique + exigence de capital/gouvernance non soumise à des lois extraterritoriales
  type CLOUD Act). État au 26/09/2026 :
  - **OVHcloud** : qualification SecNumCloud obtenue pour son offre **SNC Cloud Platform au 1er septembre
    2026** (3ᵉ qualification obtenue par OVHcloud après Bare Metal Pod et VMware on OVHcloud).
  - **Scaleway** : certifié HDS (hébergeur de données de santé) mais **qualification SecNumCloud en cours,
    pas encore obtenue** à cette date pour son offre IaaS généraliste — à vérifier au cas par cas selon
    l'offre exacte (Scaleway communique sur une « approche SecNumCloud » mais ce n'est pas une qualification
    ANSSI actée pour toutes ses offres).
  - Environ 9 prestataires qualifiés et une douzaine de candidatures en cours au 26/09/2026, incluant
    Outscale, OVHcloud, Oodrive, Cloud Temple, Worldline, Orange Business, S3NS.
  Sources : [OVHcloud — SecNumCloud qualification](https://corporate.ovhcloud.com/en/newsroom/news/ovhcloud-obtains-secnumcloud-qualification-snc-cloud-platform/) ;
  [ANSSI — Prestataires SecNumCloud](https://cyber.gouv.fr/offre-de-service/solutions-certifiees-et-qualifiees/services-de-securite-evalue/solutions-en-cours-de-qualification/prestataires-secnumcloud/) ;
  [Scaleway — Sovereign cloud SecNumCloud approach](https://www.scaleway.com/en/security-and-compliance/secnumcloud/) ;
  [Code Confiance — état 2026](https://www.codeconfiance.com/2026/04/03/secnumcloud-2026-qui-est-deja-qualifie-qui-est-encore-en-attente/) (agrégateur, non ANSSI direct — à recouper).
- **« Cloud de confiance »** (label français, ex. S3NS de Thales/Google, Bleu de Capgemini/Orange/Microsoft)
  : concept français d'hébergement local avec licence technologique étrangère mais gouvernance et capital
  français/européens — distinct de SecNumCloud (qui est une qualification technique ANSSI), souvent utilisé
  en complément pour les appels d'offres publics sensibles. Non approfondi en détail dans cette recherche —
  **non trouvé** de fiche officielle comparant précisément « cloud de confiance » vs SecNumCloud pour du
  LLM as-a-service en date de septembre 2026 ; à creuser si un client public/santé est visé.
- **CLOUD Act** : s'applique dès qu'une entité américaine (société mère ou filiale) contrôle
  l'infrastructure, **indépendamment du pays où sont physiquement stockées les données**. C'est le point clé
  : héberger chez une filiale européenne d'un cloud américain (AWS Europe, Azure Europe, GCP Europe) ne met
  pas à l'abri du CLOUD Act — seule une entité réellement non soumise au droit américain (pas de maison mère
  US, pas de licence technologique US critique) protège complètement. La Commission européenne a présenté le
  **Cloud and AI Development Act** le 3 juin 2026, avec un cadre à 4 niveaux de souveraineté (de la simple
  localisation UE jusqu'au contrôle capitalistique européen complet et absence d'ingérence d'un État tiers)
  — c'est une réponse politique directe à ce problème, encore en cours d'élaboration au 26/09/2026 (à
  vérifier l'état d'adoption avant de s'en servir comme argument commercial ferme).
  Sources : [Numspot — Cloud Act vs RGPD](https://numspot.com/ressource/cloud-act-patriot-act-vs-rgpd-que-faut-il-retenir/) ;
  [Kiteworks — EU Data Act vs CLOUD Act](https://www.kiteworks.com/fr/conformite-rgpd/eu-data-act-rgpd-conflit-cloud/) (à recouper, sources majoritairement des cabinets de conseil/éditeurs, pas des textes officiels — le texte du Cloud and AI Development Act lui-même n'a pas été lu directement dans cette recherche).
- **Modèles ouverts exécutables localement (Ollama)** : les modèles cités dans `docs/research/modeles.md`
  comme alternatives « poids ouverts » (Llama 3.3 70B, Qwen, DeepSeek) sont compatibles Ollama pour de
  l'exécution locale. Pour des tâches de classification/extraction simples, la littérature interne du projet
  (cf. section 2 de `modeles.md`) recommande de préférer règles > classifieur fine-tuné > embeddings+kNN >
  petit LLM local avant même d'envisager un LLM cloud — **non trouvé** dans cette recherche de benchmark
  chiffré et récent (< 2 ans) comparant précisément la qualité d'un Llama 3.x 8B/70B local via Ollama vs GPT
  nano/mini sur une tâche de classification métier type — à traiter comme une hypothèse raisonnable, pas un
  fait démontré, tant que Deadweight n'a pas fait tourner son propre banc de test.

### Ce que Deadweight peut affirmer aujourd'hui

- « On sait dire, fournisseur par fournisseur, si vos appels LLM sont traités et stockés en UE ou aux
  US » — vrai, la matrice existe déjà dans `docs/research/modeles.md`.
- « Anthropic (Claude) n'offre aujourd'hui aucune résidence UE en API directe » — fait vérifiable,
  argument fort et différenciant si le client a un existant Claude.
- « Pour un besoin de souveraineté stricte (SecNumCloud), les options 2026 sont Scaleway/OVHcloud (poids
  ouverts hébergés en France) ou Mistral en direct » — vrai avec la nuance que Scaleway n'a pas encore la
  qualification SecNumCloud actée pour toutes ses offres au 26/09/2026 (à vérifier offre par offre avant de
  le garantir à un client).

### Ce qu'il faut construire/prouver pour aller plus loin

- Un vrai banc de test qualité (accuracy sur données réelles du client, rejoué) comparant un modèle cloud
  US et une alternative UE/locale sur la tâche précise auditée — c'est justement la promesse centrale de
  Deadweight (« on rejoue, on compare »), donc l'aligner explicitement avec l'argument souveraineté.
- Vérifier l'état d'adoption du Cloud and AI Development Act avant de le citer dans un pitch commercial —
  au 26/09/2026 c'est une proposition, pas un texte en vigueur (statut d'adoption non vérifié dans cette
  recherche).

### Pièges à éviter

- Ne pas dire « votre stack est souveraine » juste parce qu'un cloud américain a un datacenter en Europe —
  le CLOUD Act reste applicable via la maison mère, c'est un point juridique établi et cité par plusieurs
  cabinets de conseil.
- Ne pas présenter Scaleway comme « SecNumCloud qualifié » sans préciser l'offre exacte et la date — au
  26/09/2026 c'est en cours pour au moins une partie du catalogue, pas acquis partout.
- Ne pas garantir une qualité équivalente entre un petit modèle local (Ollama) et un modèle cloud sans
  l'avoir mesuré sur le cas du client — c'est un point à prouver par le rejeu, pas à affirmer a priori.

---

## 3. Écologie

### Faits clés (sourcés)

- **Mistral Large 2 — analyse de cycle de vie (LCA) publiée** (première LCA complète et publique d'un LLM,
  réalisée avec l'ADEME et le cabinet Carbone 4) : sur 18 mois d'utilisation (jusqu'à janvier 2025),
  empreinte totale de **20,4 kilotonnes de CO2e** et **281 000 m³ d'eau**. Pour un **prompt de 400 tokens**
  (~300 mots) : **1,14 g CO2e et 45 mL d'eau**. 85,5 % des émissions et 91 % de l'eau viennent de
  l'entraînement + l'inférence (pas de la fabrication du matériel). Source :
  [The Batch (DeepLearning.AI) — French AI Startup Discloses Full Lifecycle Consumption](https://www.deeplearning.ai/the-batch/french-ai-startup-discloses-full-lifecycle-consumption-and-emissions-for-mistral-large-2) ;
  [Hedgehog — Mistral LCA report](https://www.hhc.earth/knowledge-base/articles/french-ai-startup-discloses-full-lifecycle-consumption-and-emissions-for-mistral-large-2).
- **Google Gemini — chiffres officiels par prompt** (rapport du **21 août 2025**, méthodologie
  « comprehensive » incluant PUE, énergie des puces au repos, refroidissement) : **prompt texte médian =
  0,24 Wh, 0,03 gCO2e, 0,26 mL d'eau**. Amélioration de 33x en énergie et 44x en CO2 entre mai 2024 et mai
  2025 sur un prompt médian. Source : [Google Cloud Blog — Measuring the environmental impact of AI inference](https://cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference/) ;
  [MIT Technology Review — In a first, Google has released data](https://www.technologyreview.com/2025/08/21/1122288/google-gemini-ai-energy/).
  **Attention** : ces chiffres sont propres à l'infrastructure Google (TPU, PUE Google) et ne sont pas
  transposables tels quels à d'autres fournisseurs/modèles.
- **AI Energy Score (Hugging Face, Sasha Luccioni et al.)** : projet lancé en février 2025 (Sommet IA de
  Paris), méthodologie standardisée par matériel identique (mesure GPU via CodeCarbon), 166 modèles évalués
  sur 10 tâches. Constat marquant : **les modèles de raisonnement consomment en moyenne 30x plus d'énergie**
  que les modèles sans raisonnement (ou raisonnement désactivé) — donnée directement exploitable par
  Deadweight pour chiffrer le gaspillage d'un « raisonnement excessif » (levier R7 mentionné dans
  `docs/analyser-un-workflow.md`). Source : [Hugging Face — Announcing AI Energy Score](https://huggingface.co/blog/sasha/announcing-ai-energy-score) ;
  [Hugging Face — AI Energy Score v2](https://huggingface.co/blog/sasha/ai-energy-score-v2) ;
  [MIT Technology Review — Everything you need to know about estimating AI's energy burden](https://www.technologyreview.com/2025/05/20/1116331/ai-energy-demand-methodology/).
- **EcoLogits (GenAI Impact, association française)** : bibliothèque open-source qui **estime** (et non
  mesure directement) l'empreinte carbone d'un appel LLM à partir de paramètres observables côté client
  (fournisseur, modèle, nombre de tokens, latence) combinés à des hypothèses sur le matériel, le PUE datacenter
  et le mix électrique régional. Indicateurs produits : énergie (kWh), GWP (kgCO2e), eau (L), ADP (kgSbEq).
  C'est l'outil le plus directement réutilisable par Deadweight car conçu pour fonctionner **a posteriori,
  côté utilisateur d'API**, exactement le cas d'usage de Deadweight. Sources : [GitHub — mlco2/ecologits-calculator](https://github.com/mlco2/ecologits-calculator) ;
  [ecologits.ai — Environmental Impacts of LLM Inference (méthodologie)](https://ecologits.ai/0.4/methodology/llm_inference/) ;
  [Medium/Axionable — When every question counts](https://medium.com/axionable-ai-and-blockchain/when-every-question-counts-measuring-the-environmental-impact-of-llms-in-use-7e3532092231).
- **Cadres français/UE pertinents** : le **RGESN** (Référentiel Général d'Écoconception de Services
  Numériques, version finale mai 2024, DINUM/ADEME/Arcep/Arcom/CNIL/Inria, 78 critères en 8 familles)
  s'applique explicitement aux services numériques **incluant l'IA**. La **CSRD** impose depuis 2024-2025 un
  reporting de durabilité aux grandes entreprises, dans lequel le RGESN peut structurer le volet numérique.
  Source : [Numérique écoresponsable (DINUM) — RGESN](https://ecoresponsable.numerique.gouv.fr/publications/referentiel-general-ecoconception/) ;
  [Arcep — Référentiel général de l'écoconception](https://www.arcep.fr/mes-demarches-et-services/entreprises/fiches-pratiques/referentiel-general-ecoconception-services-numeriques.html).
  **Non trouvé** de critère RGESN chiffré spécifique à « nombre d'appels LLM » ou « choix du modèle » — le
  référentiel est généraliste sur l'écoconception numérique, pas un standard sectoriel IA à lui seul.

### Ordres de grandeur à retenir (avec fourchettes d'incertitude explicites)

| Source | Contexte mesuré | Énergie | CO2e | Incertitude |
|---|---|---|---|---|
| Google (comprehensive) | prompt texte médian Gemini, mai 2025 | 0,24 Wh | 0,03 g | méthodologie propriétaire Google, non auditée par un tiers indépendant |
| Google (non-comprehensive) | même prompt, méthode partielle | 0,10 Wh | 0,02 g | sous-estime volontairement (chiffre "plancher") |
| Mistral (LCA complète) | prompt 400 tokens, Large 2 | non détaillé en Wh dans les sources consultées | 1,14 g | LCA incluant fabrication matériel + entraînement amorti, donc non comparable brut à Google (scope différent) |
| Hugging Face AI Energy Score | reasoning vs non-reasoning | ratio ×30 (pas de valeur absolue universelle) | — | dépend du modèle et de la tâche, ordre de grandeur relatif seulement |

**So what méthodologique** : les chiffres de Google et de Mistral ne sont **pas directement comparables**
(scopes différents : Google mesure l'inférence de production à grande échelle sur son propre matériel,
Mistral amortit aussi l'entraînement et la fabrication). Deadweight doit toujours citer la source et le
scope exact quand il donne un chiffre de CO2/énergie « évité », et présenter une fourchette plutôt qu'un
chiffre unique quand il extrapole d'un fournisseur à un autre.

### Ce que Deadweight peut affirmer aujourd'hui

- « On peut estimer, via EcoLogits ou des ordres de grandeur publiés (Google, Mistral), l'énergie et le CO2
  évités par un appel économisé ou un modèle plus petit choisi — avec une fourchette et la source citée,
  pas un chiffre unique inventé. »
- « Le raisonnement inutile (chain-of-thought sur une tâche simple) coûte, selon Hugging Face AI Energy
  Score, en moyenne 30x plus d'énergie qu'un mode sans raisonnement — c'est un signal fort pour prioriser
  la règle R7 (raisonnement excessif) de l'audit. »

### Ce qu'il faut construire/prouver pour aller plus loin

- Intégrer EcoLogits (ou une méthode équivalente documentée) comme moteur de calcul dans le rapport
  Deadweight, plutôt que de citer des chiffres tiers de mémoire — c'est le seul moyen de donner un chiffre
  spécifique au client sans se référencer uniquement à Google/Mistral qui ne sont pas transposables.
- Documenter, pour chaque fournisseur réellement utilisé par les clients (OpenAI, Anthropic, Mistral,
  Groq...), quelle donnée énergétique existe ou n'existe pas — à ce stade, **seuls Google et Mistral
  publient des chiffres propres et sourcés** ; OpenAI et Anthropic n'ont pas publié de méthodologie
  équivalente trouvée dans cette recherche (non trouvé).

### Pièges à éviter

- Ne jamais donner un chiffre de CO2/énergie « évité » sans préciser la source et la méthodologie — les
  ordres de grandeur varient de 10x à 100x selon le scope (inférence seule vs cycle de vie complet).
- Ne pas comparer directement un chiffre Google (Gemini) à un chiffre Mistral (Large 2) comme s'ils
  mesuraient la même chose — le rappeler systématiquement dans le rapport client.
- Ne pas présenter le RGESN comme un « label IA » — c'est un référentiel généraliste d'écoconception
  numérique, pas un standard spécifique aux LLM.

---

## 4. Efficacité / marché

### Faits clés (sourcés)

- **Ampleur du gaspillage** : plusieurs sources concordent sur un ordre de grandeur de **50 à 90 % des
  coûts d'inférence évitables** via routing de modèle, cache sémantique et distillation, et **60 à 80 % des
  coûts concentrés sur 20 à 30 % des cas d'usage** — des tâches à fort volume et faible complexité qu'un
  modèle moins cher traiterait identiquement. Le choix par défaut d'un modèle frontière (ex. GPT-4o, Claude
  Sonnet) pour des tâches simples comme la classification d'intention ou le résumé est identifié comme
  **le principal poste de gaspillage**, représentant à lui seul environ un tiers ou plus des dépenses
  inutiles observées dans les audits. **Attention méthodologique** : ces chiffres proviennent de blogs
  d'éditeurs commerciaux (leanlm.ai, the-ai-corner.com) sans étude primaire citée en source — à traiter
  comme des ordres de grandeur indicatifs de l'industrie, pas des statistiques vérifiées par un tiers
  indépendant. Sources (à considérer comme indicatives) : [leanlm.ai — LLM Cost Optimization](https://leanlm.ai/blog/llm-cost-optimization) ;
  [the-ai-corner.com — Why Almost Every Company Is Overspending on AI in 2026](https://www.the-ai-corner.com/p/seven-deadly-sins-ai-spend).
- **Ampleur du marché et croissance** : la dépense API LLM d'entreprise est passée de **3,5 Md$ fin 2024 à
  8,4 Md$ mi-2025** (Menlo Ventures, cité par CloudZero), avec une projection à 15 Md$ en 2026. Un sondage
  2026 auprès de 500 décideurs financiers US/UK indique que **79 % des entreprises ont connu un dépassement
  budgétaire IA** dans l'année écoulée. Le rapport **Harness — 2026 State of AI in FinOps** (juillet 2026,
  700 praticiens/décideurs sur 5 pays) constate que la dépense IA a dépassé les capacités de gouvernance et
  de suivi mises en place. Sources : [CloudZero — 150+ AI statistics for 2026](https://www.cloudzero.com/blog/ai-statistics/) ;
  [PR Newswire — New Harness Report](https://www.prnewswire.com/news-releases/new-harness-report-reveals-enterprise-ai-spend-has-outgrown-the-systems-built-to-track-it-302837776.html).
- **Prompt caching, gain le plus documenté et le plus sûr à citer** : remises officielles publiées par les
  fournisseurs eux-mêmes (recoupé avec `docs/research/modeles.md`) — jusqu'à **90 % de remise sur cache hit
  chez Anthropic**, **50 à 80 % chez OpenAI** selon le modèle. Des cas concrets circulent (ex. un cache hit
  rate passé de 7 % à 84 % réduisant la dépense LLM totale de 59 à 70 % — cas non audité indépendamment,
  cité par un blog commercial, à traiter comme anecdote plutôt que statistique de marché) mais le mécanisme
  de remise lui-même est un **fait officiel vérifiable directement sur les pages pricing des fournisseurs**.
  Sources officielles déjà validées dans `docs/research/modeles.md` (OpenAI, Anthropic, Mistral, Google
  pricing/caching docs).
- **Paysage concurrentiel (gateways/observabilité/routers)** :
  - **LiteLLM** : gateway open-source auto-hébergé, fonctionnalités entreprise sous licence séparée,
    observabilité native limitée (s'appuie sur Langfuse/Helicone/Datadog en intégration).
  - **Portkey** : gateway managé, gateway open-sourcé sous Apache 2.0 en mars 2026, cache sémantique,
    garde-fous (PII, injection de prompt), observabilité poussée (traces, coût par route, latence).
  - **Helicone** : gateway léger, faible latence, mais en chemin synchrone (dépendance dure à leur edge).
  - **Langfuse** : traces/évaluations/gestion de prompts, open-source (cœur MIT), bon support Anthropic/OpenAI.
  - **OpenRouter** : agrégateur hébergé, 300-500+ modèles derrière une clé API unique, frais de plateforme
    ~5,5 % en sus du prix fournisseur.
  - **Not Diamond / Martian** : routers « intelligents » qui choisissent le modèle par requête selon un score
    de performance/coût appris — Martian valorisé ~1,3 Md$ en avril 2026 (rumeur de marché, non confirmée par
    un document officiel). Ces routers optimisent le choix de modèle **au moment de l'appel**, sur des règles
    apprises génériques.
  Sources (majoritairement blogs spécialisés/comparatifs 2026, à recouper avant citation ferme dans un
  pitch) : [Wavect — LLM Gateways Compared 2026](https://wavect.io/blog/llm-gateway-router-comparison-2026/) ;
  [Developers Digest — LLM Routers Compared 2026](https://www.developersdigest.tech/blog/llm-router-comparison-2026) ;
  [GitHub — Not-Diamond/awesome-ai-model-routing](https://github.com/Not-Diamond/awesome-ai-model-routing) ;
  [bestaiweb.ai — $3B LLM Router Race](https://www.bestaiweb.ai/openrouter-martian-and-not-diamond-the-2026-llm-router-race-and-where-agent-cost-optimization-is-heading/).

### Ce qu'aucun de ces outils ne fait (angle mort confirmé par la recherche)

D'après la description de leur fonctionnement dans les sources consultées, **aucun de ces outils ne rejoue
l'historique réel du client pour prouver, avant déploiement, qu'un modèle/config moins cher donne la même
réponse sur les cas réels déjà traités** :
- Les gateways (LiteLLM, Portkey, Helicone) optimisent le **futur trafic** (routing, cache, retries) — ils
  n'ont pas vocation à analyser un historique passé pour produire une preuve avant/après.
- Les routers apprenants (Not Diamond, Martian) décident **au moment de l'appel**, sur un modèle de scoring
  générique entraîné sur leurs propres données d'évaluation — pas sur l'historique spécifique et les
  standards de qualité du client audité.
- Aucun des outils identifiés ne livre le changement sous forme de **micro-PR revue par un humain** avant
  activation — ils appliquent le changement en configuration/infrastructure, pas en code review.
- Aucun n'est positionné comme **100 % local / sur le poste du client** avec relai de clé sans stockage —
  la plupart sont des SaaS hébergés (Portkey, Helicone, OpenRouter) ou nécessitent une infrastructure
  déployée (LiteLLM self-hosted reste un service qui tourne en continu, pas un audit ponctuel local).

C'est un point de différenciation réel et vérifié dans la recherche, mais **non trouvé** de source tierce
qui formule explicitement ce comparatif — c'est une synthèse de constat, pas une citation directe.

### Ce que Deadweight peut affirmer aujourd'hui

- « Le marché documente un gaspillage massif (ordres de grandeur 50-90 % évitables selon plusieurs analystes
  spécialisés, à recouper), concentré sur le sur-dimensionnement de modèle et le cache non activé — deux
  points que l'audit Deadweight détecte spécifiquement (règles R2 modèle trop gros, R4 cache non utilisé). »
- « Contrairement aux gateways et routers existants, Deadweight ne décide pas à la place du client en
  production — il prouve d'abord sur l'historique réel, puis livre une micro-PR relue par un humain. »

### Ce qu'il faut construire/prouver pour aller plus loin

- Chiffrer, sur au moins un cas client réel rejoué, le pourcentage de gaspillage détecté par Deadweight
  lui-même — remplacer les statistiques de marché génériques (peu fiables, sources commerciales) par une
  preuve propre dès que possible.
- Vérifier une à une les affirmations de fonctionnement des concurrents (LiteLLM, Portkey, etc.) sur leurs
  pages officielles avant de les citer nommément dans un pitch, les sources actuelles sont des comparatifs
  tiers de 2026, pas les pages produit elles-mêmes.

### Pièges à éviter

- Ne pas citer le chiffre « 50-90 % évitable » ou « 59-70 % de baisse via cache » comme une statistique de
  marché ferme — ce sont des ordres de grandeur ou des anecdotes de blogs commerciaux, pas des études
  indépendantes chiffrées et vérifiées.
- Ne pas affirmer que les gateways/routers concurrents « ne servent à rien » — ils répondent à un besoin
  réel (routing en production, observabilité continue) différent de celui de Deadweight (preuve ponctuelle
  sur historique + micro-PR). Positionner en complémentarité, pas en remplacement pur.
- Ne pas citer la valorisation de Martian (1,3 Md$) comme un fait établi — c'est une rumeur de marché non
  confirmée par un document officiel dans les sources consultées.

---

## Sources supplémentaires consultées mais non citées en détail ci-dessus

- [artificialintelligenceact.eu — High-level summary](https://artificialintelligenceact.eu/high-level-summary/) (fetch direct)
- [Google Cloud Blog — Measuring environmental impact of AI inference](https://cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference/) (fetch direct)
- [CNIL — Les fiches pratiques IA](https://www.cnil.fr/fr/les-fiches-pratiques-ia) (fetch direct)
- OpenAI sub-processor list : tentative de fetch direct en 403 (bloqué) — contenu rapporté uniquement via
  recherche web secondaire, **non vérifié de première main**, à revérifier avant de le citer précisément
  dans un document destiné à un DPO client.
