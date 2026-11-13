#!/usr/bin/env python3
"""Génère un petit fichier Excel de mouvements pour essayer la réconciliation.

Le jeu contient, sur trois périodes séparées de plus de 30 jours :
  - des paires exactes débit = crédit ;
  - des groupes 1 débit = N crédits, N débits = 1 crédit et N débits = M crédits ;
  - des mouvements isolés sans contrepartie ;
  - un groupe équilibré mais étalé sur plus de 30 jours (non réconciliable par défaut) ;
  - trois lignes invalides (montant négatif, type inconnu, date manquante).

Usage :
    python generer_donnees_test.py [--output mouvements.xlsx] [--seed 42]
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta

import pandas as pd


def _decouper(total: int, parts: int, rng: random.Random) -> list[int]:
    """Découpe `total` centimes en `parts` montants strictement positifs."""
    coupes = sorted(rng.sample(range(1, total), parts - 1))
    return [b - a for a, b in zip([0] + coupes, coupes + [total])]


def generer(seed: int = 42) -> pd.DataFrame:
    rng = random.Random(seed)
    lignes: list[dict] = []

    def ajouter(montant_cents: int, sens: str, date: datetime, libelle: str) -> None:
        lignes.append(
            {"montant": montant_cents / 100, "type": sens, "date": date, "libelle": libelle}
        )

    periodes = [datetime(2024, 1, 5), datetime(2024, 3, 20), datetime(2024, 6, 3)]
    for p, debut in enumerate(periodes, start=1):
        def jour() -> datetime:
            return debut + timedelta(days=rng.randint(0, 20))

        # Paires exactes.
        for n in range(4):
            montant = rng.randint(5_000, 200_000)
            d = jour()
            ajouter(montant, "debit", d, f"P{p} paire {n + 1} - prélèvement")
            ajouter(montant, "credit", d + timedelta(days=rng.randint(0, 5)),
                    f"P{p} paire {n + 1} - remboursement")

        # 1 débit = N crédits.
        total = rng.randint(50_000, 300_000)
        ajouter(total, "debit", jour(), f"P{p} virement global")
        for n, part in enumerate(_decouper(total, 3, rng), start=1):
            ajouter(part, "credit", jour(), f"P{p} encaissement partiel {n}")

        # N débits = 1 crédit.
        total = rng.randint(50_000, 300_000)
        ajouter(total, "credit", jour(), f"P{p} remise groupée")
        for n, part in enumerate(_decouper(total, 4, rng), start=1):
            ajouter(part, "debit", jour(), f"P{p} facture {n}")

        # N débits = M crédits.
        total = rng.randint(100_000, 400_000)
        for n, part in enumerate(_decouper(total, 2, rng), start=1):
            ajouter(part, "debit", jour(), f"P{p} lot débit {n}")
        for n, part in enumerate(_decouper(total, 3, rng), start=1):
            ajouter(part, "credit", jour(), f"P{p} lot crédit {n}")

        # Mouvements sans contrepartie (montants premiers entre eux, peu de chances de tomber juste).
        for n in range(3):
            sens = rng.choice(["debit", "credit"])
            ajouter(rng.randint(1_000, 90_000) * 7 + 3, sens, jour(), f"P{p} isolé {n + 1}")

    # Groupe équilibré mais trop étalé : 45 jours entre le débit et le second crédit.
    ajouter(77_777, "debit", datetime(2024, 8, 1), "Hors fenêtre - débit")
    ajouter(40_000, "credit", datetime(2024, 8, 3), "Hors fenêtre - crédit 1")
    ajouter(37_777, "credit", datetime(2024, 9, 15), "Hors fenêtre - crédit 2")

    # Variantes d'écriture du type, toutes valides.
    lignes[0]["type"] = "Débit"
    lignes[1]["type"] = " CREDIT "
    lignes[2]["type"] = "DEBIT"
    lignes[3]["type"] = "crédit"

    rng.shuffle(lignes)

    # Lignes invalides, pour illustrer le rapport d'erreurs.
    lignes.append({"montant": -120.50, "type": "debit", "date": datetime(2024, 1, 10),
                   "libelle": "Invalide - montant négatif"})
    lignes.append({"montant": 300.00, "type": "virement", "date": datetime(2024, 1, 12),
                   "libelle": "Invalide - type inconnu"})
    lignes.append({"montant": 45.90, "type": "credit", "date": None,
                   "libelle": "Invalide - date manquante"})

    df = pd.DataFrame(lignes)
    df.insert(0, "id", [f"MVT-{i:04d}" for i in range(1, len(df) + 1)])
    return df


def main() -> None:
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--output", "-o", default="mouvements.xlsx")
    parseur.add_argument("--seed", type=int, default=42)
    args = parseur.parse_args()

    df = generer(args.seed)
    with pd.ExcelWriter(args.output, engine="openpyxl", datetime_format="DD/MM/YYYY") as classeur:
        df.to_excel(classeur, index=False, sheet_name="Mouvements")
    print(f"{len(df)} lignes écrites dans {args.output}")


if __name__ == "__main__":
    main()
