"""Vérification finale, indépendante du solveur, de la solution produite."""

from __future__ import annotations

from .types import Groupe, Parametres


class ErreurVerification(AssertionError):
    """La solution viole une contrainte : ne jamais exporter dans ce cas."""


def verifier_solution(groupes: list[Groupe], params: Parametres) -> None:
    """Lève ErreurVerification si un groupe est invalide ou si un mouvement est en double."""
    vus: dict[int, str] = {}
    for g in groupes:
        nom = g.groupe_id or "(sans id)"
        if abs(g.ecart) > params.tolerance_cents:
            raise ErreurVerification(
                f"Groupe {nom} : écart de {g.ecart} centime(s), "
                f"tolérance {params.tolerance_cents}"
            )
        if g.nb_debits < 1 or g.nb_credits < 1:
            raise ErreurVerification(f"Groupe {nom} : il faut au moins un débit et un crédit")
        if len(g.membres) > params.max_group_size:
            raise ErreurVerification(
                f"Groupe {nom} : {len(g.membres)} mouvements, maximum {params.max_group_size}"
            )
        if g.etendue_jours > params.window_days:
            raise ErreurVerification(
                f"Groupe {nom} : étendue de {g.etendue_jours} jours, "
                f"fenêtre {params.window_days}"
            )
        for m in g.membres:
            if m.index in vus:
                raise ErreurVerification(
                    f"Mouvement {m.ident} présent dans {vus[m.index]} et dans {nom}"
                )
            vus[m.index] = nom
