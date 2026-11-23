#!/usr/bin/env python3
"""Collecte le programme des cinémas de Lectoure, Fleurance et Mauvezin.

Sources :
- Lectoure et Mauvezin : l'API utilisée par le site cine32gers.com (Ciné 32) ;
- Fleurance (Grand Angle) : les données publiées par cinegrandangle.fr ;
- Beaumont-de-Lomagne (Les Nouveaux Bleus) : la page cinéma du site de la mairie
  (séances) et le tract PDF qu'elle propose (fiches des films).
Écrit programme.json à la racine du dépôt.
Python 3.9+ ; seule dépendance, facultative : pypdf (lecture du tract de Beaumont).
"""
import html
import io
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = "https://www.cine32gers.com/api/gatsby-source-boxofficeapi"
TZ = "Europe/Paris"
DAYS = 7  # aujourd'hui + 6 jours
GA_BASE = "https://cinegrandangle.fr"
CINEMAS = [
    {"id": "P1039", "ville": "Lectoure", "nom": "Le Sénéchal", "source": "cine32"},
    {"id": "P1051", "ville": "Fleurance", "nom": "Grand Angle", "source": "grandangle"},
    {"id": "P1042", "ville": "Mauvezin", "nom": "Ciné Mauv'", "source": "cine32"},
    {"id": "BDL", "ville": "Beaumont", "nom": "Les Nouveaux Bleus", "source": "beaumont"},
]
BD_URL = "https://www.beaumontdelomagne.fr/vivre-a-beaumont/cinema"
OUT = Path(__file__).resolve().parent.parent / "programme.json"
HEADERS = {
    "User-Agent": "programme-cinemas-gers/1.0 (projet personnel, une collecte par jour)",
    "Referer": "https://www.cine32gers.com/",
    "Accept": "application/json",
}


def get_bytes(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def get_text(url, tries=3):
    return get_bytes(url, tries).decode("utf-8")


def get_json(url, tries=3):
    return json.loads(get_text(url, tries))


def version(tags):
    """VO (toujours sous-titrée en français en salle) -> VOSTFR ; sinon VF."""
    if "Localization.Version.Original" in tags:
        return "VOSTFR"
    if "Localization.Language.French" in tags:
        return "VF"
    return None


def fetch_sessions(cinema_id, start, end):
    q = urllib.parse.urlencode({
        "from": f"{start:%Y-%m-%d}T03:00:00",
        "theaters": json.dumps({"id": cinema_id, "timeZone": TZ}, separators=(",", ":")),
        "to": f"{end:%Y-%m-%d}T03:00:00",
    })
    data = get_json(f"{BASE}/schedule?{q}")
    schedule = (data.get(cinema_id) or {}).get("schedule") or {}
    first, last = f"{start:%Y-%m-%d}", f"{end - timedelta(days=1):%Y-%m-%d}"
    out = []
    for movie_id, days in schedule.items():
        for day, shows in days.items():
            if not first <= day <= last:
                continue
            for s in shows:
                out.append({
                    "date": day,
                    "time": s["startsAt"][11:16],
                    "cinema": cinema_id,
                    "movie": str(movie_id),
                    "version": version(s.get("tags", [])),
                    "screen": (s.get("screen") or {}).get("name"),
                })
    return out


def person_list(value):
    return [p for p in (value or []) if isinstance(p, str)]


def fetch_movies(ids):
    movies = {}
    ids = sorted(ids)
    for i in range(0, len(ids), 20):
        params = [("basic", "false"), ("castingLimit", "6")] + [("ids", x) for x in ids[i:i + 20]]
        for m in get_json(f"{BASE}/movies?{urllib.parse.urlencode(params)}"):
            locale = m.get("locale") or {}
            movies[str(m["id"])] = {
                "titre": m.get("title"),
                "titre_original": m.get("originalTitle"),
                "affiche": m.get("poster"),
                "genres": m.get("genres"),
                "duree_min": round(m["runtime"] / 60) if m.get("runtime") else None,
                "realisateurs": person_list(m.get("direction")) + person_list(m.get("coDirection")),
                "acteurs": person_list(m.get("casting")),
                "synopsis": m.get("synopsis") or locale.get("synopsis"),
            }
    return movies


GA_VERSIONS = {"VF": "VF", "VOST": "VOSTFR", "VOSTFR": "VOSTFR"}


def grandangle_data():
    """Données du Grand Angle : /data.json, sinon le bloc intégré à la page /programme."""
    try:
        data = get_json(f"{GA_BASE}/data.json", tries=1)
        if isinstance(data, dict) and data.get("seances"):
            return data
    except Exception:
        pass
    html = get_text(f"{GA_BASE}/programme")
    marker = "window.__CINE_DATA__="
    start = html.index(marker) + len(marker)
    data, _ = json.JSONDecoder().raw_decode(html[start:])
    return data


def fetch_grandangle(start, end):
    data = grandangle_data()
    first, last = f"{start:%Y-%m-%d}", f"{end - timedelta(days=1):%Y-%m-%d}"
    films = {f["id"]: f for f in data["films"]}
    sessions, movies = [], {}
    for s in data["seances"]:
        day = s["starts_at"][:10]  # heure locale déjà indiquée dans la date
        if not first <= day <= last or s["film_id"] not in films:
            continue
        f, mid = films[s["film_id"]], f"ga-{s['film_id']}"
        v = s.get("version")
        sess = {
            "date": day,
            "time": s["starts_at"][11:16],
            "cinema": "P1051",
            "movie": mid,
            "version": GA_VERSIONS.get(str(v).upper(), v) if v else None,
            "screen": s.get("room"),
        }
        if s.get("event_title"):
            sess["evenement"] = s["event_title"]
        sessions.append(sess)
        movies[mid] = {
            "titre": f.get("title"),
            "titre_original": f.get("original_title"),
            "affiche": f.get("poster_url"),
            "genres": ", ".join(f.get("genres") or []),
            "duree_min": f.get("runtime"),
            "realisateurs": [f["director"]] if f.get("director") else [],
            "acteurs": person_list(f.get("cast")),
            "synopsis": f.get("overview"),
        }
    return sessions, movies


# ---------------------------------------------------------------- Beaumont
# La page de la mairie alterne : une image (nom de fichier = titre du film), puis un
# intertitre « Mer 18 nov : 17h30 [VOST] », puis « Durée : 2h14 » et la bande-annonce.
BD_TOKEN = re.compile(r'<img\b[^>]*?\bsrc="([^"]+?\.svg)"|<h3[^>]*>(.*?)</h3>', re.S | re.I)
BD_SESSION = re.compile(
    r"^(?:lun|mar|mer|jeu|ven|sam|dim)\w*\.?\s+(\d{1,2})\s+([^\s:]+)\s*:\s*(\d{1,2})\s*h\s*(\d{2})?\s*(VOST\w*)?",
    re.I)
BD_STOP = {"le", "la", "les", "l", "un", "une", "des", "de", "du", "d", "et", "au", "aux", "the"}


def plain(fragment):
    txt = html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ")
    return " ".join(txt.split())


def ascii_lower(txt):
    txt = unicodedata.normalize("NFD", txt.lower())
    return "".join(c for c in txt if not unicodedata.combining(c))


def title_tokens(title):
    return frozenset(w for w in re.findall(r"[a-z0-9]+", ascii_lower(title or "")) if w not in BD_STOP)


def match_title(title, candidates):
    """candidates : {identifiant: titre}. Titre identique, sinon contenu dans un seul autre."""
    want = title_tokens(title)
    if not want:
        return None
    exact = [i for i, t in candidates.items() if title_tokens(t) == want]
    if exact:
        return exact[0]
    part = [i for i, t in candidates.items() if len(want) >= 2 and want <= title_tokens(t)]
    return part[0] if len(part) == 1 else None


def match_film(title, movies):
    """Retrouve un film déjà connu (autres cinémas) à partir d'un titre approximatif."""
    return match_title(title, {i: f.get("titre") for i, f in movies.items()})


# Tract PDF : « TITRE EN MAJUSCULES / 1h30/Animation de Prénom Nom / synopsis ».
FLYER_HEAD = re.compile(
    r"^(?P<titre>[^\n]{2,80})\n(?P<h>\d)h(?P<m>\d{2})/(?P<genre>[A-Za-zÀ-ÿ' -]+?)(?: de (?P<real>[^\n]+))?\s*$",
    re.M)
FLYER_STOP = re.compile(
    r"Suivi d[’']un|PROGRAMM|TARIFS|Séance gratuite|Projection en avant|MOIS DU|PROCHAINEMENT|Maquette|AVANT-PREMI")
SMALL_WORDS = {"de", "du", "des", "la", "le", "les", "et", "au", "aux", "un", "une", "à", "en", "sur"}


def nice_title(title):
    t = " ".join(title.replace("’", "'").split())
    if not t.isupper():
        return t
    words = []
    for i, w in enumerate(t.lower().split(" ")):
        if i and w in SMALL_WORDS:
            words.append(w)
        elif "'" in w:
            a, b = w.split("'", 1)
            words.append(a + "'" + b[:1].upper() + b[1:] if i else a.capitalize() + "'" + b[:1].upper() + b[1:])
        else:
            words.append(w[:1].upper() + w[1:])
    return " ".join(words)


def find_flyer_url(page):
    links = [html.unescape(x) for x in re.findall(r'href="([^"]+?\.pdf[^"]*)"', page, re.I)]
    for link in links:
        if re.search(r"flyer|programme", link, re.I):
            return urllib.parse.urljoin(BD_URL, link)
    for link in links:
        if not re.search(r"tarif|d[ée]lib[ée]ration|actualisation", link, re.I):
            return urllib.parse.urljoin(BD_URL, link)
    return None


def parse_flyer(data):
    """Lit le tract PDF et renvoie une liste de fiches (titre, durée, genre, réalisateur, synopsis)."""
    from pypdf import PdfReader  # import tardif : dépendance facultative

    text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    heads = list(FLYER_HEAD.finditer(text))
    fiches = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        syn = " ".join(text[m.end():end].split())
        cut = FLYER_STOP.search(syn)
        if cut:
            syn = syn[:cut.start()]
        syn = re.sub(r"(\s[+-]\d{1,2})+\s*$", "", syn).strip()
        fiches.append({
            "titre": nice_title(m["titre"]),
            "duree_min": int(m["h"]) * 60 + int(m["m"]),
            "genre": m["genre"].strip(),
            "realisateur": (m["real"] or "").strip() or None,
            "synopsis": syn or None,
        })
    return fiches


def month_number(word):
    w = ascii_lower(word).strip(".")
    if w.startswith("juin"):
        return 6
    if w.startswith("juil"):
        return 7
    return {"jan": 1, "fev": 2, "mar": 3, "avr": 4, "mai": 5, "aou": 8,
            "sep": 9, "oct": 10, "nov": 11, "dec": 12}.get(w[:3])


def guess_year(month, day, today):
    for year in (today.year, today.year - 1, today.year + 1):
        try:
            if abs((datetime(year, month, day) - today).days) <= 180:
                return year
        except ValueError:
            return None
    return None


def parse_beaumont(page, start, end, movies, flyer=()):
    first, last = f"{start:%Y-%m-%d}", f"{end - timedelta(days=1):%Y-%m-%d}"
    tokens = list(BD_TOKEN.finditer(page))
    sessions, new_movies, image = [], {}, None
    for i, m in enumerate(tokens):
        if m.group(1):
            image = m.group(1)
            continue
        sm = BD_SESSION.match(plain(m.group(2)))
        if not sm or not image:
            continue
        month = month_number(sm.group(2))
        year = month and guess_year(month, int(sm.group(1)), start)
        if not year:
            continue
        day = f"{year}-{month:02d}-{int(sm.group(1)):02d}"
        if not first <= day <= last:
            continue
        stop = tokens[i + 1].start() if i + 1 < len(tokens) else len(page)
        seg = page[m.end():min(stop, m.end() + 2500)]
        text = plain(seg)
        dur = re.search(r"Dur[ée]e\s*:\s*(\d+)\s*h\s*(\d{2})?", text)
        trailer = re.search(r'href="(https?://(?:www\.)?(?:youtu\.be|youtube\.com)[^"]*)"', seg)
        slug = urllib.parse.unquote(image).rsplit("/", 1)[-1][:-4]
        guessed = " ".join(re.split(r"[_\-\s]+", slug)).strip()
        guessed = guessed[:1].upper() + guessed[1:]
        if dur:
            minutes = int(dur.group(1)) * 60 + int(dur.group(2) or 0)
            mid = match_film(guessed, {**movies, **new_movies})
            if not mid:
                fiche_id = match_title(guessed, {i: f["titre"] for i, f in enumerate(flyer)})
                fiche = flyer[fiche_id] if fiche_id is not None else {}
                title = fiche.get("titre") or guessed
                mid = "bd-" + re.sub(r"[^a-z0-9]+", "-", ascii_lower(title)).strip("-")
                new_movies[mid] = {
                    "titre": title, "titre_original": None, "affiche": None,
                    "genres": fiche.get("genre") or "", "duree_min": minutes,
                    "realisateurs": [fiche["realisateur"]] if fiche.get("realisateur") else [],
                    "acteurs": [], "synopsis": fiche.get("synopsis"),
                    "bande_annonce": trailer.group(1) if trailer else None,
                }
        else:  # pas de durée : animation ou conférence, le titre est dans le texte
            label = text[:90] or guessed
            mid = "bd-evt-" + re.sub(r"[^a-z0-9]+", "-", ascii_lower(label)).strip("-")[:40]
            new_movies[mid] = {"titre": label, "titre_original": None, "affiche": None, "genres": "",
                               "duree_min": None, "realisateurs": [], "acteurs": [], "synopsis": None}
        sessions.append({
            "date": day,
            "time": f"{int(sm.group(3)):02d}:{sm.group(4) or '00'}",
            "cinema": "BDL",
            "movie": mid,
            "version": "VOSTFR" if sm.group(5) else "VF",
            "screen": None,
        })
    return sessions, new_movies


def fetch_beaumont(start, end, movies):
    """Séances depuis la page de la mairie, fiches depuis le tract PDF (facultatif)."""
    page = get_text(BD_URL)
    flyer, warnings = [], []
    try:
        url = find_flyer_url(page)
        if url:
            flyer = parse_flyer(get_bytes(url))
        if not flyer:
            warnings.append("tract PDF introuvable ou illisible : fiches minimales")
    except ImportError:
        warnings.append("pypdf non installé : fiches minimales")
    except Exception as e:
        warnings.append(f"tract PDF : {e}")
    sessions, new_movies = parse_beaumont(page, start, end, movies, flyer)
    return sessions, new_movies, warnings


def main():
    now = datetime.now(ZoneInfo(TZ))
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=DAYS)
    prev = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {}
    first, last = f"{start:%Y-%m-%d}", f"{end - timedelta(days=1):%Y-%m-%d}"

    sessions, errors, failed, new_movies = [], [], set(), {}

    def keep_previous(c, e):
        failed.add(c["id"])
        errors.append(f"{c['ville']}: {e}")
        print(f"ERREUR {c['ville']}: {e}", file=sys.stderr)
        # on garde les dernières données connues de ce cinéma
        sessions.extend(s for s in prev.get("seances", [])
                        if s["cinema"] == c["id"] and first <= s["date"] <= last)

    for c in CINEMAS:
        if c["source"] == "beaumont":
            continue  # traité après les autres : il réutilise leurs fiches de films
        try:
            if c["source"] == "grandangle":
                got, ga_movies = fetch_grandangle(start, end)
                new_movies.update(ga_movies)
            else:
                got = fetch_sessions(c["id"], start, end)
            print(f"{c['ville']}: {len(got)} séances")
            sessions += got
        except Exception as e:
            keep_previous(c, e)

    movies = dict(prev.get("films", {}))
    movies.update(new_movies)
    try:
        ids = {s["movie"] for s in sessions if not s["movie"].startswith("ga-")}
        movies.update(fetch_movies(ids))
    except Exception as e:
        errors.append(f"films: {e}")
        print(f"ERREUR films: {e}", file=sys.stderr)

    for c in CINEMAS:
        if c["source"] != "beaumont":
            continue
        try:
            got, bd_movies, warnings = fetch_beaumont(start, end, movies)
            errors.extend(f"{c['ville']} : {w}" for w in warnings)
            print(f"{c['ville']}: {len(got)} séances", *warnings)
            sessions += got
            movies.update(bd_movies)
        except Exception as e:
            keep_previous(c, e)

    if len(failed) == len(CINEMAS):
        sys.exit("Aucun cinéma n'a pu être lu : programme.json conservé tel quel.")

    used = {s["movie"] for s in sessions}
    movies = {k: v for k, v in movies.items() if k in used}
    sessions.sort(key=lambda s: (s["date"], s["time"], s["cinema"], s["movie"]))
    result = {
        "genere_le": now.isoformat(timespec="minutes"),
        "du": first,
        "au": last,
        "cinemas": CINEMAS,
        "films": movies,
        "seances": sessions,
        "erreurs": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    print(f"{len(sessions)} séances, {len(movies)} films -> {OUT}")


if __name__ == "__main__":
    main()
