#!/usr/bin/env python3
"""Réconciliation de mouvements bancaires — interface en ligne de commande.

Exemple :
    python reconcilier.py --input mouvements.xlsx --window-days 30 --time-limit 60
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from reconciliation.chargement import ErreurChargement, charger_excel, resoudre_colonnes
from reconciliation.export import exporter
from reconciliation.resolution import reconcilier
from reconciliation.types import Parametres
from reconciliation.validation import rapport_erreurs, valider
from reconciliation.verification import ErreurVerification

log = logging.getLogger("reconcilier")

CODE_OK = 0
CODE_ERREUR_ENTREE = 2
CODE_ERREUR_VERIFICATION = 3

CHAMPS_COLONNES = ("montant", "type", "date", "id", "libelle")


def construire_parseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Réconcilie des débits et des crédits en groupes équilibrés (OR-Tools CP-SAT).",
    )
    p.add_argument("--input", "-i", help="Fichier Excel d'entrée (.xlsx)")
    p.add_argument(
        "--output", "-o", default="reconciliation_resultat.xlsx",
        help="Fichier Excel de sortie (défaut : %(default)s)",
    )
    p.add_argument("--config", help="Fichier JSON de paramètres (la ligne de commande reste prioritaire)")
    p.add_argument("--sheet", default=0, help="Nom ou numéro de la feuille à lire (défaut : première)")

    metier = p.add_argument_group("contraintes métier")
    metier.add_argument("--window-days", type=int, default=30,
                        help="Écart maximal en jours entre deux mouvements d'un groupe (défaut : %(default)s)")
    metier.add_argument("--max-group-size", type=int, default=20,
                        help="Nombre maximal de mouvements par groupe (défaut : %(default)s)")
    metier.add_argument("--tolerance-cents", type=int, default=0,
                        help="Écart toléré entre débits et crédits, en centimes (défaut : %(default)s)")
    metier.add_argument("--time-limit", type=float, default=60,
                        help="Limite de temps du solveur par composante, en secondes (défaut : %(default)s)")
    metier.add_argument("--weight-by-amount", action="store_true",
                        help="Maximiser le montant réconcilié plutôt que le nombre de mouvements")

    colonnes = p.add_argument_group("mapping des colonnes (détection automatique par défaut)")
    for champ in CHAMPS_COLONNES:
        colonnes.add_argument(f"--col-{champ}", help=f"Nom de la colonne « {champ} »")

    divers = p.add_argument_group("divers")
    divers.add_argument("--workers", type=int, default=8,
                        help="Nombre de threads du solveur (défaut : %(default)s)")
    divers.add_argument("--seed", type=int, default=0, help="Graine aléatoire du solveur")
    divers.add_argument("--strict", action="store_true",
                        help="Arrêter si une ligne est invalide, au lieu de l'exclure")
    divers.add_argument("--verbose", "-v", action="store_true", help="Journalisation DEBUG")
    return p


def lire_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse la ligne de commande ; les valeurs de --config servent de défauts."""
    parseur = construire_parseur()
    pre, _ = parseur.parse_known_args(argv)
    if pre.config:
        try:
            config = json.loads(Path(pre.config).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parseur.error(f"Fichier de config illisible ({pre.config}) : {exc}")
        if not isinstance(config, dict):
            parseur.error("Le fichier de config doit contenir un objet JSON")
        config = {cle.replace("-", "_"): valeur for cle, valeur in config.items()}
        connus = {a.dest for a in parseur._actions} - {"help", "config"}
        inconnus = sorted(set(config) - connus)
        if inconnus:
            parseur.error(f"Clé(s) inconnue(s) dans le fichier de config : {inconnus}")
        parseur.set_defaults(**config)
    args = parseur.parse_args(argv)
    if not args.input:
        parseur.error("--input est obligatoire (ligne de commande ou fichier de config)")
    if isinstance(args.sheet, str) and args.sheet.isdigit():
        args.sheet = int(args.sheet)
    return args


def main(argv: list[str] | None = None) -> int:
    args = lire_arguments(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        params = Parametres(
            window_days=args.window_days,
            max_group_size=args.max_group_size,
            tolerance_cents=args.tolerance_cents,
            time_limit=args.time_limit,
            weight_by_amount=args.weight_by_amount,
            workers=args.workers,
            seed=args.seed,
        )
        df = charger_excel(args.input, args.sheet)
        colonnes = resoudre_colonnes(
            df, {c: getattr(args, f"col_{c}") for c in CHAMPS_COLONNES}
        )
    except (ErreurChargement, ValueError) as exc:
        log.error("%s", exc)
        return CODE_ERREUR_ENTREE

    mouvements, erreurs = valider(df, colonnes)
    if erreurs:
        log.warning("%s", rapport_erreurs(erreurs, len(df)))
        if args.strict:
            log.error("Mode --strict : arrêt à cause des lignes invalides.")
            return CODE_ERREUR_ENTREE
    else:
        log.info("Validation : %d mouvement(s) valide(s), aucune anomalie", len(mouvements))

    try:
        resultat = reconcilier(mouvements, params)
    except ErreurVerification as exc:
        log.error("Vérification finale en échec, aucun fichier écrit : %s", exc)
        return CODE_ERREUR_VERIFICATION

    exporter(args.output, df, resultat, erreurs)
    if not resultat.tout_optimal:
        log.warning(
            "Au moins une composante n'a pas été résolue à l'optimum : le résultat est "
            "valide mais peut-être améliorable (voir la feuille « Résumé »)."
        )
    return CODE_OK


if __name__ == "__main__":
    sys.exit(main())
