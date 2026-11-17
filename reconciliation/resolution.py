"""Résolution CP-SAT par composante et orchestration de la réconciliation."""

from __future__ import annotations

import logging
import time

from ortools.sat.python import cp_model

from .grande_echelle import reconcilier_par_blocs
from .modele import construire_modele
from .pretraitement import apparier_exacts, composantes_connexes
from .types import (
    METHODE_CPSAT,
    Groupe,
    Mouvement,
    Parametres,
    Resultat,
    StatutComposante,
)
from .verification import verifier_solution

log = logging.getLogger(__name__)

# Au-delà de ce nombre de variables x[m,k], la preuve d'optimalité devient improbable.
SEUIL_GROS_MODELE = 20_000


def resoudre_composante(
    mouvements: list[Mouvement], params: Parametres, numero: int = 1
) -> tuple[list[Groupe], StatutComposante]:
    """Résout une composante ; renvoie ses groupes et un compte rendu.

    Une solution non prouvée optimale (FEASIBLE) est conservée et signalée.
    """
    nb_debits = sum(1 for m in mouvements if m.est_debit)
    nb_credits = len(mouvements) - nb_debits
    compte_rendu = StatutComposante(
        numero=numero,
        nb_mouvements=len(mouvements),
        nb_debits=nb_debits,
        nb_credits=nb_credits,
        statut="SANS_SOLVEUR",
    )
    if nb_debits == 0 or nb_credits == 0:
        log.debug("Composante %d : un seul type de mouvement, rien à réconcilier", numero)
        return [], compte_rendu

    debut = time.perf_counter()
    mc = construire_modele(mouvements, params)
    nb_variables = len(mouvements) * mc.nb_groupes_max
    if nb_variables > SEUIL_GROS_MODELE:
        log.warning(
            "Composante %d : modèle volumineux (%d mouvements × %d groupes = %d variables). "
            "Le résultat risque de ne pas être optimal ; réduisez --window-days ou "
            "augmentez --time-limit.",
            numero, len(mouvements), mc.nb_groupes_max, nb_variables,
        )

    solveur = cp_model.CpSolver()
    solveur.parameters.max_time_in_seconds = float(params.time_limit)
    solveur.parameters.num_workers = params.workers
    solveur.parameters.random_seed = params.seed
    code = solveur.solve(mc.modele)
    compte_rendu.duree = time.perf_counter() - debut

    if code == cp_model.OPTIMAL:
        compte_rendu.statut = "OPTIMAL"
    elif code == cp_model.FEASIBLE:
        compte_rendu.statut = "FEASIBLE"
    else:
        # Le groupement vide est toujours admissible : INFEASIBLE est impossible,
        # ce cas correspond donc à un arrêt avant toute solution.
        compte_rendu.statut = "UNKNOWN"

    groupes: list[Groupe] = []
    if code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for k in range(mc.nb_groupes_max):
            membres = [m for i, m in enumerate(mouvements) if solveur.boolean_value(mc.x[i][k])]
            if membres:
                membres.sort(key=lambda m: (m.jour, m.index))
                groupes.append(Groupe(membres=membres, methode=METHODE_CPSAT))

    compte_rendu.nb_groupes = len(groupes)
    compte_rendu.nb_reconcilies = sum(len(g.membres) for g in groupes)
    optimal = compte_rendu.statut == "OPTIMAL"
    log.log(
        logging.DEBUG if optimal else logging.WARNING,
        "Composante %d : %s — %d/%d mouvement(s) réconcilié(s) en %d groupe(s) (%.1f s)%s",
        numero, compte_rendu.statut, compte_rendu.nb_reconcilies, len(mouvements),
        len(groupes), compte_rendu.duree,
        "" if optimal else " — optimalité NON prouvée",
    )
    return groupes, compte_rendu


def reconcilier(mouvements: list[Mouvement], params: Parametres | None = None) -> Resultat:
    """Pipeline complet : appariements exacts, composantes, CP-SAT, fusion, vérification."""
    params = params or Parametres()
    debut = time.perf_counter()

    groupes, restants = apparier_exacts(mouvements, params.window_days)
    composantes = composantes_connexes(restants, params.window_days)
    petites = [c for c in composantes if len(c) <= params.seuil_exact]
    grosses = [c for c in composantes if len(c) > params.seuil_exact]
    comptes_rendus: list[StatutComposante] = []

    if grosses:
        log.info(
            "%d grosse(s) composante(s) (> %d mouvements, %d au total) : résolution par blocs",
            len(grosses), params.seuil_exact, sum(map(len, grosses)),
        )
        debut_blocs = time.perf_counter()
        groupes_blocs, reste = reconcilier_par_blocs([m for c in grosses for m in c], params)
        groupes.extend(groupes_blocs)
        duree_blocs = time.perf_counter() - debut_blocs
        reconcilies = {m.index for g in groupes_blocs for m in g.membres}
        composante_de = {m.index: n for n, c in enumerate(grosses) for m in c}
        groupes_par_composante = [0] * len(grosses)
        for g in groupes_blocs:
            groupes_par_composante[composante_de[g.membres[0].index]] += 1
        for n, c in enumerate(grosses):
            nb_debits = sum(1 for m in c if m.est_debit)
            comptes_rendus.append(StatutComposante(
                numero=0, nb_mouvements=len(c), nb_debits=nb_debits,
                nb_credits=len(c) - nb_debits, statut="HEURISTIQUE",
                nb_reconcilies=sum(1 for m in c if m.index in reconcilies),
                nb_groupes=groupes_par_composante[n],
                duree=duree_blocs * len(c) / max(1, sum(map(len, grosses))),
            ))
        # Les restes devenus petits passent encore par le modèle exact.
        petites += [c for c in composantes_connexes(reste, params.window_days)
                    if len(c) <= params.seuil_exact]

    for composante in petites:
        nouveaux, compte_rendu = resoudre_composante(
            composante, params, numero=len(comptes_rendus) + 1
        )
        groupes.extend(nouveaux)
        comptes_rendus.append(compte_rendu)
    for numero, compte_rendu in enumerate(comptes_rendus, start=1):
        compte_rendu.numero = numero

    groupes.sort(key=lambda g: min((m.jour, m.index) for m in g.membres))
    largeur = max(4, len(str(len(groupes))))
    for numero, g in enumerate(groupes, start=1):
        g.groupe_id = f"G{numero:0{largeur}d}"

    verifier_solution(groupes, params)

    resultat = Resultat(
        mouvements=mouvements,
        groupes=groupes,
        composantes=comptes_rendus,
        parametres=params,
        duree=time.perf_counter() - debut,
    )
    log.info(
        "Réconciliation : %d/%d mouvement(s) (%.1f %%) en %d groupe(s), %.1f s",
        resultat.nb_reconcilies, len(mouvements), resultat.taux,
        len(groupes), resultat.duree,
    )
    return resultat
