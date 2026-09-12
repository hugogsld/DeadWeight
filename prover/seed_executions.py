import json, os, random, sys, time, urllib.request
U = os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/")
P = os.environ.get("DW_WEBHOOK_PATH", "triage-original")
T = {
 "billing": ["Je n'arrive pas a telecharger ma facture de {mois}",
  "Ma facture de {mois} me semble incorrecte, le montant a double",
  "Le paiement a echoue {n} fois, la carte est pourtant valide",
  "Je veux un remboursement sur la facture de {mois}",
  "Mon abonnement a ete debite deux fois ce mois-ci",
  "Comment obtenir une facture au nom de ma societe ?",
  "Le prelevement du {n} n'est jamais passe",
  "Je souhaite changer de formule de paiement"],
 "technical": ["L'application plante quand j'ouvre le tableau de bord",
  "Erreur {n} au chargement de la page export",
  "Le bouton d'export ne fait rien depuis la mise a jour",
  "Les donnees ne se synchronisent plus depuis {mois}",
  "La page reste blanche apres la connexion",
  "Un bug affiche des chiffres faux dans le rapport",
  "L'upload de fichier echoue systematiquement",
  "Le site est tres lent depuis {n} jours"],
 "account": ["Comment changer l'email de mon compte ?",
  "Impossible de reinitialiser mon mot de passe",
  "Je veux supprimer mon compte definitivement",
  "Comment ajouter un collegue a mon espace ?",
  "Mon compte semble bloque depuis {mois}",
  "Je n'ai jamais recu l'email de confirmation",
  "Comment activer la double authentification ?",
  "Je veux transferer la propriete du compte"],
 "other": ["Bonjour, je voulais juste vous feliciter pour le produit",
  "Avez-vous une version mobile prevue ?",
  "Ou puis-je trouver votre documentation ?",
  "Proposez-vous des tarifs pour les associations ?"]}
W = {"billing": .41, "technical": .30, "account": .22, "other": .07}
M = "janvier fevrier mars avril mai juin juillet septembre octobre novembre decembre".split()
PRE = ["", "Bonjour, ", "Bonsoir, ", "Salut, "]
SUF = ["", " Merci d'avance.", " Pouvez-vous m'aider ?", " C'est urgent.", " Cordialement."]
n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
url, ok, fail, t0 = f"{U}/webhook/{P}", 0, 0, time.time()
for i in range(n):
    c = random.choices(list(W), weights=list(W.values()))[0]
    txt = random.choice(PRE) + random.choice(T[c]).format(mois=random.choice(M), n=random.randint(2, 500)) + random.choice(SUF)
    r = urllib.request.Request(url, data=json.dumps({"text": txt}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(r, timeout=60).read(); ok += 1
    except Exception as e:
        fail += 1
        if fail == 1: print(f"erreur: {e}\n  -> workflow publie ? url={url}")
    if (i+1) % 25 == 0: print(f"  {i+1}/{n}  ok={ok} fail={fail}  {time.time()-t0:.0f}s")
print(f"\ntermine: {ok} executions, {fail} echecs, {time.time()-t0:.0f}s")
