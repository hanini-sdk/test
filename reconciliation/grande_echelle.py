"""Résolution heuristique des grosses composantes (volumes de 10⁴ à 10⁶ mouvements).

Le modèle CP-SAT complet (`modele.py`) compte n × K variables : il est exact mais
inutilisable au-delà de quelques dizaines de mouvements denses. Pour les grosses
composantes, on procède par blocs :

1. la composante, triée par date, est découpée en blocs d'au plus `taille_bloc`
   mouvements ;
2. dans chaque bloc, une recherche « meet-in-the-middle » vectorisée (numpy)
   énumère toutes les combinaisons équilibrées de 2 à `taille_combinaison`
   mouvements (1-1, 1-2, 2-1, 1-3, 2-2, 3-1…) respectant fenêtre et tolérance ;
3. CP-SAT choisit parmi ces candidats un ensemble sans chevauchement qui
   maximise la couverture (problème de « set packing », résolu en une fraction
   de seconde) ;
4. les blocs, indépendants, sont résolus en parallèle ; plusieurs passes à
   frontières décalées rattrapent les groupes à cheval sur deux blocs.

Les groupes produits sont valides (vérifiés comme les autres) mais l'optimalité
globale n'est pas prouvée : le statut des composantes est `HEURISTIQUE`.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from ortools.sat.python import cp_model

from .types import METHODE_BLOCS, Groupe, Mouvement, Parametres

log = logging.getLogger(__name__)

# Au-delà, les candidats d'un bloc sont tronqués (les plus petites combinaisons d'abord).
PLAFOND_CANDIDATS = 200_000


def _plages(lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Déplie les intervalles [lo[i], hi[i]) : renvoie (i répété, position)."""
    nb = hi - lo
    total = int(nb.sum())
    if total == 0:
        vide = np.empty(0, dtype=np.int64)
        return vide, vide
    proprietaire = np.repeat(np.arange(len(lo)), nb)
    decalage = np.cumsum(nb) - nb
    position = np.arange(total) - decalage[proprietaire] + lo[proprietaire]
    return proprietaire, position


def _filtrer(groupes: np.ndarray, valeurs: np.ndarray, jours: np.ndarray,
             params: Parametres) -> np.ndarray:
    """Garde les combinaisons dans la fenêtre, avec au moins un débit et un crédit."""
    if len(groupes) == 0:
        return groupes
    j = jours[groupes]
    ok = j.max(axis=1) - j.min(axis=1) <= params.window_days
    s = valeurs[groupes]
    ok &= (s > 0).any(axis=1) & (s < 0).any(axis=1)
    return groupes[ok]


def candidats_bloc(valeurs: np.ndarray, jours: np.ndarray, params: Parametres) -> list[np.ndarray]:
    """Combinaisons équilibrées d'un bloc, en indices locaux (une matrice par taille).

    `valeurs` : montants signés en centimes (crédit > 0, débit < 0).
    Toute combinaison de 2 à 4 éléments s'écrit « singleton + paire » ou
    « paire + paire » : on trie les sommes de paires et on cherche, par
    dichotomie, celles qui compensent un singleton ou une autre paire.
    """
    tol = params.tolerance_cents
    taille_max = min(params.taille_combinaison, params.max_group_size)
    n = len(valeurs)
    resultat: list[np.ndarray] = []
    if n < 2:
        return resultat

    # Paires dans la fenêtre (i < j).
    I, J = np.triu_indices(n, 1)
    proches = np.abs(jours[I] - jours[J]) <= params.window_days
    I, J = I[proches], J[proches]
    S = valeurs[I] + valeurs[J]

    paires = np.abs(S) <= tol
    resultat.append(_filtrer(np.stack([I[paires], J[paires]], axis=1), valeurs, jours, params))
    if taille_max < 3 or len(S) == 0:
        return resultat

    ordre = np.argsort(S, kind="stable")
    S_tries = S[ordre]

    # Taille 3 : singleton k + paire (i, j), avec k < i < j pour l'unicité.
    lo = np.searchsorted(S_tries, -valeurs - tol, side="left")
    hi = np.searchsorted(S_tries, -valeurs + tol, side="right")
    k, pos = _plages(lo, hi)
    p = ordre[pos]
    garde = k < I[p]
    trios = np.stack([k[garde], I[p][garde], J[p][garde]], axis=1)
    resultat.append(_filtrer(trios, valeurs, jours, params))

    if taille_max >= 4:
        # Taille 4 : paire (i, j) + paire (k, l), avec i < j < k < l pour l'unicité.
        lo = np.searchsorted(S_tries, -S - tol, side="left")
        hi = np.searchsorted(S_tries, -S + tol, side="right")
        a, pos = _plages(lo, hi)
        b = ordre[pos]
        garde = J[a] < I[b]
        a, b = a[garde], b[garde]
        quads = np.stack([I[a], J[a], I[b], J[b]], axis=1)
        resultat.append(_filtrer(quads, valeurs, jours, params))

    return resultat


def _choisir(candidats: list[np.ndarray], valeurs: np.ndarray, params: Parametres,
             limite: float) -> list[np.ndarray]:
    """Set packing CP-SAT : sous-ensemble disjoint de candidats de couverture maximale."""
    tous = [ligne for matrice in candidats for ligne in matrice]
    if not tous:
        return []
    if len(tous) > PLAFOND_CANDIDATS:
        tous.sort(key=len)
        tous = tous[:PLAFOND_CANDIDATS]

    modele = cp_model.CpModel()
    y = [modele.new_bool_var("") for _ in tous]
    par_mouvement: dict[int, list] = {}
    for var, membres in zip(y, tous):
        for i in membres:
            par_mouvement.setdefault(int(i), []).append(var)
    for variables in par_mouvement.values():
        if len(variables) > 1:
            modele.add_at_most_one(variables)

    # Couverture seule : ajouter « minimiser le nombre de groupes » rend la preuve
    # bien plus lente pour un gain nul (les combinaisons font au plus 4 mouvements).
    if params.weight_by_amount:
        gains = [int(np.abs(valeurs[m]).sum()) for m in tous]
    else:
        gains = [len(m) for m in tous]
    modele.maximize(sum(g * v for g, v in zip(gains, y)))

    solveur = cp_model.CpSolver()
    solveur.parameters.max_time_in_seconds = limite
    solveur.parameters.num_workers = 1
    # Relaxation linéaire renforcée : bien plus efficace sur ce set packing en mono-thread.
    solveur.parameters.linearization_level = 2
    solveur.parameters.random_seed = params.seed
    code = solveur.solve(modele)
    if code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return []
    return [m for m, v in zip(tous, y) if solveur.boolean_value(v)]


def resoudre_bloc(bloc: list[Mouvement], params: Parametres) -> list[Groupe]:
    valeurs = np.fromiter((m.signe * m.montant for m in bloc), dtype=np.int64, count=len(bloc))
    jours = np.fromiter((m.jour for m in bloc), dtype=np.int64, count=len(bloc))
    candidats = candidats_bloc(valeurs, jours, params)
    choisis = _choisir(candidats, valeurs, params, limite=params.temps_bloc)
    groupes = []
    for membres in choisis:
        mvts = sorted((bloc[int(i)] for i in membres), key=lambda m: (m.jour, m.index))
        groupes.append(Groupe(membres=mvts, methode=METHODE_BLOCS))
    return groupes


def _decouper(mouvements: list[Mouvement], taille: int, decalage: int) -> list[list[Mouvement]]:
    tries = sorted(mouvements, key=lambda m: (m.jour, m.index))
    bornes = [0] + list(range(decalage or taille, len(tries), taille)) + [len(tries)]
    return [tries[a:b] for a, b in zip(bornes, bornes[1:]) if b > a]


def reconcilier_par_blocs(
    mouvements: list[Mouvement], params: Parametres
) -> tuple[list[Groupe], list[Mouvement]]:
    """Passes successives par blocs ; renvoie (groupes, mouvements restants)."""
    restants = list(mouvements)
    groupes: list[Groupe] = []
    nb_threads = params.processus or os.cpu_count() or 1

    with ThreadPoolExecutor(max_workers=nb_threads) as pool:
        for passe in range(params.passes):
            if not restants:
                break
            debut = time.perf_counter()
            # Passes paires : frontières alignées ; impaires : décalées d'un demi-bloc.
            decalage = 0 if passe % 2 == 0 else params.taille_bloc // 2
            blocs = _decouper(restants, params.taille_bloc, decalage)
            nouveaux = [g for lot in pool.map(lambda b: resoudre_bloc(b, params), blocs)
                        for g in lot]
            pris = {m.index for g in nouveaux for m in g.membres}
            restants = [m for m in restants if m.index not in pris]
            groupes.extend(nouveaux)
            log.info(
                "Passe %d : %d bloc(s), %d groupe(s), %d mouvement(s) réconcilié(s), "
                "%d restant(s) (%.1f s)",
                passe + 1, len(blocs), len(nouveaux), len(pris), len(restants),
                time.perf_counter() - debut,
            )
            if not nouveaux and passe >= 1:
                break
    return groupes, restants
