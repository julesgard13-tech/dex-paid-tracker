# DEX PAID TRACKER (Solana)

Tableau de bord gratuit pour observer les tokens Solana dont le profil DEX Screener a été payé (`tokenProfile`).

## Ce que fait cette version

- Interroge périodiquement l'endpoint public `token-profiles/latest/v1`.
- Vérifie les ordres de chaque token avec `/orders/v1/solana/{tokenAddress}`.
- Ne retient comme signal que les ordres `tokenProfile` avec le statut `approved`.
- Récupère la market cap actuelle via `/tokens/v1/solana/{addresses}`.
- Enregistre le premier market cap observé après détection, puis des snapshots périodiques pendant 24 h.
- Calcule le maximum/minimum observé **après** le signal observé et les seuils de hausse/baisse atteints.
- Publie un dashboard statique via GitHub Pages.

## Limites importantes (à lire)

1. **Pas de backfill fiable des 100–200 derniers paiements.** L'API publique DEX Screener expose une liste récente de profils et la vérification des ordres par token, mais pas un historique paginé de tous les paiements. Le tracker construit donc son historique à partir de son activation. Il peut afficher moins de 100 tokens au départ.
2. **La market cap exacte à la seconde du paiement n'est pas fournie par cette API.** `entry_mc` est le premier market cap observé par le tracker après détection. Le tableau affiche le délai de détection. Les observations tardives sont marquées `RETARD`; elles ne doivent pas être confondues avec un achat exact au moment du paiement.
3. **Le maximum est calculé après l'entrée enregistrée**, jamais avec l'ATH antérieur au paiement.
4. Les snapshots toutes les 15 minutes ne voient pas tous les mouvements intraintervalles. Un seuil affiché comme atteint signifie qu'un snapshot l'a observé, pas qu'un ordre aurait nécessairement pu être exécuté à ce prix.
5. `marketCap` peut être absent. Dans ce cas le tracker n'invente pas une market cap à partir de `fdv`; le token reste sans base exploitable jusqu'à ce qu'une market cap soit disponible.
6. Les données sont indicatives. Liquidité, frais, priorité réseau, slippage, taxes de token, MEV et impossibilité de vendre peuvent fortement changer le résultat réel. Ce tracker n'envoie aucun ordre et ne connecte aucun wallet.

## Installation (gratuite)

### 1. Créer le dépôt

- Sur GitHub, crée un nouveau dépôt nommé `dex-paid-tracker`.
- Choisis **Public** (GitHub Pages et Actions sont gratuits dans cette configuration).
- N'ajoute pas de README, licence ou `.gitignore` au moment de la création si tu importes ensuite tous les fichiers du ZIP.

Le code et les données du dépôt public seront visibles publiquement. Il n'y a aucune clé API ni donnée privée dans ce projet.

### 2. Importer les fichiers

Décompresse le ZIP sur ton ordinateur. Dans le dépôt GitHub :
- `Add file` → `Upload files`
- Glisse tous les fichiers et dossiers du projet (y compris `.github`).
- Clique sur `Commit changes`.

Sur iPhone, l'import de plusieurs dossiers est compliqué : utilise de préférence un ordinateur, ou l'interface web GitHub fichier par fichier.

### 3. Activer GitHub Pages

- Dépôt → `Settings` → `Pages`
- `Build and deployment` → `Deploy from a branch`
- Branch : `main`
- Folder : `/docs`
- `Save`

Ton site sera publié à une adresse du type `https://TON-PSEUDO.github.io/dex-paid-tracker/`.

### 4. Activer le collecteur

- Dépôt → `Actions`
- Si GitHub demande de confirmer les workflows, clique sur `I understand my workflows, go ahead and enable them`.
- Ouvre `DEX Paid Tracker - collect`
- Clique sur `Run workflow` pour lancer un premier test manuel.
- Le workflow est ensuite planifié toutes les 15 minutes (UTC). GitHub peut retarder les tâches planifiées en période de charge.

### 5. Autoriser le workflow à enregistrer les données

Normalement le workflow définit déjà `contents: write`. Si le premier lancement échoue lors du `git push` :
- Dépôt → `Settings` → `Actions` → `General`
- `Workflow permissions` → `Read and write permissions`
- Enregistre puis relance le workflow.

## Comment lire les résultats

- `Tokens suivis` : tokens détectés par ce tracker depuis son activation.
- `Entrée observée` : première market cap disponible après la détection, pas nécessairement la market cap exacte à la seconde du paiement.
- `ATH post-détection` : plus haut snapshot enregistré après l'entrée.
- `+40 % observé` : au moins un snapshot a atteint 1,40 × l'entrée.
- `Retard` : plus de 30 minutes entre le timestamp de paiement fourni par DEX Screener et la première observation du tracker.
- `Échantillon exploitable` : les tokens avec entrée market cap disponible et détection dans les 30 minutes. Il faut accumuler suffisamment de données avant de tirer une conclusion.

## Données et cadence

- Une exécution toutes les 15 minutes.
- Snapshots pendant 24 heures après la première détection.
- Conservation des 500 tokens les plus récents.
- Les données sont stockées dans `docs/data.json` et publiées avec le site.

## Dépannage

- Si le dashboard affiche `Aucune donnée`, lance le workflow manuellement et vérifie l'onglet `Actions`.
- Si les tokens ne sont pas détectés, cela peut signifier que la liste publique DEX Screener ne les expose pas dans sa fenêtre récente, ou que l'ordre `tokenProfile` n'est pas `approved`.
- Si l'API renvoie une erreur temporaire, le prochain passage réessaiera.
- Ne désactive pas le dépôt public sans vérifier les conditions actuelles de GitHub Pages et GitHub Actions pour ton compte.
