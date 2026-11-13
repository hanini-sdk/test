"""Prétraitement : appariements exacts 1-à-1 et découpage en composantes connexes."""

from __future__ import annotations

import logging
from collections import defaultdict

from .types import METHODE_EXACT, Groupe, Mouvement

log = logging.getLogger(__name__)


def apparier_exacts(
    mouvements: list[Mouvement], window_days: int
) -> tuple[list[Groupe], list[Mouvement]]:
    """Apparie un débit et un crédit de même montant dont les dates sont dans la fenêtre.

    Les paires candidates sont servies par écart de dates croissant, de sorte
    que les mouvements les plus proches dans le temps sont appariés en premier.
    Renvoie (groupes de 2 mouvements, mouvements restants).
    """
    debits: dict[int, list[Mouvement]] = defaultdict(list)
    credits: dict[int, list[Mouvement]] = defaultdict(list)
    for m in mouvements:
        (debits if m.est_debit else credits)[m.montant].append(m)

    candidats: list[tuple[int, int, int, Mouvement, Mouvement]] = []
    for montant, liste_debits in debits.items():
        for d in liste_debits:
            for c in credits.get(montant, ()):
                ecart = abs(d.jour - c.jour)
                if ecart <= window_days:
                    candidats.append((ecart, d.index, c.index, d, c))
    candidats.sort(key=lambda t: t[:3])  # écart, puis ordre du fichier (déterministe)

    pris: set[int] = set()
    groupes: list[Groupe] = []
    for _, _, _, d, c in candidats:
        if d.index in pris or c.index in pris:
            continue
        pris.update((d.index, c.index))
        groupes.append(Groupe(membres=[d, c], methode=METHODE_EXACT))

    restants = [m for m in mouvements if m.index not in pris]
    log.info(
        "Prétraitement : %d appariement(s) exact(s) 1-à-1, %d mouvement(s) restant(s)",
        len(groupes), len(restants),
    )
    return groupes, restants


def composantes_connexes(
    mouvements: list[Mouvement], window_days: int
) -> list[list[Mouvement]]:
    """Composantes connexes du graphe « deux mouvements à au plus W jours l'un de l'autre ».

    Sur un axe temporel, deux mouvements sont dans la même composante si et
    seulement si aucun « trou » de plus de W jours ne les sépare : il suffit de
    trier par date et de couper à chaque écart consécutif supérieur à W.
    """
    if not mouvements:
        return []
    tries = sorted(mouvements, key=lambda m: (m.jour, m.index))
    composantes = [[tries[0]]]
    for precedent, courant in zip(tries, tries[1:]):
        if courant.jour - precedent.jour > window_days:
            composantes.append([])
        composantes[-1].append(courant)
    log.info("Prétraitement : %d composante(s) connexe(s)", len(composantes))
    return composantes
