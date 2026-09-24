# -*- coding: utf-8 -*-
"""
criteres.py — Les atouts et les defauts d'un bien, que les donnees ignorent.

DVF ne dit ni la vue, ni le bruit, ni la piscine, ni le vis-a-vis. Les
methodes estiment donc un bien TYPE de son secteur ; ces criteres, coches
par l'utilisateur, l'en ecartent. Chacun porte un coefficient :

  - tire de mesures publiees quand il en existe — la valeur verte des
    notaires, le bruit selon l'ADEME et le Conseil national du bruit,
    l'etage et les exterieurs selon les etudes hedoniques de MeilleursAgents,
    le risque d'inondation selon le Commissariat general au developpement
    durable ;
  - PRUDENT : pris dans le bas des fourchettes publiees. Elles comparent
    souvent un bien a un bien situe ailleurs (une vue mer contre un bien a
    cinq kilometres dans les terres), alors qu'ici le bien est deja compare
    a ses voisins, qui partagent une partie de ses atouts ;
  - PROVISOIRE : ce sont des reperes nationaux, pas des mesures locales.
    Le bilan des estimations dira, critere par critere, si les biens ainsi
    coches se vendent plus ou moins cher qu'estime — c'est lui qui permettra
    de les ajuster pour ce secteur.

Les effets se multiplient, puis le total est BORNE : des atouts qui se
cumulent se recouvrent en partie (une vue mer dit deja la lumiere, un
standing eleve deja une partie du cachet), et au-dela de ces bornes le bien
sort de ce que ses voisins permettent de juger.
"""

import math

TOUS = ("maison", "appartement")

# Le total des criteres ne descend pas sous -35 % ni ne depasse +40 %.
PLANCHER, PLAFOND = 0.65, 1.40

# (cle, libelle, effet, groupe exclusif, types, theme, repere)
CATALOGUE = [
    # --- L'emplacement, a l'echelle de la maison ------------------------
    ("vue_mer", "Vue mer dégagée", 0.20, "vue", TOUS, "emplacement",
     "Sur la Côte d'Azur, +25 à +35 % pour une vue frontale ; retenu +20 %, "
     "le bien étant comparé à ses voisins du littoral."),
    ("vue_mer_partielle", "Vue mer partielle", 0.08, "vue", TOUS, "emplacement",
     "De quelques points à +15 % selon l'ampleur de la vue."),
    ("vue_degagee", "Vue dégagée sur un lac, la forêt ou la campagne", 0.05, "vue", TOUS,
     "emplacement", "Repère d'expertise, sans étude chiffrée publiée."),
    ("calme", "Très calme : impasse, aucun passage", 0.03, "bruit", TOUS, "emplacement",
     "Le pendant du bruit : un bien au calme se vend au-dessus d'une rue ordinaire."),
    ("rue_passante", "Rue passante, bruit de circulation", -0.08, "bruit", TOUS, "emplacement",
     "ADEME : au-delà de 68 dB en façade, −6 à −12 % face à un bien au calme."),
    ("nuisance_forte", "Forte nuisance proche : grand axe, voie ferrée, bars, activité",
     -0.15, "bruit", TOUS, "emplacement",
     "ADEME et Conseil national du bruit : au-delà de 70 dB, −10 à −20 %."),
    ("sans_vis_a_vis", "Aucun vis-à-vis", 0.04, "vis_a_vis", TOUS, "emplacement",
     "Repère d'expertise ; l'intimité se paie surtout en haut de gamme."),
    ("vis_a_vis", "Vis-à-vis important", -0.08, "vis_a_vis", TOUS, "emplacement",
     "Experts : −5 à −20 % selon les pièces exposées et la distance."),
    ("lumineux", "Très lumineux, bien exposé (sud, traversant)", 0.04, "exposition", TOUS,
     "emplacement", "Repère d'expertise."),
    ("sombre", "Sombre ou mal exposé", -0.06, "exposition", TOUS, "emplacement",
     "Repère d'expertise."),
    ("voisinage", "Problème de voisinage connu", -0.08, None, TOUS, "emplacement",
     "Expertises de troubles du voisinage : −5 à −15 %."),
    ("risque", "Zone inondable ou risque connu (submersion, érosion du littoral)", -0.08,
     None, TOUS, "emplacement",
     "CGDD : −6,5 % en zone bleue, jusqu'à −20 % en zone rouge ; le marché "
     "l'oublie entre deux catastrophes."),

    # --- Le bati et ses prestations -------------------------------------
    ("standing", "Standing élevé, prestations haut de gamme", 0.10, "standing", TOUS, "bati",
     "Repère d'expertise. L'état dit ce qu'il faut réparer ; le standing, la "
     "qualité de ce qui est là."),
    ("prestations_modestes", "Prestations bas de gamme", -0.06, "standing", TOUS, "bati",
     "Repère d'expertise."),
    ("architecture", "Architecture remarquable : maison d'architecte, villa de caractère, cachet",
     0.08, None, TOUS, "bati", "Repère d'expertise, sans étude chiffrée publiée."),
    ("energie_performante", "Très performant en énergie : isolation parfaite, DPE A ou B",
     0.10, "energie", TOUS, "bati",
     "Notaires, à caractéristiques égales : une maison A vaut +17 % qu'une D "
     "(2024) ; mesuré dans le Born, +10 % pour A ou B."),
    ("passoire", "Passoire thermique : DPE F ou G", -0.12, "energie", TOUS, "bati",
     "Notaires, Nouvelle-Aquitaine : −15 % pour un appartement F ou G face à "
     "un D, davantage pour une maison ; une part relève de l'état, compté à part."),
    ("domotique", "Domotique, équipements connectés", 0.01, None, TOUS, "bati",
     "Effet faible : les acheteurs le paient peu."),

    # --- Propre a une maison -------------------------------------------
    ("piscine", "Piscine", 0.10, None, ("maison",), "maison",
     "MeilleursAgents (2021, 346 000 ventes, méthode hédonique) : +19,5 % pour "
     "une maison ; retenu +10 %, une partie de l'écart tenant au standing."),
    ("mitoyenne", "Maison mitoyenne", -0.07, None, ("maison",), "maison",
     "−5 à −10 % mitoyenne d'un côté, −10 à −15 % des deux."),

    # --- Propre a un appartement ---------------------------------------
    ("rdc", "Rez-de-chaussée", -0.10, "etage", ("appartement",), "appartement",
     "MeilleursAgents : −10 % face à un 1er ou 2e étage, ascenseur ou non."),
    ("dernier_etage", "Dernier étage", 0.05, "etage", ("appartement",), "appartement",
     "MeilleursAgents : du rez-de-chaussée au dernier étage, +15 % en province."),
    ("sans_ascenseur", "3e étage ou plus, sans ascenseur", -0.07, None, ("appartement",),
     "appartement", "Repère d'expertise."),
    ("balcon", "Balcon ou petite terrasse", 0.05, "exterieur", ("appartement",), "appartement",
     "Études 2019-2021 : +4,4 % sous 10 m², +8,8 % en moyenne dans les grandes villes."),
    ("grande_terrasse", "Grande terrasse ou jardin privatif", 0.10, "exterieur",
     ("appartement",), "appartement", "Jusqu'à +30 % au-delà de 50 m² ; retenu +10 %."),
    ("copro_degradee", "Copropriété dégradée ou gros travaux votés", -0.08, None,
     ("appartement",), "appartement", "Repère d'expertise."),
]

THEMES = {
    "emplacement": "L'emplacement, à l'échelle du bien",
    "bati": "Le bâti et ses prestations",
    "maison": "Pour une maison",
    "appartement": "Pour un appartement",
}

_PAR_CLE = {c[0]: c for c in CATALOGUE}


def liste():
    """Le catalogue, pour l'ecran."""
    return [{"cle": cle, "libelle": libelle, "effet": round(effet * 100), "groupe": groupe,
             "types": list(types), "theme": theme, "repere": repere}
            for cle, libelle, effet, groupe, types, theme, repere in CATALOGUE]


def libelle(cle):
    critere = _PAR_CLE.get(cle)
    return critere[1] if critere else cle


def retenir(cles, type_bien):
    """
    Verifie les criteres coches et calcule leur effet d'ensemble.

    Rend (criteres, facteur brut, facteur borne) ; leve ValueError pour un
    critere inconnu, etranger au type de bien, ou deux criteres qui
    s'excluent (« vue mer » et « vue mer partielle »).
    """
    retenus, groupes = [], {}
    for cle in dict.fromkeys(cles or []):
        critere = _PAR_CLE.get(cle)
        if critere is None:
            raise ValueError(f"Critère inconnu : {cle}.")
        _, nom, effet, groupe, types, _, _ = critere
        if type_bien not in types:
            raise ValueError(f"« {nom} » ne s'applique pas à un{'e maison' if type_bien == 'maison' else ' appartement'}.")
        if groupe:
            if groupe in groupes:
                raise ValueError(f"« {groupes[groupe]} » et « {nom} » s'excluent : n'en cochez qu'un.")
            groupes[groupe] = nom
        retenus.append({"cle": cle, "libelle": nom, "effet": effet})
    brut = math.prod(1 + c["effet"] for c in retenus)
    return retenus, brut, min(max(brut, PLANCHER), PLAFOND)
