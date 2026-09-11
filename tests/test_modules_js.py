# -*- coding: utf-8 -*-
"""
test_modules_js.py — Aucun appel a une fonction qui n'existe pas.

`node --check` valide la SYNTAXE, pas les noms : un appel a une fonction
jamais ecrite passe sans un mot, et n'echoue qu'a l'execution.

C'est arrive, et le defaut a tenu des semaines. `chargerContexte()` etait
appelee a deux endroits — a la selection d'une commune, et a la fin d'un
import — sans avoir jamais ete ecrite. Chaque appel levait un
`ReferenceError` qu'un `try/catch` muet avalait, et le `charger()` pose sur
la meme ligne ne s'executait jamais.

Le symptome n'avait rien d'evident : l'ecran Veille s'ouvrait VIDE et ne se
remplissait qu'au premier changement de filtre, celui-ci appelant
`charger()` directement.

La regle gardee ici : un identifiant appele comme une fonction doit
apparaitre ailleurs dans son module — declaration, import, parametre,
affectation, ou simple mention hors appel — ou bien etre un global connu
du navigateur.

Le prix d'un faux positif est eleve : il ferait echouer une livraison
saine. Le lexeur ci-dessous est donc conservateur, et la liste des noms
connus volontairement large.
"""

import pathlib
import re
import shutil
import subprocess

import pytest

DOSSIER = pathlib.Path(__file__).resolve().parent.parent / "app" / "web" / "js"

# Mots-cles et mots-cles contextuels : `async (x) => ...` ressemble a un
# appel de `async`, `if (` a un appel de `if`. Aucun n'en est un.
MOTS_CLES = {
    "if", "for", "while", "switch", "catch", "return", "typeof", "function",
    "await", "new", "delete", "void", "in", "of", "do", "else", "try",
    "throw", "yield", "case", "super", "import", "export", "instanceof",
    "async", "get", "set", "static", "class", "const", "let", "var", "this",
    "with", "finally", "default", "break", "continue",
}

# Ce que le navigateur fournit.
GLOBAUX = {
    "console", "document", "window", "fetch", "setTimeout", "clearTimeout",
    "setInterval", "clearInterval", "requestAnimationFrame", "alert",
    "confirm", "prompt", "matchMedia", "getComputedStyle", "structuredClone",
    "encodeURIComponent", "decodeURIComponent", "encodeURI", "decodeURI",
    "parseInt", "parseFloat", "isNaN", "isFinite", "queueMicrotask",
    "URLSearchParams", "FormData", "Blob", "URL", "Event", "CustomEvent",
    "IntersectionObserver", "ResizeObserver", "MutationObserver",
    "AbortController", "Image", "Option", "Intl", "Promise", "Array",
    "Object", "String", "Number", "Boolean", "Math", "JSON", "Date", "Map",
    "Set", "WeakMap", "WeakSet", "RegExp", "Error", "TypeError", "Symbol",
    "BigInt", "Proxy", "Reflect", "history", "location", "navigator",
    "localStorage", "sessionStorage", "performance", "crypto",
    # Leaflet, auto-hebergee dans l'image.
    "L",
}

CONNUS = MOTS_CLES | GLOBAUX

IDENTIFIANT = r"[A-Za-z_$][\w$]*"
APPEL = re.compile(rf"(?<![.\w$])({IDENTIFIANT})\s*\(")

# Declarations. La forme abregee — `tracer(geometrie) {` dans une classe ou
# un litteral d'objet — est un piege : elle ressemble mot pour mot a un
# appel.
DECLARATIONS = (
    re.compile(rf"\b(?:function\s*\*?\s+|class\s+|const\s+|let\s+|var\s+)({IDENTIFIANT})"),
    re.compile(rf"(?m)^\s*(?:static\s+)?(?:async\s+)?(?:\*\s*)?(?:get\s+|set\s+)?"
               rf"({IDENTIFIANT})\s*\([^;]*?\)\s*\{{"),
)

# Ce qui precede un « / » quand il ouvre une expression reguliere et non une
# division.
AVANT_REGEX = set("(,=:[!&|?{};+-*%~^<>") | {""}
MOTS_AVANT_REGEX = {"return", "typeof", "case", "in", "of", "new", "delete",
                    "void", "do", "else", "yield", "await", "throw"}


def _sans_bruit(source):
    """Blanchit commentaires, chaines et expressions regulieres.

    Le code place dans les `${...}` d'un gabarit est CONSERVE : c'en est,
    et un appel fantome peut s'y cacher. Une suppression naive par regex
    trebuche sur les gabarits imbriques et avale des pans entiers de
    fichier — c'est ce qu'elle faisait, masquant de vraies declarations.
    """
    sortie = []
    pile = []          # "gabarit" ou profondeur d'accolades dans un ${...}
    i, n = 0, len(source)

    def garder(texte):
        sortie.append(texte)

    def blanchir(texte):
        # On preserve les retours a la ligne : les numeros de ligne restent
        # justes si l'on veut situer un defaut.
        garder(re.sub(r"[^\n]", " ", texte))

    def precedent():
        for morceau in reversed(sortie):
            for c in reversed(morceau):
                if not c.isspace():
                    return c
        return ""

    def mot_precedent():
        colle = "".join(sortie)
        trouve = re.search(rf"({IDENTIFIANT})\s*$", colle)
        return trouve.group(1) if trouve else ""

    while i < n:
        c = source[i]
        dans_gabarit = bool(pile) and pile[-1] == "gabarit"

        if dans_gabarit:
            if c == "\\":
                blanchir(source[i:i + 2])
                i += 2
            elif c == "`":
                pile.pop()
                blanchir(c)
                i += 1
            elif c == "$" and i + 1 < n and source[i + 1] == "{":
                pile.append(0)
                blanchir(source[i:i + 2])
                i += 2
            else:
                blanchir(c)
                i += 1
            continue

        if c == "/" and i + 1 < n and source[i + 1] == "/":
            fin = source.find("\n", i)
            fin = n if fin < 0 else fin
            blanchir(source[i:fin])
            i = fin
        elif c == "/" and i + 1 < n and source[i + 1] == "*":
            fin = source.find("*/", i + 2)
            fin = n if fin < 0 else fin + 2
            blanchir(source[i:fin])
            i = fin
        elif c in "\"'":
            j = i + 1
            while j < n and source[j] != c:
                j += 2 if source[j] == "\\" else 1
            j = min(j + 1, n)
            blanchir(source[i:j])
            i = j
        elif c == "`":
            pile.append("gabarit")
            blanchir(c)
            i += 1
        elif c == "/" and (precedent() in AVANT_REGEX
                           or mot_precedent() in MOTS_AVANT_REGEX):
            j = i + 1
            crochets = False
            while j < n and source[j] != "\n":
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == "[":
                    crochets = True
                elif source[j] == "]":
                    crochets = False
                elif source[j] == "/" and not crochets:
                    break
                j += 1
            if j < n and source[j] == "/":
                while j + 1 < n and source[j + 1].isalpha():
                    j += 1
                blanchir(source[i:j + 1])
                i = j + 1
            else:                       # pas une regex, finalement
                garder(c)
                i += 1
        elif pile and c == "{":
            pile[-1] += 1
            garder(c)
            i += 1
        elif pile and c == "}":
            if pile[-1] == 0:
                pile.pop()              # fin du ${...}, retour au gabarit
                blanchir(c)
            else:
                pile[-1] -= 1
                garder(c)
            i += 1
        else:
            garder(c)
            i += 1

    return "".join(sortie)


def _noms_connus(source):
    """Tout identifiant que le module introduit d'une facon ou d'une autre."""
    noms = set()
    for motif in DECLARATIONS:
        noms.update(motif.findall(source))
    # Imports : { a, b as c } et defaut.
    for bloc in re.findall(r"import\s+([^;]+?)\s+from", source, flags=re.S):
        noms.update(re.findall(rf"({IDENTIFIANT})", bloc))
    # Parametres, motifs de destructuration, variables de boucle.
    for bloc in re.findall(r"\(([^()]*)\)\s*(?:=>|\{)", source):
        noms.update(re.findall(IDENTIFIANT, bloc))
    for bloc in re.findall(r"(?:const|let|var)\s*([\[{][^;=]*[\]}])\s*=", source):
        noms.update(re.findall(IDENTIFIANT, bloc))
    noms.update(re.findall(rf"({IDENTIFIANT})\s*=>", source))
    # Affectations et proprietes abregees.
    noms.update(re.findall(rf"({IDENTIFIANT})\s*=[^=>]", source))
    return noms


def _mentions_hors_appel(source):
    """Noms cites sans parenthese : export, callback passe tel quel,
    propriete abregee. Le module les connait forcement."""
    cites = set()
    for trouve in re.finditer(rf"(?<![.\w$])({IDENTIFIANT})", source):
        suite = source[trouve.end():]
        if not re.match(r"\s*\(", suite):
            cites.add(trouve.group(1))
    return cites


def _fantomes(source):
    propre = _sans_bruit(source)
    connus = _noms_connus(propre) | _mentions_hors_appel(propre) | CONNUS
    return sorted({nom for nom in APPEL.findall(propre) if nom not in connus})


@pytest.mark.parametrize("chemin", sorted(DOSSIER.glob("*.js")), ids=lambda p: p.name)
def test_aucun_appel_a_une_fonction_inexistante(chemin):
    fantomes = _fantomes(chemin.read_text(encoding="utf-8"))
    assert not fantomes, (
        f"{chemin.name} appelle des noms qu'il ne definit ni n'importe : "
        + ", ".join(fantomes)
        + ". Un tel appel leve un ReferenceError a l'execution, que le "
          "premier try/catch venu peut avaler sans un mot.")


def test_le_garde_voit_une_fonction_jamais_ecrite():
    """Le defaut reel, en miniature : appelee deux fois, ecrite nulle part."""
    assert _fantomes(
        "import { api } from './api.js';\n"
        "async function charger() { await api.veille(); }\n"
        "export function demarrer() {\n"
        "  chargerContexte();\n"
        "  charger();\n"
        "}\n") == ["chargerContexte"]


def test_le_garde_ne_crie_pas_sur_du_code_sain():
    """Les formes qui ressemblent a un appel sans en etre un : methode
    abregee, `async (`, gabarit imbrique, expression reguliere."""
    assert _fantomes(
        "import { api } from './api.js';\n"
        "class Carte {\n"
        "  tracer(forme, options = {}) { return forme; }\n"
        "  get cadre() { return this.boite; }\n"
        "}\n"
        "const propre = (t) => t.replace(/\\(/g, '');\n"
        "const bouton = async (evenement) => {\n"
        "  const html = `<b>${propre(evenement.type)}</b>`;\n"
        "  return `${html} ${new Carte().tracer(1)}`;\n"
        "};\n"
        "export { bouton, api };\n") == []


# ---------------------------------------------------------------------
#  La syntaxe, verifiee dans le BON mode
# ---------------------------------------------------------------------

def test_chaque_module_est_syntaxiquement_valide(chemin):
    """
    `node --check FICHIER` analyse le fichier comme un script CommonJS.
    Nos fichiers sont des MODULES, et les deux grammaires different : une
    redeclaration que le mode module refuse passe sans un mot en mode
    script.

    Cas vecu : `const ecran = {...}` ajoute a un module qui portait deja
    `function etat(...)`. `node --check` a rendu 0 ; le navigateur, lui, a
    refuse le module entier — « Identifier 'etat' has already been
    declared » — et l'application ne demarrait plus du tout. Un module qui
    ne s'analyse pas ne s'execute pas : rien n'en sort, pas meme une
    moitie d'ecran.

    Rien dans la suite ne verifiait la syntaxe jusqu'ici. C'est fait, et
    dans le mode ou ces fichiers sont reellement charges.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent de cette machine")

    verdict = subprocess.run(
        [node, "--input-type=module", "--check"],
        input=chemin.read_text(encoding="utf-8"),
        capture_output=True, text=True)
    assert verdict.returncode == 0, (
        f"{chemin.name} n'est pas un module valide :\n{verdict.stderr}")


# La meme liste de fichiers pour les deux gardes.
test_chaque_module_est_syntaxiquement_valide = pytest.mark.parametrize(
    "chemin", sorted(DOSSIER.glob("*.js")), ids=lambda p: p.name
)(test_chaque_module_est_syntaxiquement_valide)


# ---------------------------------------------------------------------
#  Les elements vises existent vraiment
# ---------------------------------------------------------------------

PAGE = DOSSIER.parent / "index.html"
CIBLE = re.compile(r'\$\(\s*"#([A-Za-z][\w-]*)"\s*\)')
POSE = re.compile(r'id="([^"]+)"')


def test_chaque_element_vise_existe(chemin):
    """
    `$("#quelque-chose")` sur un identifiant absent rend `null`, et la
    ligne suivante — `.addEventListener`, `.innerHTML` — leve un
    TypeError qui interrompt tout ce qui suit dans la meme fonction.

    C'est le meme accident que l'appel a une fonction jamais ecrite, par
    une autre porte : un bouton cesse de repondre, un ecran reste vide, et
    rien ne le dit. Renommer `#panneau-carte` en classe, deplacer un
    formulaire d'un ecran a l'autre, retirer une section : chaque fois le
    risque est le meme.

    Les identifiants poses PAR le script comptent : une fiche construit sa
    propre barre de retour avant de s'y accrocher.
    """
    poses = set(POSE.findall(PAGE.read_text(encoding="utf-8")))
    for module in DOSSIER.glob("*.js"):
        poses.update(POSE.findall(module.read_text(encoding="utf-8")))

    # Le texte BRUT, non blanchi : la cible est justement une chaine.
    vises = set(CIBLE.findall(chemin.read_text(encoding="utf-8")))
    absents = sorted(vises - poses)
    assert not absents, (
        f"{chemin.name} interroge des elements que la page ne porte pas : "
        + ", ".join(absents)
        + ". `$()` rend null, et le premier appel de methode qui suit "
          "interrompt la fonction sans un mot.")


test_chaque_element_vise_existe = pytest.mark.parametrize(
    "chemin", sorted(DOSSIER.glob("*.js")), ids=lambda p: p.name
)(test_chaque_element_vise_existe)
