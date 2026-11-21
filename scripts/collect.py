#!/usr/bin/env python3
"""Collecte le programme des cinémas de Lectoure, Fleurance et Mauvezin.

Sources :
- Lectoure et Mauvezin : l'API utilisée par le site cine32gers.com (Ciné 32) ;
- Fleurance (Grand Angle) : les données publiées par cinegrandangle.fr.
Écrit programme.json à la racine du dépôt.
Aucune dépendance : bibliothèque standard uniquement (Python 3.9+).
"""
import json
import sys
import time
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
]
OUT = Path(__file__).resolve().parent.parent / "programme.json"
HEADERS = {
    "User-Agent": "programme-cinemas-gers/1.0 (projet personnel, une collecte par jour)",
    "Referer": "https://www.cine32gers.com/",
    "Accept": "application/json",
}


def get_text(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8")
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


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


def main():
    now = datetime.now(ZoneInfo(TZ))
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=DAYS)
    prev = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {}
    first, last = f"{start:%Y-%m-%d}", f"{end - timedelta(days=1):%Y-%m-%d}"

    sessions, errors, new_movies = [], [], {}
    for c in CINEMAS:
        try:
            if c["source"] == "grandangle":
                got, ga_movies = fetch_grandangle(start, end)
                new_movies.update(ga_movies)
            else:
                got = fetch_sessions(c["id"], start, end)
            print(f"{c['ville']}: {len(got)} séances")
            sessions += got
        except Exception as e:  # on garde les anciennes données de ce cinéma
            errors.append(f"{c['ville']}: {e}")
            print(f"ERREUR {c['ville']}: {e}", file=sys.stderr)
            sessions += [s for s in prev.get("seances", [])
                         if s["cinema"] == c["id"] and first <= s["date"] <= last]
    if len(errors) == len(CINEMAS):
        sys.exit("Aucun cinéma n'a pu être lu : programme.json conservé tel quel.")

    ids = {s["movie"] for s in sessions}
    movies = dict(prev.get("films", {}))
    movies.update(new_movies)
    try:
        movies.update(fetch_movies({i for i in ids if not i.startswith("ga-")}))
    except Exception as e:
        errors.append(f"films: {e}")
        print(f"ERREUR films: {e}", file=sys.stderr)
    movies = {k: v for k, v in movies.items() if k in ids}

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
