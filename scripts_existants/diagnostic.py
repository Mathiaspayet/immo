#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnostic.py — Identifier l'origine d'une erreur de certificat HTTPS.

Lance ce script AVANT parcelles.py si tu as une erreur
"CERTIFICATE_VERIFY_FAILED". Il teste chaque cause possible et te dit
laquelle s'applique.

Usage :  python parcelles_diagnostic.py
"""

import datetime
import platform
import ssl
import sys
import urllib.request

URL_TEST = "https://geo.api.gouv.fr/communes?codePostal=78000"


def essayer(contexte, libelle):
    """Tente une connexion et affiche le résultat."""
    try:
        requete = urllib.request.Request(URL_TEST, headers={"User-Agent": "diagnostic"})
        with urllib.request.urlopen(requete, timeout=20, context=contexte) as reponse:
            reponse.read()
        print(f"  [OK]     {libelle}")
        return True
    except Exception as erreur:
        print(f"  [ECHEC]  {libelle}")
        print(f"           -> {type(erreur).__name__}: {erreur}")
        return False


print("\n=== DIAGNOSTIC ===\n")

print("Environnement")
print(f"  Python           : {sys.version.split()[0]}")
print(f"  Systeme          : {platform.system()} {platform.release()}")
print(f"  Bibliotheque SSL : {ssl.OPENSSL_VERSION}")

# --- Cause n°1 : horloge du PC ---
maintenant = datetime.datetime.now()
print(f"\nHorloge du PC : {maintenant:%d/%m/%Y %H:%M}")
print("  Verifie que cette date est la bonne. Si elle est fausse, TOUS les")
print("  certificats paraissent expires. C'est la cause la plus frequente.")

# --- Cause n°2 : magasin de certificats ---
print("\nListe de certificats utilisee")
try:
    import certifi
    print(f"  certifi est installe : {certifi.where()}")
    contexte_certifi = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    print("  certifi n'est PAS installe (Python utilise la liste du systeme)")
    contexte_certifi = None

# --- Tests de connexion ---
print("\nTests de connexion vers geo.api.gouv.fr")

ok_defaut = essayer(ssl.create_default_context(), "avec la liste du systeme")

ok_certifi = None
if contexte_certifi is not None:
    ok_certifi = essayer(contexte_certifi, "avec la liste de certifi")

contexte_sans = ssl.create_default_context()
contexte_sans.check_hostname = False
contexte_sans.verify_mode = ssl.CERT_NONE
ok_sans = essayer(contexte_sans, "sans aucune verification")

# --- Conclusion ---
print("\n=== CONCLUSION ===\n")

if ok_defaut:
    print("  Tout fonctionne. Tu peux lancer parcelles.py tel quel.")
elif ok_certifi:
    print("  La liste de certificats de Windows est en cause, celle de certifi")
    print("  fonctionne. parcelles.py l'utilisera automatiquement : rien a faire,")
    print("  relance-le simplement.")
elif ok_sans:
    print("  La connexion passe, mais aucune liste de certificats ne valide le")
    print("  serveur. Deux pistes :")
    print("    - installe certifi :  pip install certifi")
    print("    - ou desactive l'analyse HTTPS de ton antivirus")
    print("  A defaut, mets VERIFIER_CERTIFICATS = False dans parcelles.py.")
else:
    print("  Aucune connexion ne passe : le probleme n'est pas les certificats")
    print("  mais l'acces reseau lui-meme (pare-feu, proxy d'entreprise, ou")
    print("  coupure internet). Teste depuis une autre connexion, par exemple")
    print("  en partage de connexion depuis ton telephone.")

print()
input("Appuie sur Entree pour fermer.")
