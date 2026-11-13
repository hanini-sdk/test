"""Validation des lignes et conversion en objets `Mouvement`."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import pandas as pd

from .chargement import normaliser_texte
from .types import CREDIT, DEBIT, Mouvement

log = logging.getLogger(__name__)

TYPES = {"debit": DEBIT, "credit": CREDIT}


@dataclass(frozen=True)
class ErreurLigne:
    """Une anomalie détectée sur une ligne du fichier d'entrée."""

    index: int
    ligne_excel: int  # numéro de ligne tel qu'affiché dans Excel
    ident: str
    champ: str
    valeur: str
    message: str


def _est_vide(valeur: object) -> bool:
    if valeur is None or valeur is pd.NaT or valeur is pd.NA:
        return True
    if isinstance(valeur, float) and math.isnan(valeur):
        return True
    return isinstance(valeur, str) and not valeur.strip()


def montant_en_centimes(valeur: object) -> int:
    """Convertit un montant en centimes entiers, arrondi au plus proche.

    Le passage par `Decimal(str(x))` évite les erreurs binaires des flottants
    (ex. 0.29 * 100 == 28.999999999999996). Les chaînes « 1 234,56 » sont
    acceptées. Lève ValueError si la valeur n'est pas un nombre fini.
    """
    if _est_vide(valeur) or isinstance(valeur, bool):
        raise ValueError("montant manquant")
    if isinstance(valeur, str):
        texte = valeur.strip().replace(" ", "").replace(" ", "").replace(" ", "")
        texte = texte.replace("€", "")
        if "," in texte:
            # Virgule décimale à la française ; les points sont des séparateurs de milliers.
            texte = texte.replace(".", "").replace(",", ".")
    else:
        texte = str(valeur)
    try:
        nombre = Decimal(texte)
    except InvalidOperation as exc:
        raise ValueError("montant non numérique") from exc
    if not nombre.is_finite():
        raise ValueError("montant non numérique")
    return int((nombre * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _convertir_date(valeur: object) -> datetime | None:
    if _est_vide(valeur):
        return None
    if isinstance(valeur, pd.Timestamp):
        return valeur.to_pydatetime()
    if isinstance(valeur, datetime):
        return valeur
    if isinstance(valeur, date):
        return datetime(valeur.year, valeur.month, valeur.day)
    if not isinstance(valeur, str):
        return None  # un nombre isolé n'est pas une date fiable
    texte = valeur.strip()
    # Les dates ISO (AAAA-MM-JJ) sont sans ambiguïté ; sinon on lit jour/mois/année.
    iso = len(texte) >= 10 and texte[4:5] == "-" and texte[:4].isdigit()
    try:
        horodatage = pd.to_datetime(texte, errors="coerce", dayfirst=not iso)
    except (ValueError, TypeError, OverflowError):
        return None
    if pd.isna(horodatage):
        return None
    return horodatage.to_pydatetime()


def valider(
    df: pd.DataFrame, colonnes: dict[str, str | None]
) -> tuple[list[Mouvement], list[ErreurLigne]]:
    """Valide chaque ligne ; renvoie les mouvements valides et la liste des erreurs.

    Une ligne comportant au moins une erreur est exclue de la réconciliation.
    """
    col_id = colonnes.get("id")
    mouvements: list[Mouvement] = []
    erreurs: list[ErreurLigne] = []

    for position, ligne in enumerate(df.to_dict("records")):
        ligne_excel = position + 2  # +1 pour l'en-tête, +1 car Excel compte à partir de 1
        brut_id = ligne[col_id] if col_id else None
        ident = f"L{ligne_excel}" if _est_vide(brut_id) else str(brut_id).strip()
        avant = len(erreurs)

        def signaler(champ: str, valeur: object, message: str) -> None:
            affichee = "" if _est_vide(valeur) else str(valeur)
            erreurs.append(ErreurLigne(position, ligne_excel, ident, champ, affichee, message))

        brut_montant = ligne[colonnes["montant"]]
        centimes = 0
        try:
            centimes = montant_en_centimes(brut_montant)
        except ValueError as exc:
            signaler("montant", brut_montant, str(exc))
        else:
            if centimes == 0:
                signaler("montant", brut_montant, "montant nul")
            elif centimes < 0:
                signaler("montant", brut_montant, "montant négatif")

        brut_type = ligne[colonnes["type"]]
        signe = None if _est_vide(brut_type) else TYPES.get(normaliser_texte(brut_type))
        if signe is None:
            message = (
                "type manquant" if _est_vide(brut_type)
                else "type inconnu (attendu : debit ou credit)"
            )
            signaler("type", brut_type, message)

        brut_date = ligne[colonnes["date"]]
        horodatage = _convertir_date(brut_date)
        if horodatage is None:
            message = "date manquante" if _est_vide(brut_date) else "date illisible"
            signaler("date", brut_date, message)

        if len(erreurs) == avant:
            mouvements.append(
                Mouvement(
                    index=position,
                    ident=ident,
                    montant=centimes,
                    signe=signe,
                    date=horodatage,
                    jour=horodatage.date().toordinal(),
                )
            )

    if col_id:
        vus: dict[str, int] = {}
        for m in mouvements:
            vus[m.ident] = vus.get(m.ident, 0) + 1
        doublons = sorted(i for i, n in vus.items() if n > 1)
        if doublons:
            log.warning(
                "%d identifiant(s) en double dans la colonne « %s » (ex. %s) : "
                "les lignes restent traitées séparément.",
                len(doublons), col_id, ", ".join(doublons[:5]),
            )

    return mouvements, erreurs


def rapport_erreurs(erreurs: list[ErreurLigne], nb_lignes: int) -> str:
    """Rapport lisible des anomalies, regroupé par nature."""
    if not erreurs:
        return "Validation : aucune anomalie."
    lignes_touchees = len({e.index for e in erreurs})
    sortie = [
        f"Validation : {len(erreurs)} anomalie(s) sur {lignes_touchees} ligne(s) "
        f"(sur {nb_lignes}) — ces lignes sont exclues de la réconciliation.",
    ]
    par_message: dict[str, list[ErreurLigne]] = {}
    for e in erreurs:
        par_message.setdefault(e.message, []).append(e)
    for message, groupe in sorted(par_message.items(), key=lambda kv: -len(kv[1])):
        sortie.append(f"  • {message} : {len(groupe)}")
        for e in groupe[:10]:
            valeur = f" (valeur : {e.valeur!r})" if e.valeur else ""
            sortie.append(f"      ligne {e.ligne_excel}, id {e.ident}{valeur}")
        if len(groupe) > 10:
            sortie.append(f"      … et {len(groupe) - 10} autre(s)")
    return "\n".join(sortie)
