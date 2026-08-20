# -*- coding: utf-8 -*-
"""
test_purge.py — La purge (CDC 9).

Elle est la seule instruction de l'application qui supprime des DPE. Une
erreur ici ne se rattrape pas : la donnee effacee n'est plus servie par
l'ADEME, c'est precisement pour cela qu'on la gardait.
"""

import datetime

import pytest

from app.base import reglages
from app.base.connexion import connexion, transaction
from app.metier.import_dpe import _purger
from tests.conftest import inserer_dpe


def _revu(n_dpe, il_y_a_mois):
    """Un DPE dont l'ADEME n'a plus servi la ligne depuis N mois."""
    quand = (datetime.date.today()
             - datetime.timedelta(days=int(il_y_a_mois * 30.44))).isoformat()
    inserer_dpe(n_dpe=n_dpe, adresse=f"{n_dpe} rue", revu_le=quand)


def _restants():
    with connexion() as conn:
        return {l["n_dpe"] for l in conn.execute("SELECT n_dpe FROM dpe")}


def test_zero_ne_purge_jamais(base):
    """
    Zero veut dire « ne jamais purger ».

    Le piege est arithmetique : zero mois donne une limite au jour meme, et
    supprimerait donc tout ce qui n'a pas ete revu dans la journee — le
    contraire exact de ce qui est demande. Le cas se traite avant tout
    calcul.
    """
    _revu("VIEUX", il_y_a_mois=120)         # dix ans sans etre revu
    _revu("RECENT", il_y_a_mois=1)

    with transaction() as conn:
        assert _purger(conn, 0) == 0
    assert _restants() == {"VIEUX", "RECENT"}


def test_une_valeur_positive_purge_toujours(base):
    """Le garde-fou ne doit pas avoir desarme la purge elle-meme."""
    _revu("OUBLIE", il_y_a_mois=30)
    _revu("SUIVI", il_y_a_mois=3)

    with transaction() as conn:
        assert _purger(conn, 24) == 1
    assert _restants() == {"SUIVI"}


def test_la_purge_ignore_la_date_du_diagnostic(base):
    """
    Elle porte sur `revu_le`, pas sur `date_etablissement` : un diagnostic
    de 2013 que l'ADEME sert encore est la memoire de la chronologie F4, et
    doit survivre.
    """
    inserer_dpe(n_dpe="ANCIEN", adresse="1 rue",
                date_etablissement="2013-05-02",
                revu_le=datetime.date.today().isoformat())

    with transaction() as conn:
        assert _purger(conn, 24) == 0
    assert _restants() == {"ANCIEN"}


def test_un_dpe_jamais_revu_survit(base):
    """`revu_le` vide n'est pas une autorisation de suppression."""
    inserer_dpe(n_dpe="SANS", adresse="1 rue", revu_le=None)

    with transaction() as conn:
        assert _purger(conn, 24) == 0
    assert _restants() == {"SANS"}


def test_le_reglage_accepte_zero_et_refuse_le_negatif(base):
    reglages.ecrire({"purge_mois": 0})
    assert reglages.lire("purge_mois") == 0

    with pytest.raises(ValueError):
        reglages.ecrire({"purge_mois": -1})


def test_le_defaut_conserve_tout():
    """L'exigence exprimee est de garder le maximum d'historique."""
    assert reglages.DEFAUTS["purge_mois"] == 0
