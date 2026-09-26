"""Génère leviers/README.md et une fiche par levier depuis la liste ci-dessous.

    python leviers/_generer.py

Une seule source : modifier LEVIERS puis relancer. Rang = gain × fréquence × facilité à prouver.
"""
from pathlib import Path

ICI = Path(__file__).resolve().parent

# rang, fichier, titre, famille, argent, latence, preuve, données, état, règle
LEVIERS = [
    dict(fichier="01-llm-qui-aiguille", titre="Un LLM qui ne fait qu'aiguiller", famille="Usage des LLM",
         argent="90 à 100 % de l'étape", latence="×1 000 (700 ms → 0,2 ms)", preuve="Rejeu, seuil 95 %",
         donnees="Événements passerelle", etat="Fait (R1, D3.1, D3.2, D3.3, D4.3)", regle="R1 low_entropy_output",
         signal="Des centaines d'appels, une poignée de réponses différentes : le modèle classe, il ne raisonne pas.",
         detection="Entropie de Shannon des sorties normalisées, par application × modèle × gabarit de prompt.",
         optimisation="Remplacer par des règles fixes (mots-clés extraits de l'historique), le modèle gardé en secours "
                      "pour les cas non couverts. Mode miroir d'abord, court-circuit ensuite.",
         comment_prouver="Extraction des règles puis rejeu sur tout l'historique hors exemples ; refus sous 95 % "
                         "d'accord. En production : mode miroir.",
         suite="Tester aussi un classifieur léger ou des embeddings quand les règles couvrent mal (banc de modèles)."),
    dict(fichier="02-modele-surdimensionne", titre="Un modèle trop gros pour la tâche", famille="Usage des LLM",
         argent="÷10 à ÷20 (gpt-4o → mini)", latence="Premier mot plus rapide", preuve="Banc de modèles",
         donnees="Événements + catalogue", etat="Détection faite (R2), banc en cours, M1/M2 (Hugo)",
         regle="R2 oversized_model",
         signal="Un modèle haut de gamme produit des sorties courtes ou simples.",
         detection="Prix du modèle au catalogue, longueur et diversité des sorties, famille de la tâche.",
         optimisation="Proposer trois options : la moins chère, le meilleur compromis, la souveraine. Jamais un modèle "
                      "trop faible : garde-fou qualité.",
         comment_prouver="**Banc de modèles** : rejouer un échantillon du vrai trafic sur les candidats (petits, locaux "
                         "via Ollama, en ligne via OpenRouter), mesurer l'accord, la latence, le coût. Rien n'est "
                         "recommandé sans ce test.",
         suite="Bibliothèque de candidats versionnée ; indice de qualité (Artificial Analysis) pour présélectionner."),
    dict(fichier="03-raisonnement-excessif", titre="Un modèle qui réfléchit trop", famille="Usage des LLM",
         argent="50 à 80 % des appels concernés", latence="Forte (le raisonnement précède la réponse)",
         preuve="Banc (effort bas vs haut)", donnees="Événements (reasoning_tokens)", etat="En cours (R7)",
         regle="R7 excess_reasoning",
         signal="Beaucoup de jetons de réflexion facturés pour des réponses courtes ou triviales.",
         detection="Rapport jetons de réflexion / jetons de sortie visibles, croisé avec la simplicité de la tâche.",
         optimisation="Baisser l'effort de raisonnement, ou passer à un modèle sans raisonnement pour cette étape.",
         comment_prouver="Banc de modèles : même modèle avec effort bas, comparer l'accord.",
         suite="Les modèles récents (gpt-5, o-series, Claude avec réflexion) rendent ce levier de plus en plus gros."),
    dict(fichier="04-cache-de-prompt", titre="Le cache de prompt non utilisé", famille="Usage des LLM",
         argent="Jusqu'à 90 % du coût d'entrée répété", latence="Premier mot plus rapide", preuve="Calcul exact",
         donnees="Événements + prix du cache", etat="Fait (R4) ; prix du cache branchés (OpenRouter)",
         regle="R4 no_cache",
         signal="Un long préfixe (instructions, documents) identique d'un appel à l'autre, sans jetons en cache.",
         detection="Préfixe commun des requêtes d'un même gabarit, cached_input_tokens nuls.",
         optimisation="Ordonner le prompt (fixe d'abord, variable ensuite) ; activer le cache là où il est explicite "
                      "(Anthropic, Mistral) ; clé de cache stable.",
         comment_prouver="Le gain se calcule : jetons répétés × (prix normal − prix du cache).",
         suite="Règles propres à chaque fournisseur : seuils (1 024 jetons OpenAI, 64 Mistral), durée de vie."),
    dict(fichier="05-contexte-et-rag", titre="Trop de contexte envoyé (historique, RAG)", famille="Forme des briques d'IA",
         argent="Coût d'entrée ÷2 à ÷10", latence="Moyenne", preuve="Banc (contexte réduit)",
         donnees="Événements (taille des messages)", etat="Symptôme détecté (R3) ; causes RAG à faire",
         regle="R3 raw_context",
         signal="La taille des requêtes grossit à chaque tour ; des documents entiers sont renvoyés.",
         detection="Croissance du nombre de jetons d'entrée dans une trace ; blocs répétés d'un appel à l'autre.",
         optimisation="Résumer l'historique ; RAG : morceaux plus petits, moins de documents, un reclasseur ; ne pas "
                      "ré-encoder les documents à chaque exécution ; pas de RAG sur un petit corpus.",
         comment_prouver="Banc de modèles avec le contexte réduit : la réponse reste-t-elle la même ?",
         suite="Détecter la forme du RAG (nombre et taille des extraits) dans les requêtes."),
    dict(fichier="06-etapes-paralleles", titre="Des étapes en série qui pourraient tourner en parallèle",
         famille="Forme du workflow", argent="Aucun", latence="Le plus gros gain : ×2 à ×5 sur le workflow",
         preuve="Horaires d'exécution", donnees="Historique n8n (B1)", etat="À faire (R10, après B1)",
         regle="R10 (à venir)",
         signal="Deux étapes qui ne dépendent pas l'une de l'autre s'exécutent l'une après l'autre.",
         detection="Graphe du workflow (dépendances de données) + horaires réels de chaque nœud dans l'historique.",
         optimisation="Brancher les étapes indépendantes en parallèle.",
         comment_prouver="Chemin critique recalculé à partir des vraies durées : latence avant / après.",
         suite="Seul argument latence sur la forme du workflow : priorité dès que B1 fonctionne."),
    dict(fichier="07-appels-identiques", titre="Les mêmes appels payés plusieurs fois", famille="Usage des LLM",
         argent="100 % de chaque doublon", latence="Réponse immédiate si mise en cache", preuve="Calcul exact",
         donnees="Événements", etat="En cours (R8)", regle="R8 duplicate_calls",
         signal="Même modèle, même requête, même réponse, payés à nouveau.",
         detection="Empreinte de la requête normalisée ; fenêtre de temps.",
         optimisation="Mettre les réponses en cache avec une durée de vie adaptée.",
         comment_prouver="Nombre de doublons × coût mesuré.",
         suite="Cache sémantique (requêtes proches) plus tard, avec preuve par rejeu."),
    dict(fichier="08-agent-en-boucle", titre="Un agent qui tourne en rond", famille="Forme des briques d'IA",
         argent="Chaque tour en trop", latence="Forte", preuve="Traces", donnees="Événements regroupés en traces",
         etat="Fait (R5)", regle="R5 unbounded_loop",
         signal="Le même outil appelé encore et encore avec des arguments quasi identiques.",
         detection="Répétitions d'actions dans une trace (arguments comparés clé par clé).",
         optimisation="Plafond d'étapes, détection de répétition, sortie de secours.",
         comment_prouver="Traces montrées au client ; coût des tours en trop.", suite="—"),
    dict(fichier="09-agent-ou-chaine", titre="Un agent là où une chaîne fixe suffit", famille="Forme des briques d'IA",
         argent="Coût d'orchestration", latence="Moyenne", preuve="Traces", donnees="Événements regroupés en traces",
         etat="Fait (R6)", regle="R6 agent_where_chain",
         signal="L'agent suit toujours le même chemin d'outils.",
         detection="Part du chemin dominant parmi les traces (seuil 90 %, 10 traces minimum).",
         optimisation="Remplacer par une chaîne fixe ; garder l'agent pour les cas atypiques.",
         comment_prouver="Distribution des chemins.", suite="—"),
    dict(fichier="10-boucle-sur-elements", titre="Un appel LLM par élément au lieu d'un appel groupé",
         famille="Forme du workflow", argent="÷5 à ÷20", latence="÷5 à ÷20", preuve="Banc (lot vs unitaire)",
         donnees="Historique n8n (B1)", etat="À faire (R11, après B1)", regle="R11 (à venir)",
         signal="Une étape LLM dans une boucle sur les lignes d'un tableau.",
         detection="Graphe n8n (nœud LLM dans une boucle) ou rafales d'appels du même gabarit.",
         optimisation="Regrouper les éléments dans un seul appel structuré, ou l'API batch.",
         comment_prouver="Banc de modèles sur l'appel groupé.", suite="—"),
    dict(fichier="11-sorties-trop-longues", titre="Des réponses trop longues", famille="Usage des LLM",
         argent="20 à 60 % (la sortie coûte 4 à 8 fois l'entrée)", latence="Proportionnelle", preuve="Calcul + banc",
         donnees="Événements", etat="En cours (R12)", regle="R12 verbose_output",
         signal="Beaucoup de jetons de sortie, pas de plafond, réponses tronquées ou bavardes.",
         detection="Distribution des longueurs de sortie par gabarit ; max_tokens absent ; fin par longueur.",
         optimisation="Plafonner, demander une sortie structurée et concise.",
         comment_prouver="Banc avec plafond : la réponse utile reste-t-elle ?", suite="—"),
    dict(fichier="12-erreurs-et-relances", titre="Des erreurs et relances payées", famille="Usage des LLM",
         argent="Variable, parfois énorme", latence="Forte (attentes, relances)", preuve="Calcul exact",
         donnees="Événements", etat="En cours (R9)", regle="R9 paid_errors",
         signal="Taux d'erreur, relances en rafale, sorties coupées relancées.",
         detection="Statut, erreur, fin de réponse ; même requête relancée en quelques secondes.",
         optimisation="Attente progressive, plafond de relances, sortie structurée pour éviter les JSON invalides.",
         comment_prouver="Coût réellement facturé des appels en échec.", suite="—"),
    dict(fichier="13-api-batch", titre="Des tâches non urgentes payées plein tarif", famille="Usage des LLM",
         argent="50 %", latence="Aucun (elle augmente, c'est voulu)", preuve="Calcul exact",
         donnees="Événements (horaires)", etat="À faire", regle="—",
         signal="Rafales nocturnes ou planifiées, sans utilisateur qui attend.",
         detection="Répartition horaire, absence de streaming, déclencheur planifié (n8n).",
         optimisation="API batch des fournisseurs (−50 %).", comment_prouver="Calcul sur les prix batch.", suite="—"),
    dict(fichier="14-autres-api", titre="Les autres API du workflow (recherche, scraping, enrichissement)",
         famille="Appels d'autres API", argent="Doublons : 100 % ; choix du fournisseur : ÷3",
         latence="Appels parallélisables", preuve="Calcul exact", donnees="Relais HTTP générique (C1)",
         etat="Mis de côté (C1, C2)", regle="—",
         signal="Même prospect enrichi deux fois, même page scrapée, fournisseur cher.",
         detection="Relais HTTP générique : empreinte des requêtes, coût par appel, erreurs.",
         optimisation="Cache avec durée de vie, cascade du moins cher au plus cher, fournisseur moins cher.",
         comment_prouver="Doublons × prix ; comparaison de prix publics.", suite="Pour la finale."),
    dict(fichier="15-definitions-outils", titre="Des définitions d'outils envoyées à chaque appel",
         famille="Forme des briques d'IA", argent="10 à 40 % de l'entrée d'un agent", latence="Faible",
         preuve="Calcul", donnees="Événements (outils de la requête)", etat="À faire", regle="—",
         signal="Vingt outils décrits longuement à chaque tour d'agent, deux utilisés.",
         detection="Taille des définitions d'outils vs outils réellement appelés.",
         optimisation="Ne passer que les outils utiles à l'étape ; descriptions courtes ; cache.",
         comment_prouver="Jetons économisés × prix.", suite="—"),
    dict(fichier="16-souverainete", titre="Des données qui partent hors d'Europe", famille="Conformité",
         argent="—", latence="—", preuve="Catalogue (origine, hébergement)", donnees="Événements + catalogue M1",
         etat="Fait (data_outside_eu, catalogue M1/M2)", regle="data_outside_eu",
         signal="Appels vers un fournisseur sans hébergement UE (API directe d'Anthropic, par exemple).",
         detection="Destination réelle de chaque appel (upstream capturé par la passerelle, sinon déduite du "
                   "format), qualifiée par le catalogue : UE, hors UE, ou non garantie.",
         optimisation="D'abord le même modèle en région UE quand l'éditeur la propose (aucun changement de "
                      "qualité) ; sinon un modèle d'éditeur européen, nommé seulement pour une tâche simple (R2), "
                      "à tester au banc.",
         comment_prouver="Banc de modèles sur l'alternative.", suite="Argument fort pour les clients français."),
    dict(fichier="17-forme-du-workflow", titre="Autres gains sur la forme du workflow", famille="Forme du workflow",
         argent="Variable", latence="Variable", preuve="Graphe + historique", donnees="Historique n8n (B1)",
         etat="À faire, après B1", regle="—",
         signal="Étapes LLM enchaînées fusionnables, étapes dont le résultat ne sert à rien, déclencheur trop "
                "fréquent (exécutions à vide), filtre simple qui éviterait le LLM.",
         detection="Graphe du workflow et historique des exécutions.",
         optimisation="Fusionner, supprimer, filtrer avant, déclencher sur événement.",
         comment_prouver="Exécutions et coûts avant / après calculés sur l'historique.", suite="—"),
    dict(fichier="18-images-et-relecture", titre="Images en haute résolution, relecture par un LLM juge",
         famille="Usage des LLM", argent="Images : ÷5 à ÷10 ; relecture : ×2 évité", latence="Moyenne",
         preuve="Calcul + banc", donnees="Événements", etat="À faire", regle="—",
         signal="Vision en détail haut pour lire un titre ; un deuxième LLM qui juge chaque réponse.",
         detection="Paramètres d'image ; paires d'appels « génération puis jugement ».",
         optimisation="Basse résolution ; relecture par échantillon ou par règle.",
         comment_prouver="Banc de modèles.", suite="—"),
]

FICHE = """# {rang}. {titre}

| | |
|---|---|
| Famille | {famille} |
| Gain argent | {argent} |
| Gain latence | {latence} |
| Comment prouver | {preuve} |
| Données nécessaires | {donnees} |
| État | {etat} |
| Règle | {regle} |

## Le signal
{signal}

## Comment le détecter
{detection}

## Ce qu'on propose au client
{optimisation}

## Comment le prouver avant de le recommander
{comment_prouver}

## Suite
{suite}
"""

INDEX = """# Leviers d'optimisation

Tout ce sur quoi Deadweight peut faire gagner de l'argent, de la latence ou de la fiabilité à un workflow
agentique, **classé par importance** (gain × fréquence × facilité à prouver). Une fiche par levier : le
signal, la détection, ce qu'on propose, comment on le prouve, les données nécessaires, l'état.

Principe commun : **rien n'est recommandé sans preuve sur le vrai trafic du client** (rejeu, banc de
modèles, calcul exact sur l'historique). Un levier non prouvé reste une piste.

Fichiers générés par `python leviers/_generer.py` : modifier la liste dans ce script, pas les fiches.

| Rang | Levier | Famille | Argent | Latence | Preuve | État |
|---|---|---|---|---|---|---|
{lignes}
"""


def main():
    lignes = []
    for rang, lv in enumerate(LEVIERS, 1):
        (ICI / f"{lv['fichier']}.md").write_text(FICHE.format(rang=rang, **lv), encoding="utf-8")
        lignes.append(f"| {rang} | [{lv['titre']}]({lv['fichier']}.md) | {lv['famille']} | {lv['argent']} | "
                      f"{lv['latence']} | {lv['preuve']} | {lv['etat']} |")
    (ICI / "README.md").write_text(INDEX.format(lignes="\n".join(lignes)), encoding="utf-8")
    print(f"{len(LEVIERS)} fiches écrites dans {ICI}")


if __name__ == "__main__":
    main()
