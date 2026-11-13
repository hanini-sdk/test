"""Construction du modèle CP-SAT d'une composante."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .types import Mouvement, Parametres

log = logging.getLogger(__name__)


@dataclass
class ModeleComposante:
    """Modèle CP-SAT et accès à ses variables."""

    modele: cp_model.CpModel
    mouvements: list[Mouvement]
    x: list[list[cp_model.IntVar]]  # x[i][k] : mouvement i affecté au groupe k
    u: list[cp_model.IntVar]  # u[k] : groupe k utilisé

    @property
    def nb_groupes_max(self) -> int:
        return len(self.u)


def construire_modele(mouvements: list[Mouvement], params: Parametres) -> ModeleComposante:
    """Modèle d'affectation des mouvements d'une composante à K groupes équilibrés.

    K = min(nb débits, nb crédits) : chaque groupe contient au moins un débit
    et un crédit, il ne peut donc pas y avoir davantage de groupes.
    """
    modele = cp_model.CpModel()
    n = len(mouvements)
    nb_debits = sum(1 for m in mouvements if m.est_debit)
    K = min(nb_debits, n - nb_debits)
    groupes = range(K)

    x = [[modele.new_bool_var(f"x_{m.index}_{k}") for k in groupes] for m in mouvements]
    u = [modele.new_bool_var(f"u_{k}") for k in groupes]

    # Unicité : un mouvement appartient à au plus un groupe.
    for i in range(n):
        modele.add_at_most_one(x[i])

    indices_debits = [i for i, m in enumerate(mouvements) if m.est_debit]
    indices_credits = [i for i, m in enumerate(mouvements) if m.est_credit]
    tol = params.tolerance_cents

    for k in groupes:
        # Équilibre : somme signée nulle, ou dans [-tol, +tol].
        somme_signee = sum(m.signe * m.montant * x[i][k] for i, m in enumerate(mouvements))
        if tol == 0:
            modele.add(somme_signee == 0)
        else:
            modele.add(somme_signee <= tol)
            modele.add(somme_signee >= -tol)

        # Groupe valide : aucun membre si inutilisé, au moins un débit et un crédit sinon.
        for i in range(n):
            modele.add_implication(x[i][k], u[k])
        modele.add(sum(x[i][k] for i in indices_debits) >= u[k])
        modele.add(sum(x[i][k] for i in indices_credits) >= u[k])

        # Taille maximale.
        modele.add(sum(x[i][k] for i in range(n)) <= params.max_group_size)

    # Fenêtre temporelle : deux mouvements trop éloignés ne cohabitent pas.
    ordre = sorted(range(n), key=lambda i: mouvements[i].jour)
    nb_conflits = 0
    for a, i in enumerate(ordre):
        for j in ordre[a + 1:]:
            if mouvements[j].jour - mouvements[i].jour > params.window_days:
                nb_conflits += 1
                for k in groupes:
                    modele.add_at_most_one((x[i][k], x[j][k]))

    # Symétrie : les groupes utilisés sont les premiers.
    for k in range(K - 1):
        modele.add_implication(u[k + 1], u[k])

    # Objectif lexicographique : d'abord couvrir un maximum de mouvements (ou de
    # montant), puis utiliser un minimum de groupes. Le poids doit dépasser K
    # pour que la somme des u ne compense jamais un mouvement réconcilié.
    poids = max(1000, K + 1)
    if params.weight_by_amount:
        couverture = sum(m.montant * x[i][k] for i, m in enumerate(mouvements) for k in groupes)
    else:
        couverture = sum(x[i][k] for i in range(n) for k in groupes)
    modele.maximize(poids * couverture - sum(u))

    log.debug(
        "Modèle : %d mouvements, K=%d, %d variables x, %d paire(s) hors fenêtre",
        n, K, n * K, nb_conflits,
    )
    return ModeleComposante(modele=modele, mouvements=mouvements, x=x, u=u)
