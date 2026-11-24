"""Journal audio quotidien des news informatiques.

Trois temps, chaque matin :
1. `preparer` (GitHub Actions) : récupère les flux RSS, écrit
   travail/articles.json.
2. Une tâche programmée Claude Code lit ce fichier et écrit
   travail/redaction.json selon CONSIGNES.md : regroupement des articles
   qui racontent la même news, rubriques, texte de 15 minutes.
   Claude tourne sur l'abonnement, pas sur une clé API : c'est pour ça
   que la rédaction est sortie du programme.
3. `finir` (GitHub Actions) : vérifie la rédaction, la lit avec une voix
   française, met à jour le flux de podcast (docs/flux.xml).

Le réseau des sessions Claude dans le cloud est restreint : les flux et
la synthèse vocale sont donc faits par GitHub Actions, Claude ne fait que
lire et écrire des fichiers du dépôt.
"""

import asyncio
import calendar
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

DOSSIER = Path(__file__).resolve().parent
TRAVAIL = Path(os.environ.get("JOURNAL_TRAVAIL") or DOSSIER / "travail")
DOCS = Path(os.environ.get("JOURNAL_DOCS") or DOSSIER / "docs")
URL_FLUX = os.environ.get("JOURNAL_URL_FLUX", "")
URL_AUDIO = os.environ.get("JOURNAL_URL_AUDIO", "").rstrip("/")

VOIX = os.environ.get("JOURNAL_VOIX", "fr-FR-DeniseNeural")
# Mesuré le 23 nov. sur un vrai journal : 1 850 mots en 12 minutes (154 mots/min).
# Un essai sur une phrase répétée donnait 142 : ne pas se fier aux textes factices.
MOTS_VISES = 2300
FENETRE_HEURES = 30          # un peu plus de 24 h, pour ne rien perdre si l'heure varie
EPISODES_GARDES = 14

# BleepingComputer renvoie 403 à un client sans en-tête de navigateur.
AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

SOURCES = {
    "Numerama": "https://www.numerama.com/feed/",
    "01net": "https://www.01net.com/feed/",
    "ZDNet": "https://www.zdnet.fr/feeds/rss/actualites/",
    "Next": "https://next.ink/feed/",
    "LeMagIT": "https://www.lemagit.fr/rss/ContentSyndication.xml",
    "Le Monde Informatique": "https://www.lemondeinformatique.fr/flux-rss/thematique/toutes-les-actualites/rss.xml",
    "CERT-FR alertes": "https://www.cert.ssi.gouv.fr/alerte/feed/",
    "CERT-FR actualités": "https://www.cert.ssi.gouv.fr/actualite/feed/",
    "ZATAZ": "https://www.zataz.com/feed/",
    "ActuIA": "https://www.actuia.com/feed/",
    "Developpez.com": "https://www.developpez.com/index/rss",
    "BleepingComputer": "https://www.bleepingcomputer.com/feed/",
}

# L'ordre est celui de l'écoute. Matériel et grand public écarté à la demande.
RUBRIQUES = ["Sécurité", "IA", "Développement", "Cloud et infrastructure",
             "Business et régulation"]

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


# --- état : ce qui a déjà été raconté -------------------------------------

def charger_etat(chemin=None):
    """Mémoire d'un jour sur l'autre : sans elle, une news reprise le
    lendemain par un site plus lent serait racontée deux fois."""
    chemin = chemin or DOCS / "etat.json"
    if chemin.exists():
        return json.loads(chemin.read_text(encoding="utf-8"))
    return {"liens_vus": {}, "sujets_recents": [], "episodes": []}


def enregistrer_etat(etat, chemin=None):
    # chemin=None puis « or » : une valeur par défaut figée à la définition
    # rendrait toute redirection (essais) inopérante.
    chemin = chemin or DOCS / "etat.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    maintenant = time.time()
    etat["liens_vus"] = {l: t for l, t in etat["liens_vus"].items()
                         if maintenant - t < 30 * 86400}
    etat["sujets_recents"] = [s for s in etat["sujets_recents"]
                              if maintenant - s["t"] < 7 * 86400]
    chemin.write_text(json.dumps(etat, ensure_ascii=False, indent=1),
                      encoding="utf-8")


# --- 1. préparer ----------------------------------------------------------

def nettoyer(texte, limite=500):
    texte = html.unescape(re.sub(r"<[^>]+>", " ", texte or ""))
    texte = re.sub(r"\s+", " ", texte).strip()
    return texte[:limite]


def telecharger(url):
    """feedparser n'a pas de délai maximal : le 24 nov., un flux muet a
    bloqué le relevé 5 minutes sur GitHub. On télécharge donc nous-mêmes."""
    import urllib.request
    debut = time.time()
    requete = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(requete, timeout=20) as r:
        return r.read(), time.time() - debut


def recuperer_articles(etat):
    import feedparser
    from concurrent.futures import ThreadPoolExecutor
    limite = time.time() - FENETRE_HEURES * 3600
    articles, erreurs = [], []
    with ThreadPoolExecutor(8) as pool:
        futurs = {nom: pool.submit(telecharger, url) for nom, url in SOURCES.items()}
    for nom, futur in futurs.items():
        try:
            contenu, duree = futur.result()
        except Exception as e:
            erreurs.append(f"{nom} : {e}")
            continue
        flux = feedparser.parse(contenu)
        if flux.bozo and not flux.entries:
            debut_page = contenu[:120].decode("utf-8", "replace").replace("\n", " ")
            erreurs.append(f"{nom} : {flux.get('bozo_exception')} — reçu : {debut_page!r}")
            continue
        avant = len(articles)
        for e in flux.entries:
            date = e.get("published_parsed") or e.get("updated_parsed")
            lien = e.get("link", "")
            if not lien or lien in etat["liens_vus"]:
                continue
            if date and calendar.timegm(date) < limite:
                continue
            articles.append({
                "id": len(articles),
                "source": nom,
                "titre": nettoyer(e.get("title"), 200),
                "resume": nettoyer(e.get("summary")),
                "lien": lien,
            })
        print(f"  {nom} : {len(articles) - avant} articles ({duree:.1f} s)")
    return articles, erreurs


def preparer():
    etat = charger_etat()
    articles, erreurs = recuperer_articles(etat)
    for e in erreurs:
        print("Flux illisible :", e, file=sys.stderr)
    # Heure de Zurich et non celle du serveur GitHub, qui est en UTC.
    m = datetime.now(ZoneInfo("Europe/Zurich"))
    TRAVAIL.mkdir(parents=True, exist_ok=True)
    (TRAVAIL / "articles.json").write_text(json.dumps({
        "date": f"{m:%Y-%m-%d}",
        # Deux éditions : le matin pour l'aller, à midi pour l'après-midi
        # et le retour. Celle de midi ne reprend que ce qui est paru depuis.
        "edition": "matin" if m.hour < 10 else "midi",
        "date_texte": f"{JOURS[m.weekday()]} {m.day} {MOIS[m.month - 1]} {m.year}",
        "mots_vises": MOTS_VISES,
        "rubriques": RUBRIQUES,
        "sujets_deja_racontes": [s["titre"] for s in etat["sujets_recents"]],
        "articles": articles,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(articles)} articles nouveaux, {len(erreurs)} flux illisibles")


# --- 3. finir -------------------------------------------------------------

def verifier(redaction, articles):
    """La rédaction vient d'un autre programme : une rubrique mal orthographiée
    ou un identifiant inventé ferait planter le tri ou citer un faux lien."""
    ids = {a["id"] for a in articles}
    for cle in ("introduction", "sujets", "conclusion"):
        if cle not in redaction:
            raise ValueError(f"redaction.json : « {cle} » manque")
    if not redaction["sujets"]:
        raise ValueError("redaction.json : aucun sujet")
    for s in redaction["sujets"]:
        if s.get("rubrique") not in RUBRIQUES:
            raise ValueError(f"rubrique inconnue : {s.get('rubrique')!r}")
        if not s.get("texte", "").strip():
            raise ValueError(f"sujet sans texte : {s.get('titre')!r}")
        inconnus = [i for i in s.get("articles", []) if i not in ids]
        if inconnus:
            raise ValueError(f"articles inexistants {inconnus} dans {s.get('titre')!r}")


def assembler(redaction):
    """Les annonces de rubrique sont ajoutées ici : l'auditeur s'y repère
    sans regarder l'écran.

    Un chapitre par news : « suivant » au volant passe à la news suivante,
    et l'appli sait quelle news était en cours quand on la marque."""
    chapitres = [{"titre": "Introduction", "rubrique": None, "articles": [],
                  "texte": redaction["introduction"]}]
    rubrique = None
    for s in sorted(redaction["sujets"], key=lambda s: RUBRIQUES.index(s["rubrique"])):
        texte = s["texte"]
        if s["rubrique"] != rubrique:
            rubrique = s["rubrique"]
            texte = f"Rubrique {rubrique.lower()}.\n\n{texte}"
        chapitres.append({"titre": s["titre"], "rubrique": rubrique,
                          "articles": s["articles"], "texte": texte})
    chapitres[-1]["texte"] += "\n\n" + redaction["conclusion"]
    return chapitres


# edge-tts produit du MP3 à débit constant de 48 kbit/s : la durée se
# déduit de la taille (vérifié contre mutagen le 23 nov., à la ms près).
OCTETS_PAR_SECONDE = 48000 / 8


async def _synthetiser(textes):
    import edge_tts
    limite = asyncio.Semaphore(4)

    async def un(texte):
        async with limite:
            morceaux = []
            async for m in edge_tts.Communicate(texte, VOIX).stream():
                if m["type"] == "audio":
                    morceaux.append(m["data"])
            return b"".join(morceaux)

    return await asyncio.gather(*(un(t) for t in textes))


def lire_a_voix_haute(chapitres, chemin):
    """Chaque chapitre est lu à part puis mis bout à bout : des trames MP3
    se concatènent sans réencodage, et on connaît ainsi le début exact de
    chacun."""
    audios = asyncio.run(_synthetiser([c["texte"] for c in chapitres]))
    debut = 0.0
    for c, audio in zip(chapitres, audios):
        c["debut"] = round(debut, 2)
        debut += len(audio) / OCTETS_PAR_SECONDE
    chemin.write_bytes(b"".join(audios))
    return debut


def notes_episode(redaction, articles):
    par_id = {a["id"]: a for a in articles}
    lignes = []
    for s in redaction["sujets"]:
        liens = " · ".join(f'<a href="{escape(par_id[i]["lien"])}">{escape(par_id[i]["source"])}</a>'
                           for i in s["articles"])
        lignes.append(f"<p><b>[{escape(s['rubrique'])}] {escape(s['titre'])}</b> — {liens}</p>")
    return "\n".join(lignes)


def publier_flux(etat):
    """Flux RSS de podcast : c'est lui qui donne la lecture enchaînée, la
    reprise et les commandes au volant, sans écrire d'appli Android."""
    base_docs = URL_FLUX.rsplit("/", 1)[0]
    items = []
    for ep in etat["episodes"]:
        items.append(f"""<item>
<title>{escape(ep['titre'])}</title>
<guid isPermaLink="false">{escape(ep['fichier'])}</guid>
<pubDate>{ep['date']}</pubDate>
<enclosure url="{escape(URL_AUDIO + '/' + ep['fichier'])}" length="{ep['taille']}" type="audio/mpeg"/>
<podcast:chapters url="{escape(base_docs + '/' + Path(ep['fichier']).stem + '.chapitres.json')}" type="application/json+chapters"/>
<description>{escape(ep['notes'])}</description>
</item>""")
    (DOCS / "flux.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:podcast="https://podcastindex.org/namespace/1.0">
<channel>
<title>Journal informatique</title>
<link>{escape(URL_FLUX)}</link>
<language>fr</language>
<description>Les news informatiques du jour, sans doublons, en 15 minutes.</description>
<itunes:block>Yes</itunes:block>
{chr(10).join(items)}
</channel>
</rss>
""", encoding="utf-8")


def finir():
    entree = json.loads((TRAVAIL / "articles.json").read_text(encoding="utf-8"))
    redaction = json.loads((TRAVAIL / "redaction.json").read_text(encoding="utf-8"))
    articles = entree["articles"]
    verifier(redaction, articles)
    par_id = {a["id"]: a for a in articles}

    chapitres = assembler(redaction)
    nom = f"journal-{entree['date']}-{entree['edition']}"
    mp3 = TRAVAIL / f"{nom}.mp3"
    duree = lire_a_voix_haute(chapitres, mp3)
    texte = "\n\n".join(c["texte"] for c in chapitres)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / f"{nom}.txt").write_text(texte, encoding="utf-8")
    print(f"{len(redaction['sujets'])} sujets, {len(texte.split())} mots, "
          f"{duree / 60:.1f} min")
    for c in chapitres:
        c["liens"] = [{"source": par_id[i]["source"], "lien": par_id[i]["lien"]}
                      for i in c.pop("articles")]
        del c["texte"]
    # Chapitres au format Podcasting 2.0 : AntennaPod les affiche aussi.
    (DOCS / f"{nom}.chapitres.json").write_text(json.dumps({
        "version": "1.2.0",
        "chapters": [{"startTime": c["debut"], "title": c["titre"],
                      **({"url": c["liens"][0]["lien"]} if c["liens"] else {})}
                     for c in chapitres],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    etat = charger_etat()
    t = time.time()
    for a in articles:
        etat["liens_vus"][a["lien"]] = t
    etat["sujets_recents"] += [{"titre": s["titre"], "t": t} for s in redaction["sujets"]]
    etat["episodes"] = [e for e in etat["episodes"] if e["fichier"] != mp3.name]
    etat["episodes"].insert(0, {
        "titre": f"Journal du {entree['date_texte']}, édition du {entree['edition']}",
        "fichier": mp3.name,
        "date": format_datetime(datetime.now(timezone.utc)),
        "taille": mp3.stat().st_size,
        "duree": round(duree),
        "notes": notes_episode(redaction, articles),
        "chapitres": chapitres,
    })
    etat["episodes"].sort(key=lambda e: parsedate_to_datetime(e["date"]), reverse=True)
    perimes = etat["episodes"][EPISODES_GARDES:]
    etat["episodes"] = etat["episodes"][:EPISODES_GARDES]
    for ancien in perimes:
        for ext in (".txt", ".chapitres.json"):
            (DOCS / ancien["fichier"]).with_suffix(ext).unlink(missing_ok=True)
    # Les MP3 sont des pièces jointes de la release « episodes », pas des
    # fichiers du dépôt : 5 Mo par jour gonfleraient l'historique Git.
    (TRAVAIL / "a_supprimer.txt").write_text(
        "\n".join(e["fichier"] for e in perimes), encoding="utf-8")
    enregistrer_etat(etat)
    publier_flux(etat)
    # Ce que lit l'appli Android : les éditions et leurs chapitres, sans
    # l'état interne (liens vus, sujets récents).
    (DOCS / "editions.json").write_text(json.dumps(
        [{k: v for k, v in e.items() if k != "notes"} | {"url": URL_AUDIO + "/" + e["fichier"]}
         for e in etat["episodes"]], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Épisode prêt : {mp3}")


if __name__ == "__main__":
    commandes = {"preparer": preparer, "finir": finir}
    if len(sys.argv) != 2 or sys.argv[1] not in commandes:
        sys.exit("usage : python journal.py preparer|finir")
    commandes[sys.argv[1]]()
