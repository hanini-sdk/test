"""Export du résultat vers un classeur Excel."""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .types import Resultat
from .validation import ErreurLigne

log = logging.getLogger(__name__)

STATUT_RECONCILIE = "réconcilié"
STATUT_NON_RECONCILIE = "non réconcilié"
STATUT_REJETE = "rejeté (ligne invalide)"


def table_mouvements(df: pd.DataFrame, resultat: Resultat) -> pd.DataFrame:
    """Lignes d'origine enrichies de `groupe_id`, `statut` et `methode`."""
    valides = {m.index for m in resultat.mouvements}
    groupe_ids, statuts, methodes = [], [], []
    for position in range(len(df)):
        groupe = resultat.groupe_par_index.get(position)
        if groupe is not None:
            groupe_ids.append(groupe.groupe_id)
            statuts.append(STATUT_RECONCILIE)
            methodes.append(groupe.methode)
        else:
            groupe_ids.append(None)
            statuts.append(STATUT_NON_RECONCILIE if position in valides else STATUT_REJETE)
            methodes.append(None)
    sortie = df.copy()
    sortie["groupe_id"] = groupe_ids
    sortie["statut"] = statuts
    sortie["methode"] = methodes
    return sortie


def table_groupes(resultat: Resultat) -> pd.DataFrame:
    lignes = []
    for g in resultat.groupes:
        dates = [m.date for m in g.membres]
        lignes.append(
            {
                "groupe_id": g.groupe_id,
                "methode": g.methode,
                "total_debit": g.total_debit / 100,
                "total_credit": g.total_credit / 100,
                "ecart": g.ecart / 100,
                "nb_debits": g.nb_debits,
                "nb_credits": g.nb_credits,
                "date_min": min(dates),
                "date_max": max(dates),
                "etendue_jours": g.etendue_jours,
            }
        )
    colonnes = [
        "groupe_id", "methode", "total_debit", "total_credit", "ecart",
        "nb_debits", "nb_credits", "date_min", "date_max", "etendue_jours",
    ]
    return pd.DataFrame(lignes, columns=colonnes)


def table_resume(resultat: Resultat, nb_rejetes: int = 0) -> pd.DataFrame:
    lignes: list[tuple[str, object]] = [
        ("Nombre total de mouvements", len(resultat.mouvements)),
        ("Nombre de mouvements réconciliés", resultat.nb_reconcilies),
        ("Nombre de mouvements non réconciliés", len(resultat.non_reconcilies)),
        ("Taux de réconciliation (%)", round(resultat.taux, 2)),
        ("Nombre de groupes", len(resultat.groupes)),
        ("Lignes rejetées à la validation", nb_rejetes),
        ("Temps total d'exécution (s)", round(resultat.duree, 2)),
        (
            "Optimalité prouvée sur toutes les composantes",
            "oui" if resultat.tout_optimal else "NON",
        ),
    ]
    for c in resultat.composantes:
        lignes.append(
            (
                f"Composante {c.numero} ({c.nb_debits} débits, {c.nb_credits} crédits)",
                f"{c.statut} — {c.nb_reconcilies}/{c.nb_mouvements} réconciliés, "
                f"{c.nb_groupes} groupe(s), {c.duree:.1f} s",
            )
        )
    for nom, valeur in asdict(resultat.parametres).items():
        lignes.append((f"Paramètre : {nom}", str(valeur)))
    table = pd.DataFrame(lignes, columns=["Indicateur", "Valeur"])
    table["Valeur"] = table["Valeur"].astype(object)
    return table


def _ajuster_largeurs(feuille) -> None:
    for colonne in feuille.columns:
        largeur = max((len(str(c.value)) for c in colonne if c.value is not None), default=8)
        feuille.column_dimensions[colonne[0].column_letter].width = min(largeur + 2, 60)
    feuille.freeze_panes = "A2"


def exporter(
    chemin: str | Path,
    df: pd.DataFrame,
    resultat: Resultat,
    erreurs: list[ErreurLigne] | None = None,
) -> Path:
    """Écrit le classeur de résultat et renvoie son chemin."""
    chemin = Path(chemin)
    erreurs = erreurs or []
    mouvements = table_mouvements(df, resultat)
    feuilles = {
        "Mouvements": mouvements,
        "Groupes": table_groupes(resultat),
        "Non réconciliés": mouvements[mouvements["statut"] == STATUT_NON_RECONCILIE],
        "Résumé": table_resume(resultat, nb_rejetes=len({e.index for e in erreurs})),
    }
    if erreurs:
        feuilles["Erreurs"] = pd.DataFrame(
            [
                {
                    "ligne_excel": e.ligne_excel,
                    "id": e.ident,
                    "champ": e.champ,
                    "valeur": e.valeur,
                    "anomalie": e.message,
                }
                for e in erreurs
            ]
        )

    with pd.ExcelWriter(chemin, engine="openpyxl", datetime_format="DD/MM/YYYY") as classeur:
        for nom, table in feuilles.items():
            table.to_excel(classeur, sheet_name=nom, index=False)
            _ajuster_largeurs(classeur.sheets[nom])
    log.info("Résultat écrit dans %s", chemin)
    return chemin
