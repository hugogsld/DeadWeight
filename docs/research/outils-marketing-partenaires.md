# Recherche — Deadweight : workflows marketing, partenaires hackathon, sources publiques

Cadrage : quels outils non-LLM composent les workflows marketing IA, quelles metriques Deadweight peut capter, comment integrer chaque partenaire du hackathon en <0,5 jour, et ou trouver des workflows publics reels a auditer.

---

## 1. Workflows marketing IA typiques — outils chaines, pricing, latence, origine

| Workflow | Outil non-LLM | Fonction dans le flux | Pricing / credit | Latence typique | Origine | Alternative FR/EU ou moins chere |
|---|---|---|---|---|---|---|
| Lead enrichment | **Clay** | Orchestration + enrichissement multi-source (waterfall de providers) | Growth $495/mois + credits data ; Starter ~$67/1000 credits, tarif degressif jusqu'a $4.80/1000 credits en tier 4 (source : cleanlist.ai, devcommx.com, 2026) | Non publie (dependant du provider chaine) | US | — |
| Lead enrichment | **Apollo** | Base de contacts B2B, email/telephone | $49-$119/siege/mois annuel ; email = 2 credits, telephone = 8 credits (calculateur Apollo, 2026) | Non publie | US | Kaspr (FR), Dropcontact (FR) |
| Lead enrichment | **Dropcontact** | Verification/enrichissement email B2B, RGPD-friendly | Starter $45/mois (annuel) ou $59 (mensuel), emails B2B illimites + 1200 credits telephone/an (emelia.io, leadhaste.com, 2026) | Non publie | **FR** | — (deja l'alternative FR) |
| Lead enrichment | **Kaspr** | Emails/telephones directs, extension LinkedIn | Starter EUR59/mois (EUR45 annuel) ; emails generiques illimites mais 5 emails directs/mois inclus (derrick-app.com, 2026) | Non publie | **FR** | — |
| Scraping web | **Firecrawl** | Scrape/crawl/map pages en Markdown pret-LLM | 1 credit = 1 page, ~$0.0008/scrape a l'echelle ; recherche = 2 credits/10 resultats ; interaction navigateur = 2 credits/min ; Standard 100k credits = $99/mois ($83 annuel) | P95 = 3,4s (chiffre publie par Firecrawl) | US | — |
| Scraping web | **Apify** | Plateforme d'actors/scrapers, proxies inclus | Facturation au Compute Unit ($0.20-0.30/CU) + location d'actors + proxy/stockage/transfert en sus | Non publie (depend de l'actor) | US (EU-friendly, data residency configurable) | — |
| Scraping web | **Browserless** | Navigateur headless as-a-service | Non trouve dans les sources croisees (absent des resultats de recherche) | Non trouve | US | — |
| Recherche web / RAG | **Tavily** | Recherche web optimisee agents/LLM | ~$8/1000 credits (PAYG), $5/1000 sur plan Growth (keirolabs.cloud, codenote.net, 2026) | Non publie | US | — |
| Recherche web / RAG | **Exa** | Recherche semantique + extraction de contenu | $5/1000 recherches (1-25 resultats) = $0.005/recherche ; +$1/1000 pages pour le contenu (exa.ai) | Non publie | US | — |
| Recherche web / RAG | **Perplexity Sonar / Search API** | Recherche + reponse synthetisee | Sonar Pro : $3/$15 par million tokens in/out + $6-14/1000 requetes ; Search API seule : $5/1000 requetes (sources agregees, prix Sonar de base non confirme independamment) | Non publie | US | — |
| Recherche web / RAG | **SerpAPI** | Scraping resultats moteurs de recherche | A partir de $15/1000 (dev.to, 2026) | Non publie | US | — |
| Recherche web / RAG | **Brave Search API** | Index de recherche independant | $5/1000 requetes (prix publie par Brave) | Non publie | US (index independant, souvent positionne "privacy-first") | — moins cher que SerpAPI |
| Voix (audit vocal, outbound) | **ElevenLabs** | TTS haute qualite / clonage voix | $0.10/1000 caracteres (multilingue) ou $0.05/1000 (Flash/Turbo) ; Business plan TTS bas-latence des $0.05/min | Flash v2.5 : ~75ms | US | **Gradium (FR)** — voir section 2 |
| Email outbound | **Lemlist** | Sequences email + API cold outreach | API incluse des le plan Email $39/mois | Non publie | US | Brevo (FR/EU, pricing au volume d'envoi) |
| Email / CRM | **Brevo** | Envoi email transactionnel/marketing, API | Free 300 emails/jour ; Starter $9/mois (5k emails) jusqu'a $69/mois (100k emails) ; facturation au volume d'envoi, pas au contact | Rate limits documentes par seconde/heure/endpoint (developers.brevo.com) | **FR/EU** | Deja l'option EU la moins chere du comparatif |
| CRM | **HubSpot** | Base de contacts, pipeline, automations | Non trouve (donnee API pricing/rate-limit specifique non confirmee dans les sources croisees) | Non trouve | US | — |

**Metriques que Deadweight peut capter pour ces outils (et observabilite via proxy HTTP) :**

- **Cout par appel** — observable via proxy si l'outil facture au call/credit et que la reponse ou les headers exposent le nombre de credits consommes (Firecrawl, Tavily, Exa le font explicitement dans leurs headers/reponses JSON) ; sinon il faut mapper statiquement le tarif publie au type d'appel (ex. Apollo email=2 credits).
- **Latence** — 100% observable via proxy (timestamp requete/reponse), c'est la metrique la plus fiable et la moins dependante du fournisseur.
- **Taux d'echec / retry** — observable via proxy (codes HTTP 4xx/5xx, timeouts), tres pertinent pour Firecrawl/Apify/scraping ou les echecs sont frequents (pages protegees, CAPTCHA).
- **Appels redondants / doublons** — observable via proxy en hashant les payloads de requete (meme URL scrapee 2x, meme prospect enrichi 2x dans la meme fenetre temporelle) — coeur de la proposition de valeur "waste".
- **Opportunites de cache** — deductible des doublons observes + TTL raisonnable par type de donnee (un enrichissement Apollo d'une entreprise ne change pas en 1h, un scrape de page produit oui) : c'est une heuristique a construire, pas une donnee fournie par l'outil.
- **Point d'attention** — les outils qui facturent en "credits" opaques (Clay, Kaspr) ne remontent pas toujours le cout reel dans la reponse HTTP ; Deadweight devra maintenir une table de correspondance credit->cout tarifaire par outil, mise a jour manuellement — c'est un vrai risque de dette de maintenance a mentionner au jury.

---

## 2. Integration des partenaires hackathon — classement valeur/effort

| Partenaire | Integration concrete en <0,5 jour | Effort | Valeur pour le pitch | Rang |
|---|---|---|---|---|
| **OpenAI** | Modele d'extraction pour classifier les appels loggues (type d'appel, intention, redondance) — deja le coeur du produit (le "classificateur LLM" que Deadweight cherche a remplacer). Integration triviale via API standard, deja probablement en place. | Tres faible (deja prevu dans l'archi) | Haute — demontre le "avant remplacement deterministe" | 1 |
| **Dust** | Front conversationnel de l'auditeur : creer un agent Dust (LLM + instructions + acces aux logs Deadweight via MCP/webhook) permettant a l'utilisateur de poser des questions ("pourquoi ce workflow coute cher ?") en langage naturel. Dust expose une API de conversations (POST message, SSE streaming) et un systeme MCP pour brancher des outils externes — integrable en quelques heures si Deadweight expose deja un endpoint MCP ou REST simple pour ses metriques. | Faible-moyen (depend d'avoir un endpoint de donnees pret) | Haute — UX/demo (15% de la notation), montre l'aspect "agentique" cote front | 2 |
| **Gradium** | Vocaliser le resume d'audit (cout total, gaspillage detecte, recommandation de regle deterministe) en fin de demo. TTS Paris-based, latence tres basse (P50 ~258ms depuis Paris), supporte le francais nativement — cote "pitch" fort pour un jury, integration = un appel API texte->audio en fin de pipeline. | Tres faible (un seul appel API, pas de dependance d'architecture) | Moyenne — bonus demo/pitch clarity (15%), differenciant FR/EU | 3 |
| **Pipelex** | ATTENTION — les sources croisees divergent : la doc Pipelex (docs.pipelex.com) presente encore un format "PLX" (v0.1.0, TOML), mais le repo GitHub principal (github.com/Pipelex/pipelex) decrit desormais un standard renomme **MTHDS** (fichiers `.mthds`, memes concepts domain/concepts/pipes). A verifier en direct avant de s'engager. Si `.mthds`/`.plx` est bien le format cible : Deadweight pourrait emettre un fichier `.mthds` decrivant la regle deterministe extraite (ex. "si intention=X et confiance>0.95, appliquer regle Y sans LLM"), executable ensuite via `pipelex run`. CLI et SDK Python/TS disponibles, integration annoncee "operationnelle en quelques heures" par la doc elle-meme. Licence Elastic License 2.0 (source-available, pas open-source pur — a mentionner si redistribution du code prevue). | Moyen (bloque par la verification du format + la generation d'un bundle valide) | Haute si ca marche (target format tres aligne avec la these du produit : "remplacer le LLM par du deterministe"), mais risque d'effort sous-estime a cause du flou de doc | 2 (valeur) mais risque d'effort — a tester en premier pour lever le doute |
| **Jinko** | Pas de lien evident et fort avec le cas d'usage marketing/audit de Deadweight (Jinko = agents de voyage). Integration possible seulement de maniere artificielle (ex. auditer un workflow Jinko comme cas d'usage de demo) mais faible valeur ajoutee pour le narratif principal. | — | Faible pour ce produit | 5 (a ignorer sauf besoin de cocher toutes les cases partenaires) |

**Recommandation de sequencement (0,5 jour chacun, en parallele si possible) :**
1. Verifier en 30 min le vrai format Pipelex actuel (`.plx` vs `.mthds`) en clonant `pipelex-cookbook` et en lisant un exemple reel avant d'investir du temps dessus.
2. Gradium en premier (effort quasi nul, gain demo garanti).
3. Dust en second si un endpoint de donnees Deadweight existe deja (sinon le pre-requis fait deraper le budget de 0,5 jour).
4. OpenAI est deja natif au produit — pas un "ajout" a proprement parler.
5. Jinko — a ecarter sauf si le jury valorise explicitement la couverture de tous les partenaires.

---

## 3. Sources publiques de workflows agentiques reels a auditer

| Source | Type | Lien |
|---|---|---|
| n8n.io — categorie Marketing | 3859 workflows communautaires, JSON exportable/importable directement | https://n8n.io/workflows/categories/marketing/ |
| n8n.io — categorie Market Research | 1151 workflows (enrichissement, veille) | https://n8n.io/workflows/categories/market-research/ |
| n8n — template "Lead generation LinkedIn personalisation, enrichment" | Workflow concret d'enrichissement + personnalisation, pret a importer | https://n8n.io/workflows/4685-lead-generation-automate-on-linkedin-personalisation-enrichment/ |
| GitHub — tachyurgy/n8n-automation-portfolio | Workflows production-grade : agents IA, lead enrichment, repurposing de contenu, JSON reel importable | https://github.com/tachyurgy/n8n-automation-portfolio |
| GitHub — Denizk276/ai-lead-enrichment-workflow | Workflow n8n de recherche/enrichissement d'entreprises avec profil + accroche personnalisee | https://github.com/Denizk276/ai-lead-enrichment-workflow |
| Make.com — Template Gallery (filtre Marketing/AI) | +1000 scenarios pre-construits, filtrables par app (HubSpot, Slack, Shopify) | https://www.make.com/en/templates (categorie Marketing/AI) |
| GitHub — thibaudgregori/Workflow-test-hackathon-agentique-25-09-2026 | Workflows deja passes par la passerelle Deadweight : shorts-factory de Miguel, recap Gmail, exemple officiel du SDK Agents d'OpenAI. Resultats dans `docs/retours-tests-workflows.md` | https://github.com/thibaudgregori/Workflow-test-hackathon-agentique-25-09-2026 (workflow 1 : https://github.com/thibaudgregori/Workflow-test-hackathon-agentique-25-09-2026/tree/main/workflow%201%20-%20Miguel%20short) |

Ces sources permettent de tester Deadweight sur des workflows n8n/Make reels sans avoir a les construire soi-meme — priorite aux deux premiers repos GitHub (JSON directement exploitable en replay).

---

## Non trouve / a ne pas presenter comme fait

- Latence precise pour Clay, Apollo, Dropcontact, Kaspr, Apify, Tavily, Exa, Perplexity Sonar, SerpAPI, Lemlist, HubSpot — non publiee dans les sources croisees.
- Browserless — aucune donnee de pricing/latence trouvee dans les recherches menees.
- Pricing/rate-limit API HubSpot specifique — non confirme.
- Format exact et stable de Pipelex (`.plx` vs `.mthds`) — sources contradictoires, a verifier en direct avant le hackathon plutot que de batir l'integration dessus a l'aveugle.
