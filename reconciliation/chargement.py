"""Chargement du fichier Excel et résolution du mapping de colonnes."""

from __future__ import annotations

import importlib.util
import logging
import unicodedata
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

COLONNES_OBLIGATOIRES = ("montant", "type", "date")
COLONNES_OPTIONNELLES = ("id", "libelle")

# Noms reconnus automatiquement (après normalisation : minuscules, sans accents).
ALIAS = {
    "montant": ("montant", "amount", "somme", "valeur"),
    "type": ("type", "sens", "nature"),
    "date": ("date", "date mouvement", "date operation", "date valeur"),
    "id": ("id", "identifiant", "reference", "ref"),
    "libelle": ("libelle", "label", "description", "intitule"),
}


# calamine (Rust) lit un .xlsx 5 à 10 fois plus vite qu'openpyxl ; repli si absent.
MOTEUR_LECTURE = "calamine" if importlib.util.find_spec("python_calamine") else "openpyxl"


class ErreurChargement(Exception):
    """Fichier illisible ou colonnes obligatoires introuvables."""


def normaliser_texte(valeur: object) -> str:
    """Minuscules, sans accents, espaces superflus retirés."""
    texte = unicodedata.normalize("NFKD", str(valeur))
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return " ".join(texte.replace("_", " ").lower().split())


def charger_excel(chemin: str | Path, feuille: str | int = 0) -> pd.DataFrame:
    """Lit la feuille demandée et renvoie un DataFrame indexé 0..n-1."""
    chemin = Path(chemin)
    if not chemin.exists():
        raise ErreurChargement(f"Fichier introuvable : {chemin}")
    try:
        df = pd.read_excel(chemin, sheet_name=feuille, engine=MOTEUR_LECTURE)
    except Exception as exc:  # fichier corrompu, feuille absente, etc.
        raise ErreurChargement(f"Lecture impossible de {chemin} : {exc}") from exc
    log.info("%d lignes lues dans %s (moteur %s)", len(df), chemin, MOTEUR_LECTURE)
    return df.reset_index(drop=True)


def resoudre_colonnes(
    df: pd.DataFrame, mapping: dict[str, str | None] | None = None
) -> dict[str, str | None]:
    """Associe chaque champ logique à une colonne réelle du fichier.

    `mapping` (champ logique -> nom de colonne) est prioritaire ; à défaut on
    cherche un alias connu, sans tenir compte de la casse ni des accents.
    """
    mapping = {k: v for k, v in (mapping or {}).items() if v}
    par_nom_normalise = {normaliser_texte(c): c for c in df.columns}
    resolu: dict[str, str | None] = {}

    for champ in COLONNES_OBLIGATOIRES + COLONNES_OPTIONNELLES:
        demande = mapping.get(champ)
        if demande is not None:
            if demande in df.columns:
                resolu[champ] = demande
            elif normaliser_texte(demande) in par_nom_normalise:
                resolu[champ] = par_nom_normalise[normaliser_texte(demande)]
            else:
                raise ErreurChargement(
                    f"Colonne « {demande} » (champ {champ}) absente du fichier. "
                    f"Colonnes disponibles : {list(df.columns)}"
                )
            continue
        resolu[champ] = next(
            (par_nom_normalise[a] for a in ALIAS[champ] if a in par_nom_normalise),
            None,
        )

    manquantes = [c for c in COLONNES_OBLIGATOIRES if resolu[c] is None]
    if manquantes:
        raise ErreurChargement(
            f"Colonnes obligatoires introuvables : {manquantes}. "
            f"Colonnes disponibles : {list(df.columns)}. "
            "Utilisez --col-montant / --col-type / --col-date pour les désigner."
        )
    log.debug("Mapping des colonnes : %s", resolu)
    return resolu
