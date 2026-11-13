"""Structures de données partagées entre les modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

METHODE_EXACT = "exact 1-à-1"
METHODE_CPSAT = "CP-SAT"

CREDIT = 1
DEBIT = -1


@dataclass(frozen=True)
class Mouvement:
    """Un mouvement bancaire validé.

    `index` est la position de la ligne dans le fichier d'origine : c'est la
    clé interne, garantie unique même si la colonne `id` contient des doublons.
    """

    index: int
    ident: str
    montant: int  # en centimes, strictement positif
    signe: int  # CREDIT (+1) ou DEBIT (-1)
    date: datetime
    jour: int  # numéro de jour (date.toordinal()), pour les écarts en jours

    @property
    def est_debit(self) -> bool:
        return self.signe == DEBIT

    @property
    def est_credit(self) -> bool:
        return self.signe == CREDIT


@dataclass(frozen=True)
class Parametres:
    """Contraintes métier et réglages du solveur."""

    window_days: int = 30
    max_group_size: int = 20
    tolerance_cents: int = 0
    time_limit: float = 60.0
    weight_by_amount: bool = False
    workers: int = 8
    seed: int = 0

    def __post_init__(self) -> None:
        if self.window_days < 0:
            raise ValueError("window_days doit être >= 0")
        if self.max_group_size < 2:
            raise ValueError("max_group_size doit être >= 2")
        if self.tolerance_cents < 0:
            raise ValueError("tolerance_cents doit être >= 0")
        if self.time_limit <= 0:
            raise ValueError("time_limit doit être > 0")
        if self.workers < 1:
            raise ValueError("workers doit être >= 1")


@dataclass
class Groupe:
    """Un groupe réconcilié : somme des débits = somme des crédits (± tolérance)."""

    membres: list[Mouvement]
    methode: str
    groupe_id: str = ""

    @property
    def total_debit(self) -> int:
        return sum(m.montant for m in self.membres if m.est_debit)

    @property
    def total_credit(self) -> int:
        return sum(m.montant for m in self.membres if m.est_credit)

    @property
    def ecart(self) -> int:
        """Somme signée en centimes (crédits - débits)."""
        return self.total_credit - self.total_debit

    @property
    def nb_debits(self) -> int:
        return sum(1 for m in self.membres if m.est_debit)

    @property
    def nb_credits(self) -> int:
        return sum(1 for m in self.membres if m.est_credit)

    @property
    def etendue_jours(self) -> int:
        jours = [m.jour for m in self.membres]
        return max(jours) - min(jours)


@dataclass
class StatutComposante:
    """Compte rendu de la résolution d'une composante connexe."""

    numero: int
    nb_mouvements: int
    nb_debits: int
    nb_credits: int
    statut: str  # OPTIMAL / FEASIBLE / UNKNOWN / SANS_SOLVEUR
    nb_reconcilies: int = 0
    nb_groupes: int = 0
    duree: float = 0.0


@dataclass
class Resultat:
    """Résultat complet d'une réconciliation."""

    mouvements: list[Mouvement]
    groupes: list[Groupe]
    composantes: list[StatutComposante]
    parametres: Parametres
    duree: float = 0.0
    groupe_par_index: dict[int, Groupe] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.groupe_par_index:
            self.groupe_par_index = {
                m.index: g for g in self.groupes for m in g.membres
            }

    @property
    def non_reconcilies(self) -> list[Mouvement]:
        return [m for m in self.mouvements if m.index not in self.groupe_par_index]

    @property
    def nb_reconcilies(self) -> int:
        return len(self.groupe_par_index)

    @property
    def taux(self) -> float:
        """Taux de réconciliation en pourcentage."""
        if not self.mouvements:
            return 0.0
        return 100.0 * self.nb_reconcilies / len(self.mouvements)

    @property
    def tout_optimal(self) -> bool:
        return all(c.statut in ("OPTIMAL", "SANS_SOLVEUR") for c in self.composantes)
