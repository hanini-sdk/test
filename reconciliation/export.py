"""Export du résultat vers un classeur Excel."""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .types import Resultat
from .validation import ErreurLigne

log = logging.getLogger(__name__)

# xlsxwriter écrit 3 à 4 fois plus vite qu'openpyxl ; repli si absent.
MOTEUR_ECRITURE = "xlsxwriter" if importlib.util.find_spec("xlsxwriter") else "openpyxl"
# Lignes examinées pour estimer la largeur des colonnes.
ECHANTILLON_LARGEUR = 2_000

STATUT_RECONCILIE = "réconcilié"
STATUT_NON_RECONCILIE = "non réconcilié"
STATUT_REJETE = "rejeté (ligne invalide)"


def table_mouvements(df: pd.DataFrame, resultat: Resultat) -> pd.DataFrame:
    """Lignes d'origine enrichies de `groupe_id`, `statut` et `methode`."""
    n = len(df)
    groupe_ids: list[str | None] = [None] * n
    methodes: list[str | None] = [None] * n
    statuts = [STATUT_REJETE] * n
    for m in resultat.mouvements:
        statuts[m.index] = STATUT_NON_RECONCILIE
    for g in resultat.groupes:
        for m in g.membres:
            groupe_ids[m.index] = g.groupe_id
            methodes[m.index] = g.methode
            statuts[m.index] = STATUT_RECONCILIE
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


def _largeurs(table: pd.DataFrame) -> list[int]:
    """Largeur de chaque colonne, estimée sur un échantillon (en-tête compris)."""
    echantillon = table.head(ECHANTILLON_LARGEUR)
    largeurs = []
    for nom in table.columns:
        colonne = echantillon[nom]
        if pd.api.types.is_datetime64_any_dtype(colonne):
            contenu = 10  # JJ/MM/AAAA
        else:
            valeurs = colonne.dropna()
            contenu = int(valeurs.astype(str).str.len().max()) if len(valeurs) else 0
        largeurs.append(min(max(len(str(nom)), contenu, 6) + 2, 60))
    return largeurs


def _mettre_en_forme(classeur: pd.ExcelWriter, nom: str, table: pd.DataFrame) -> None:
    feuille = classeur.sheets[nom]
    if MOTEUR_ECRITURE == "xlsxwriter":
        for position, largeur in enumerate(_largeurs(table)):
            feuille.set_column(position, position, largeur)
        feuille.freeze_panes(1, 0)
    else:
        from openpyxl.utils import get_column_letter

        for position, largeur in enumerate(_largeurs(table), start=1):
            feuille.column_dimensions[get_column_letter(position)].width = largeur
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

    with pd.ExcelWriter(
        chemin, engine=MOTEUR_ECRITURE, datetime_format="DD/MM/YYYY", date_format="DD/MM/YYYY"
    ) as classeur:
        for nom, table in feuilles.items():
            table.to_excel(classeur, sheet_name=nom, index=False)
            _mettre_en_forme(classeur, nom, table)
    log.info("Résultat écrit dans %s", chemin)
    return chemin
