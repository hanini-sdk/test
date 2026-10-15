"""Réconciliation bancaire exacte par programmation par contraintes (OR-Tools CP-SAT).

Données minimales : montant, sens (C = crédit / entrée, D = débit / sortie), date.

Modèle « par représentant » : chaque groupe est identifié par son mouvement le plus ancien.
  x[m,k] = 1  si le mouvement m appartient au groupe dont le représentant est k (k <= m)
  x[k,k] = 1  si le groupe k existe
Contraintes :
  (1) chaque mouvement est dans au plus un groupe
  (2) x[m,k] <= x[k,k]                    (un groupe n'existe que si son représentant y est)
  (3) somme des montants signés du groupe k = 0 (en centimes, égalité exacte)
  (4) date(m) - date(k) <= FENETRE        (appliquée en ne créant pas la variable)
  (5) taille du groupe <= TAILLE_MAX       (optionnel)
Objectif lexicographique, résolu en 3 passes successives :
  1. maximiser le nombre de mouvements réconciliés
  2. à niveau 1 fixé, maximiser le nombre de groupes (groupes les plus petits possible)
  3. à niveaux 1 et 2 fixés, minimiser l'étalement des dates dans les groupes

La décomposition en composantes (coupure dès que deux dates consécutives sont séparées de
plus de FENETRE jours) est exacte : aucun groupe admissible ne peut chevaucher une coupure.
"""
import argparse
import csv
from datetime import date

from ortools.sat.python import cp_model


def charger(chemin, col_montant, col_sens, col_date, sep):
    mouvements = []
    with open(chemin, encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f, delimiter=sep)):
            centimes = round(float(r[col_montant].replace(",", ".").replace(" ", "")) * 100)
            sens = r[col_sens].strip().upper()
            sens = {"ENTRANT": "C", "SORTANT": "D"}.get(sens, sens)
            if sens not in ("C", "D"):
                raise ValueError(f"Ligne {i + 2} : sens inconnu {r[col_sens]!r}")
            if centimes == 0:
                continue
            mouvements.append({
                "id": r.get("id") or f"L{i + 2}",
                "date": date.fromisoformat(r[col_date][:10]),
                "sens": sens,
                "v": abs(centimes) if sens == "C" else -abs(centimes),
            })
    mouvements.sort(key=lambda m: (m["date"], m["id"]))
    return mouvements


def composantes(mouvements, fenetre):
    bloc = [mouvements[0]]
    for prec, m in zip(mouvements, mouvements[1:]):
        if (m["date"] - prec["date"]).days > fenetre:
            yield bloc
            bloc = []
        bloc.append(m)
    yield bloc


def resoudre_composante(mvts, fenetre, taille_max, temps_max):
    n = len(mvts)
    if len({m["sens"] for m in mvts}) < 2:
        return [], "OPTIMAL (un seul sens)", 0

    model = cp_model.CpModel()
    x = {}
    for k in range(n):
        for m in range(k, n):
            if (mvts[m]["date"] - mvts[k]["date"]).days <= fenetre:
                x[m, k] = model.NewBoolVar(f"x_{m}_{k}")

    par_mvt = {m: [] for m in range(n)}
    par_groupe = {k: [] for k in range(n)}
    for (m, k), var in x.items():
        par_mvt[m].append(var)
        par_groupe[k].append((m, var))

    for m in range(n):
        model.AddAtMostOne(par_mvt[m])
    for k in range(n):
        membres = par_groupe[k]
        for m, var in membres:
            if m != k:
                model.AddImplication(var, x[k, k])
        model.Add(sum(mvts[m]["v"] * var for m, var in membres) == 0)
        if taille_max:
            model.Add(sum(var for _, var in membres) <= taille_max)

    nb_lettres = sum(x.values())
    nb_groupes = sum(x[k, k] for k in range(n))
    etalement = sum((mvts[m]["date"] - mvts[k]["date"]).days * var for (m, k), var in x.items())

    solveur = cp_model.CpSolver()
    solveur.parameters.max_time_in_seconds = temps_max
    solveur.parameters.num_workers = 8
    statuts = []
    for sens_obj, expr in (("max", nb_lettres), ("max", nb_groupes), ("min", etalement)):
        model.Maximize(expr) if sens_obj == "max" else model.Minimize(expr)
        statut = solveur.Solve(model)
        if statut not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return [], solveur.StatusName(statut), 0
        statuts.append(solveur.StatusName(statut))
        valeur = round(solveur.ObjectiveValue())
        model.ClearHints()
        for var in x.values():
            model.AddHint(var, solveur.Value(var))
        model.Add(expr == valeur)  # fige ce niveau avant de passer au suivant

    groupes = []
    for k in range(n):
        if solveur.Value(x[k, k]):
            groupes.append([mvts[m] for m, var in par_groupe[k] if solveur.Value(var)])
    statut_global = "OPTIMAL" if all(s == "OPTIMAL" for s in statuts) else "NON PROUVE (" + "/".join(statuts) + ")"
    return groupes, statut_global, len(x)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("fichier")
    p.add_argument("--montant", default="montant")
    p.add_argument("--sens", default="sens")
    p.add_argument("--date", default="date")
    p.add_argument("--sep", default=";")
    p.add_argument("--fenetre", type=int, default=7, help="écart maximal en jours dans un groupe")
    p.add_argument("--taille-max", type=int, default=0, help="taille maximale d'un groupe (0 = illimitée)")
    p.add_argument("--temps-max", type=float, default=60, help="secondes par passe et par composante")
    p.add_argument("--sortie", default="groupes_trouves.csv")
    a = p.parse_args()

    mouvements = charger(a.fichier, a.montant, a.sens, a.date, a.sep)
    tous_groupes, toutes_optimales = [], True
    for i, comp in enumerate(composantes(mouvements, a.fenetre), 1):
        groupes, statut, nb_var = resoudre_composante(comp, a.fenetre, a.taille_max, a.temps_max)
        toutes_optimales &= statut.startswith("OPTIMAL")
        print(f"Composante {i:>3} : {len(comp):>4} mouvements, {nb_var:>6} variables, "
              f"{len(groupes):>3} groupes, statut {statut}")
        tous_groupes += groupes

    with open(a.sortie, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["groupe", "type", "ids", "somme_centimes"])
        for g, membres in enumerate(tous_groupes, 1):
            nc = sum(m["sens"] == "C" for m in membres)
            somme = sum(m["v"] for m in membres)
            assert somme == 0
            w.writerow([f"R{g:03d}", f"{nc}C-{len(membres) - nc}D",
                        ";".join(m["id"] for m in membres), somme])

    nb = sum(len(g) for g in tous_groupes)
    print(f"\n{nb}/{len(mouvements)} mouvements réconciliés en {len(tous_groupes)} groupes"
          f" — optimalité {'prouvée' if toutes_optimales else 'NON prouvée'} sur toutes les composantes")


if __name__ == "__main__":
    main()
