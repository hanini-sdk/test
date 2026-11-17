# Réconciliation bancaire débits / crédits

Regroupe des mouvements bancaires de sorte que, dans chaque groupe, la somme des
débits soit égale à la somme des crédits. Le script maximise le nombre de
mouvements réconciliés, puis minimise le nombre de groupes, avec Google OR-Tools CP-SAT.

## Installation

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Utilisation

```bash
python generer_donnees_test.py                 # crée mouvements.xlsx (jeu d'essai)
python generer_donnees_test.py --volume 100000 -o gros.xlsx   # jeu dense de performance
python reconcilier.py --input mouvements.xlsx --window-days 30 --time-limit 60
```

Le résultat est écrit dans `reconciliation_resultat.xlsx` (feuilles « Mouvements »,
« Groupes », « Non réconciliés », « Résumé », et « Erreurs » s'il y a des lignes invalides).

### Fichier d'entrée

Colonnes attendues : `montant` (positif), `type` (`debit` / `credit`, casse, accents
et espaces ignorés), `date`. Colonnes facultatives : `id`, `libelle`. Sans colonne
`id`, l'identifiant est le numéro de ligne Excel (`L2`, `L3`, …).

Les noms courants sont détectés automatiquement ; sinon, désignez-les :

```bash
python reconcilier.py --input releve.xlsx --col-montant "Amount" --col-type "Sens" --col-date "Date valeur"
```

Les dates saisies en texte sont lues au format jour/mois/année (ou ISO `AAAA-MM-JJ`).

### Options

| Option | Défaut | Rôle |
|---|---|---|
| `--window-days` | 30 | Écart maximal en jours entre deux mouvements d'un même groupe |
| `--max-group-size` | 20 | Nombre maximal de mouvements par groupe |
| `--tolerance-cents` | 0 | Écart toléré entre débits et crédits d'un groupe |
| `--time-limit` | 60 | Limite de temps du solveur, par composante (secondes) |
| `--weight-by-amount` | non | Maximiser le montant réconcilié plutôt que le nombre de mouvements |
| `--output` | `reconciliation_resultat.xlsx` | Fichier de sortie |
| `--sheet` | première | Feuille à lire |
| `--config` | — | Fichier JSON de paramètres ; la ligne de commande reste prioritaire |
| `--strict` | non | S'arrêter si une ligne est invalide, au lieu de l'exclure |
| `--workers`, `--seed` | 8, 0 | Threads et graine du solveur |
| `--seuil-exact` | 30 | Au-delà de ce nombre de mouvements, une composante est résolue par blocs |
| `--taille-bloc` | 300 | Mouvements par bloc (grosses composantes) |
| `--taille-combinaison` | 4 | Mouvements max par groupe cherché dans un bloc (2 à 4) |
| `--passes` | 4 | Passes par blocs, à frontières alternativement décalées |
| `--temps-bloc` | 1 | Limite du solveur par bloc (secondes) |
| `--processus` | 0 | Blocs résolus en parallèle (0 = nombre de cœurs) |
| `--verbose` | non | Journalisation DEBUG |

Exemple de fichier de config :

```json
{ "input": "mouvements.xlsx", "window_days": 15, "max_group_size": 8, "time_limit": 120 }
```

Codes de retour : `0` succès, `2` entrée invalide, `3` échec de la vérification finale.

## Fonctionnement

1. **Validation** — les montants sont convertis en centimes entiers. Les lignes à
   montant nul, négatif ou non numérique, à type inconnu ou à date manquante sont
   exclues, listées dans le journal et dans la feuille « Erreurs ».
2. **Appariements exacts 1-à-1** — un débit et un crédit de même montant, dans la
   fenêtre, en servant d'abord les dates les plus proches.
3. **Composantes connexes** — les mouvements restants sont découpés aux « trous »
   de plus de W jours ; chaque composante est résolue séparément.
4. **CP-SAT exact** (composantes ≤ `--seuil-exact`) — variables `x[m,k]` et `u[k]`,
   contraintes d'unicité, d'équilibre, de fenêtre, de taille, de symétrie ; objectif
   `1000·Σx − Σu`.
5. **CP-SAT par blocs** (grosses composantes) — la composante est découpée par
   date en blocs de `--taille-bloc` mouvements. Dans chaque bloc, une recherche
   vectorisée (numpy, sommes de paires triées) énumère toutes les combinaisons
   équilibrées de 2 à 4 mouvements dans la fenêtre ; CP-SAT choisit ensuite les
   combinaisons disjointes qui couvrent le plus de mouvements. Les blocs sont résolus
   en parallèle, puis de nouvelles passes à frontières décalées traitent le reste.
   Les restes devenus de petites composantes repassent par le modèle exact.
6. **Vérification finale** — indépendante du solveur : écart de chaque groupe dans
   la tolérance, aucun mouvement dans deux groupes, fenêtre et taille respectées.
   En cas d'échec, aucun fichier n'est écrit.

Statut par composante dans « Résumé » : `OPTIMAL`, `FEASIBLE` (solution valide,
optimalité non prouvée dans le temps imparti), `UNKNOWN` (aucune solution trouvée
à temps), `SANS_SOLVEUR` (composante ne contenant que des débits ou que des crédits),
`HEURISTIQUE` (résolue par blocs : groupes valides, optimalité globale non prouvée).

## À savoir

- **Minimiser le nombre de groupes fusionne les groupes.** Deux groupes équilibrés
  de la même composante sont réunis en un seul s'ils tiennent dans la fenêtre et la
  taille maximale. Pour des groupes plus fins, baissez `--max-group-size`.
- **Les appariements exacts sont une heuristique.** Ils sont figés avant le solveur ;
  dans de rares cas, une paire exacte peut priver CP-SAT d'une combinaison couvrant
  davantage de mouvements.
- **Volumétrie.** Le modèle exact compte `n × K` variables par composante : il est
  réservé aux composantes de moins de `--seuil-exact` mouvements. Au-delà, le mode par
  blocs prend le relais. Repère : 100 000 mouvements denses sur un an (une seule
  composante de 53 000 mouvements après les paires exactes) sont traités en ~35 s
  sur 10 cœurs (lecture < 1 s, résolution ~23 s, écriture ~9 s), avec 98,6 % de
  mouvements réconciliés.
- **Mode par blocs.** Un groupe de plus de `--taille-combinaison` mouvements (ex. 2
  débits pour 3 crédits) n'est trouvé que dans une composante assez petite pour le
  modèle exact. Les groupes ne sont pas fusionnés entre eux. Comme chaque bloc est
  limité en temps, deux exécutions peuvent différer légèrement (quelques dizaines de
  mouvements sur 100 000) ; augmenter `--temps-bloc` réduit cet écart.
- **Moteurs Excel.** `python-calamine` (lecture) et `xlsxwriter` (écriture) sont
  utilisés s'ils sont installés, sinon openpyxl (3 à 10 fois plus lent).

## Tests

```bash
pytest
```

## Arborescence

```
reconcilier.py              Interface en ligne de commande
generer_donnees_test.py     Génère le jeu d'essai mouvements.xlsx
reconciliation/
  types.py                  Mouvement, Groupe, Parametres, Resultat
  chargement.py             Lecture Excel, mapping des colonnes
  validation.py             Contrôles, conversion en centimes, rapport d'erreurs
  pretraitement.py          Appariements exacts, composantes connexes
  modele.py                 Construction du modèle CP-SAT
  resolution.py             Résolution par composante, fusion
  grande_echelle.py         Mode par blocs pour les grosses composantes
  verification.py           Assertions finales
  export.py                 Écriture du classeur de résultat
tests/test_reconciliation.py
requirements.txt
```
