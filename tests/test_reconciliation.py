"""Tests unitaires et de bout en bout de la réconciliation."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import reconcilier as cli  # noqa: E402
from generer_donnees_test import generer  # noqa: E402
from reconciliation import Parametres, reconcilier  # noqa: E402
from reconciliation.chargement import ErreurChargement, resoudre_colonnes  # noqa: E402
from reconciliation.pretraitement import apparier_exacts, composantes_connexes  # noqa: E402
from reconciliation.types import CREDIT, DEBIT, METHODE_CPSAT, METHODE_EXACT, Groupe, Mouvement  # noqa: E402
from reconciliation.validation import montant_en_centimes, rapport_erreurs, valider  # noqa: E402
from reconciliation.verification import ErreurVerification, verifier_solution  # noqa: E402

J0 = datetime(2024, 1, 1)
COLONNES = {"montant": "montant", "type": "type", "date": "date", "id": None, "libelle": None}


def mouvements(*lignes: tuple[float, str, int]) -> list[Mouvement]:
    """Construit des mouvements à partir de (montant en euros, type, jour relatif)."""
    resultat = []
    for i, (montant, sens, jour) in enumerate(lignes):
        date = J0 + timedelta(days=jour)
        resultat.append(
            Mouvement(
                index=i,
                ident=f"M{i}",
                montant=montant_en_centimes(montant),
                signe=DEBIT if sens == "debit" else CREDIT,
                date=date,
                jour=date.date().toordinal(),
            )
        )
    return resultat


def params(**kw) -> Parametres:
    kw.setdefault("time_limit", 10)
    return Parametres(**kw)


def idents(groupe: Groupe) -> set[str]:
    return {m.ident for m in groupe.membres}


# --------------------------------------------------------------------------- solveur


def test_un_debit_egale_deux_credits():
    res = reconcilier(mouvements((100, "debit", 0), (60, "credit", 1), (40, "credit", 2)), params())
    assert len(res.groupes) == 1
    groupe = res.groupes[0]
    assert idents(groupe) == {"M0", "M1", "M2"}
    assert groupe.methode == METHODE_CPSAT
    assert groupe.ecart == 0
    assert res.non_reconcilies == []
    assert res.taux == 100.0
    assert [c.statut for c in res.composantes] == ["OPTIMAL"]


def test_sans_solution():
    res = reconcilier(mouvements((100, "debit", 0), (60, "credit", 1), (30, "credit", 2)), params())
    assert res.groupes == []
    assert len(res.non_reconcilies) == 3
    assert res.taux == 0.0


def test_fenetre_temporelle():
    donnees = mouvements((100, "debit", 0), (60, "credit", 2), (40, "credit", 45))
    assert reconcilier(donnees, params(window_days=30)).groupes == []
    res = reconcilier(donnees, params(window_days=60))
    assert len(res.groupes) == 1 and len(res.groupes[0].membres) == 3


def test_fenetre_dans_une_meme_composante():
    # Les trois mouvements sont reliés de proche en proche (0-20-40) et forment une
    # seule composante, mais le groupe complet s'étalerait sur 40 jours > 30.
    donnees = mouvements((100, "debit", 20), (60, "credit", 0), (40, "credit", 40))
    assert len(composantes_connexes(donnees, 30)) == 1
    assert reconcilier(donnees, params(window_days=30)).groupes == []


def test_tolerance():
    donnees = mouvements((100, "debit", 0), (60, "credit", 1), (39.98, "credit", 2))
    assert reconcilier(donnees, params(tolerance_cents=0)).groupes == []
    assert reconcilier(donnees, params(tolerance_cents=1)).groupes == []
    res = reconcilier(donnees, params(tolerance_cents=2))
    assert len(res.groupes) == 1
    assert res.groupes[0].ecart == -2


def test_taille_max_de_groupe():
    donnees = mouvements((100, "debit", 0), (50, "credit", 0), (30, "credit", 0), (20, "credit", 0))
    assert reconcilier(donnees, params(max_group_size=3)).groupes == []
    assert len(reconcilier(donnees, params(max_group_size=4)).groupes) == 1


def test_plusieurs_debits_plusieurs_credits():
    # Aucun sous-ensemble plus petit n'est équilibré : 70 + 50 = 80 + 40.
    res = reconcilier(
        mouvements((70, "debit", 0), (50, "debit", 1), (80, "credit", 2), (40, "credit", 3)),
        params(),
    )
    assert len(res.groupes) == 1
    assert (res.groupes[0].nb_debits, res.groupes[0].nb_credits) == (2, 2)


def test_maximise_le_nombre_de_mouvements():
    donnees = mouvements(
        (100, "debit", 0), (99, "credit", 0), (50, "credit", 0), (30, "credit", 0), (20, "credit", 0),
        (99.5, "debit", 0),
    )
    res = reconcilier(donnees, params())
    # Meilleure couverture : {100 ; 50, 30, 20} = 4 mouvements ; 99 et 99,50 restent.
    assert res.nb_reconcilies == 4
    assert {m.ident for m in res.non_reconcilies} == {"M1", "M5"}


def test_minimise_le_nombre_de_groupes():
    # Deux groupes équilibrés indépendants fusionnent en un seul, à couverture égale.
    donnees = mouvements(
        (100, "debit", 0), (60, "credit", 0), (40, "credit", 0),
        (200, "debit", 1), (150, "credit", 1), (50, "credit", 1),
    )
    res = reconcilier(donnees, params())
    assert res.nb_reconcilies == 6
    assert len(res.groupes) == 1


def test_ponderation_par_montant():
    # Le crédit de 10 ne peut servir qu'à un seul des deux groupes possibles :
    #   A = {débit 60 ; crédits 10, 20, 30}     -> 4 mouvements, 120 €
    #   B = {débit 5000 ; crédits 4990, 10}     -> 3 mouvements, 10 000 €
    donnees = mouvements(
        (60, "debit", 0), (10, "credit", 0), (20, "credit", 0), (30, "credit", 0),
        (5000, "debit", 0), (4990, "credit", 0),
    )
    par_nombre = reconcilier(donnees, params())
    assert {m.ident for g in par_nombre.groupes for m in g.membres} == {"M0", "M1", "M2", "M3"}
    par_montant = reconcilier(donnees, params(weight_by_amount=True))
    assert {m.ident for g in par_montant.groupes for m in g.membres} == {"M1", "M4", "M5"}


def test_jeu_genere_ecarts_nuls_et_groupes_disjoints():
    df = generer(seed=7)
    valides, erreurs = valider(df, resoudre_colonnes(df))
    assert len(erreurs) == 3
    res = reconcilier(valides, params(time_limit=20))

    assert res.groupes, "le jeu généré doit produire des groupes"
    vus: set[int] = set()
    for g in res.groupes:
        assert g.ecart == 0
        assert g.total_debit == g.total_credit
        assert g.nb_debits >= 1 and g.nb_credits >= 1
        assert g.etendue_jours <= 30
        assert len(g.membres) <= 20
        indices = {m.index for m in g.membres}
        assert not (indices & vus), "un mouvement apparaît dans deux groupes"
        vus |= indices
    assert len(vus) == res.nb_reconcilies
    assert res.nb_reconcilies + len(res.non_reconcilies) == len(valides)
    # Les trois mouvements « hors fenêtre » ne doivent pas être regroupés ensemble.
    hors_fenetre = set(df.index[df["libelle"].str.startswith("Hors fenêtre")])
    assert not any(hors_fenetre <= {m.index for m in g.membres} for g in res.groupes)


# ---------------------------------------------------------------------- prétraitement


def test_appariement_exact_priorise_les_dates_proches():
    donnees = mouvements((100, "debit", 0), (100, "credit", 10), (100, "credit", 2), (100, "debit", 12))
    groupes, restants = apparier_exacts(donnees, window_days=30)
    assert restants == []
    assert sorted(sorted(idents(g)) for g in groupes) == [["M0", "M2"], ["M1", "M3"]]
    assert all(g.methode == METHODE_EXACT for g in groupes)


def test_appariement_exact_respecte_la_fenetre():
    donnees = mouvements((100, "debit", 0), (100, "credit", 31))
    groupes, restants = apparier_exacts(donnees, window_days=30)
    assert groupes == [] and len(restants) == 2
    groupes, _ = apparier_exacts(donnees, window_days=31)
    assert len(groupes) == 1


def test_composantes_connexes():
    donnees = mouvements((1, "debit", 0), (1, "credit", 25), (1, "debit", 50), (1, "credit", 100))
    composantes = composantes_connexes(donnees, window_days=30)
    assert [sorted(m.ident for m in c) for c in composantes] == [["M0", "M1", "M2"], ["M3"]]


def test_composante_a_un_seul_type_sans_solveur():
    res = reconcilier(mouvements((10, "debit", 0), (20, "debit", 1)), params())
    assert res.groupes == []
    assert [c.statut for c in res.composantes] == ["SANS_SOLVEUR"]


# ------------------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "valeur, attendu",
    [
        (0.29, 29),
        (1.15, 115),
        (19.99, 1999),
        (1234.565, 123457),
        (100, 10000),
        ("1 234,56", 123456),
        ("1.234,56 €", 123456),
        ("12.5", 1250),
        (0.1 + 0.2, 30),
    ],
)
def test_conversion_en_centimes(valeur, attendu):
    assert montant_en_centimes(valeur) == attendu


def test_validation_signale_les_lignes_invalides():
    df = pd.DataFrame(
        {
            "montant": [100.0, 0, -5, 20, 30, "abc", 40],
            "type": ["Débit", "credit", "debit", "virement", " CRÉDIT ", "debit", None],
            "date": [J0, J0, J0, J0, None, J0, "pas une date"],
        }
    )
    valides, erreurs = valider(df, COLONNES)
    assert [m.index for m in valides] == [0]
    assert valides[0].signe == DEBIT and valides[0].montant == 10000 and valides[0].ident == "L2"

    par_ligne = {}
    for e in erreurs:
        par_ligne.setdefault(e.index, []).append(e.message)
    assert par_ligne[1] == ["montant nul"]
    assert par_ligne[2] == ["montant négatif"]
    assert par_ligne[3] == ["type inconnu (attendu : debit ou credit)"]
    assert par_ligne[4] == ["date manquante"]
    assert par_ligne[5] == ["montant non numérique"]
    assert par_ligne[6] == ["type manquant", "date illisible"]

    rapport = rapport_erreurs(erreurs, len(df))
    assert "montant négatif" in rapport and "ligne 4" in rapport


def test_types_insensibles_a_la_casse_et_aux_accents():
    df = pd.DataFrame(
        {
            "montant": [1, 1, 1, 1],
            "type": ["DEBIT", "  Crédit", "débit ", "CRÉDIT"],
            "date": ["2024-01-15", "15/01/2024", J0, J0.date()],
        }
    )
    valides, erreurs = valider(df, COLONNES)
    assert erreurs == []
    assert [m.signe for m in valides] == [DEBIT, CREDIT, DEBIT, CREDIT]
    assert valides[0].date == valides[1].date == datetime(2024, 1, 15)


def test_mapping_des_colonnes():
    df = pd.DataFrame({"Amount": [1], "Sens": ["debit"], "Date opération": [J0], "Réf": ["A1"]})
    colonnes = resoudre_colonnes(df, {"montant": "Amount"})
    assert colonnes == {
        "montant": "Amount", "type": "Sens", "date": "Date opération", "id": "Réf", "libelle": None,
    }
    valides, _ = valider(df, colonnes)
    assert valides[0].ident == "A1"
    with pytest.raises(ErreurChargement):
        resoudre_colonnes(pd.DataFrame({"a": [1]}))
    with pytest.raises(ErreurChargement):
        resoudre_colonnes(df, {"montant": "inexistante"})


# ----------------------------------------------------------------------- vérification


def test_verification_detecte_un_ecart():
    donnees = mouvements((100, "debit", 0), (99, "credit", 0))
    with pytest.raises(ErreurVerification):
        verifier_solution([Groupe(membres=donnees, methode=METHODE_CPSAT)], Parametres())
    verifier_solution([Groupe(membres=donnees, methode=METHODE_CPSAT)], Parametres(tolerance_cents=100))


def test_verification_detecte_un_doublon():
    donnees = mouvements((100, "debit", 0), (100, "credit", 0))
    groupes = [Groupe(membres=donnees, methode=METHODE_EXACT), Groupe(membres=donnees, methode=METHODE_EXACT)]
    with pytest.raises(ErreurVerification):
        verifier_solution(groupes, Parametres())


# ---------------------------------------------------------------------- bout en bout


def test_cli_de_bout_en_bout(tmp_path):
    entree = tmp_path / "mouvements.xlsx"
    sortie = tmp_path / "resultat.xlsx"
    df = generer(seed=42)
    df.to_excel(entree, index=False)

    code = cli.main(["--input", str(entree), "--output", str(sortie), "--time-limit", "20"])
    assert code == 0

    feuilles = pd.read_excel(sortie, sheet_name=None)
    assert {"Mouvements", "Groupes", "Non réconciliés", "Résumé", "Erreurs"} <= set(feuilles)

    mvts, groupes = feuilles["Mouvements"], feuilles["Groupes"]
    assert len(mvts) == len(df)
    assert {"groupe_id", "statut", "methode"} <= set(mvts.columns)
    assert (groupes["ecart"] == 0).all()
    assert (groupes["total_debit"] == groupes["total_credit"]).all()
    assert (groupes["etendue_jours"] <= 30).all()
    assert set(groupes["methode"]) == {METHODE_EXACT, METHODE_CPSAT}

    reconcilies = mvts[mvts["statut"] == "réconcilié"]
    assert reconcilies["groupe_id"].notna().all()
    assert set(reconcilies["groupe_id"]) == set(groupes["groupe_id"])
    assert len(feuilles["Non réconciliés"]) == (mvts["statut"] == "non réconcilié").sum()
    assert (mvts["statut"] == "rejeté (ligne invalide)").sum() == 3

    resume = dict(zip(feuilles["Résumé"]["Indicateur"], feuilles["Résumé"]["Valeur"]))
    assert int(resume["Nombre total de mouvements"]) == len(df) - 3
    assert int(resume["Nombre de mouvements réconciliés"]) == len(reconcilies)
    assert int(resume["Nombre de groupes"]) == len(groupes)
    assert str(resume["Paramètre : window_days"]) == "30"


def test_cli_fichier_de_config_et_mode_strict(tmp_path):
    entree = tmp_path / "mouvements.xlsx"
    generer(seed=1).to_excel(entree, index=False)
    config = tmp_path / "config.json"
    config.write_text(
        f'{{"input": "{entree.as_posix()}", "output": "{(tmp_path / "r.xlsx").as_posix()}", '
        '"window-days": 15, "time_limit": 10}',
        encoding="utf-8",
    )
    args = cli.lire_arguments(["--config", str(config), "--window-days", "20"])
    assert args.window_days == 20  # la ligne de commande l'emporte
    assert args.time_limit == 10
    assert cli.main(["--config", str(config), "--strict"]) == cli.CODE_ERREUR_ENTREE
    assert not (tmp_path / "r.xlsx").exists()


def test_cli_fichier_introuvable(tmp_path):
    assert cli.main(["--input", str(tmp_path / "absent.xlsx")]) == cli.CODE_ERREUR_ENTREE


# ------------------------------------------------------------------- grands volumes


def _combinaisons(donnees, **kw):
    import numpy as np
    from reconciliation.grande_echelle import candidats_bloc

    valeurs = np.array([m.signe * m.montant for m in donnees])
    jours = np.array([m.jour for m in donnees])
    return {
        tuple(sorted(int(i) for i in ligne))
        for matrice in candidats_bloc(valeurs, jours, params(**kw))
        for ligne in matrice
    }


def test_blocs_trouvent_les_combinaisons_de_2_a_4():
    donnees = mouvements(
        (100, "debit", 0), (60, "credit", 1), (40, "credit", 2),           # 1-2
        (30, "debit", 3), (45, "debit", 3), (75, "credit", 4),             # 2-1
        (70, "debit", 5), (50, "debit", 5), (80, "credit", 6), (40.01, "credit", 6),  # 2-2 à 1 ct près
        (10, "debit", 7), (3, "credit", 7), (3.5, "credit", 8), (3.5, "credit", 9),  # 1-3
    )
    combinaisons = _combinaisons(donnees, tolerance_cents=0)
    assert {(0, 1, 2), (3, 4, 5), (10, 11, 12, 13)} <= combinaisons
    assert (6, 7, 8, 9) not in combinaisons
    assert (6, 7, 8, 9) in _combinaisons(donnees, tolerance_cents=1)
    assert all(len(c) <= 3 for c in _combinaisons(donnees, taille_combinaison=3))


def test_blocs_respectent_la_fenetre():
    donnees = mouvements((100, "debit", 0), (60, "credit", 2), (40, "credit", 45))
    assert _combinaisons(donnees, window_days=30) == set()
    assert _combinaisons(donnees, window_days=45) == {(0, 1, 2)}


def test_mode_blocs_de_bout_en_bout():
    from generer_donnees_test import generer_volume

    df = generer_volume(3_000, seed=3, nb_jours=60)
    valides, erreurs = valider(df, resoudre_colonnes(df))
    assert erreurs == []
    res = reconcilier(valides, params(taille_bloc=200, temps_bloc=0.5))
    assert any(c.statut == "HEURISTIQUE" for c in res.composantes)
    assert any(g.methode == "CP-SAT par blocs" for g in res.groupes)
    assert res.taux > 80  # vérifier_solution a déjà contrôlé chaque groupe
    assert res.nb_reconcilies + len(res.non_reconcilies) == len(valides)
