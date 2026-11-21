# Cinémas de Lectoure, Fleurance et Mauvezin : programme de la semaine

Site qui affiche, pour les 7 prochains jours, les séances du **Sénéchal (Lectoure)**,
du **Grand Angle (Fleurance)** et du **Ciné Mauv' (Mauvezin)** : titre, version
(VF ou VOSTFR), horaires, affiche et, au clic sur le titre, réalisateur, acteurs et synopsis.

Les données viennent de deux sources, sans clé d'API ni compte :

- **Lectoure et Mauvezin** : l'API que le site de Ciné 32 (cine32gers.com) utilise lui-même.
- **Fleurance** : le Grand Angle a quitté Ciné 32. Ses séances viennent de son propre site, cinegrandangle.fr
  (fichier `/data.json`, ou à défaut le bloc de données intégré à la page `/programme`).

## Fonctionnement

1. `scripts/collect.py` interroge ces sources, une fois par jour, et écrit `programme.json`.
2. Le workflow `.github/workflows/update.yml` lance ce script chaque matin et enregistre le résultat dans le dépôt.
3. GitHub Pages publie la racine du dépôt : la page `index.html` lit `programme.json`.

## Installation (une seule fois)

1. Créez un dépôt GitHub (public) et déposez-y tout le contenu de ce dossier.
2. **Settings → Actions → General → Workflow permissions** : choisissez *Read and write permissions*, puis *Save*.
3. Onglet **Actions** → *Mise à jour du programme* → **Run workflow**. Après environ 30 secondes, `programme.json` apparaît dans le dépôt.
4. **Settings → Pages** : *Source* = *Deploy from a branch*, branche `main`, dossier `/ (root)`, puis *Save*.
5. Le site est disponible à l'adresse `https://VOTRE-NOM.github.io/NOM-DU-DEPOT/` (délai de 1 à 2 minutes la première fois).

## Tester sur votre ordinateur

```bash
python scripts/collect.py          # écrit programme.json
python -m http.server              # puis ouvrez http://localhost:8000
```

## Comment sont déterminées les versions

**Lectoure et Mauvezin (Ciné 32)** : l'API marque chaque séance avec une étiquette :

| Étiquette de l'API | Affichage |
|---|---|
| `Localization.Version.Original` | **VOSTFR** (version originale, sous-titrée en français en salle) |
| `Localization.Language.French` | **VF** |
| autre ou absente | aucune mention |

**Fleurance (Grand Angle)** : le site indique directement `VF` ou `VOST` (affiché VOSTFR).
Les séances spéciales (avant-première, rencontre) affichent leur intitulé sous les horaires.

## Cinémas suivis

| Ville | Salle | Identifiant | Source |
|---|---|---|---|
| Lectoure | Le Sénéchal | `P1039` | Ciné 32 |
| Fleurance | Grand Angle | `P1051` (identifiant interne) | cinegrandangle.fr |
| Mauvezin | Ciné Mauv' | `P1042` | Ciné 32 |

Pour ajouter un autre cinéma de Ciné 32, ajoutez une ligne dans `CINEMAS` (`scripts/collect.py`, `"source": "cine32"`)
et une couleur `--c-Pxxxx` dans `index.html`.

## Si un cinéma n'affiche rien

- La page indique « le programme n'est pas encore publié » : le cinéma n'a simplement pas encore mis ses séances en ligne.
- Si l'API est indisponible pour un cinéma, le script conserve les dernières séances connues pour celui-ci et note l'erreur dans `programme.json` (champ `erreurs`). Le workflow n'échoue que si **aucun** cinéma n'a pu être lu.
- Le Grand Angle met son programme en ligne par semaine : les jours non encore publiés n'apparaissent simplement pas.
- Si l'une des sources change de forme un jour, le workflow le signalera par un e-mail GitHub d'échec : il faudra alors adapter `collect.py`.

## Bon usage

- Une seule collecte par jour, avec un en-tête identifiant le projet : merci de ne pas la multiplier.
- Il est courtois de prévenir Ciné 32 et le Grand Angle de l'existence du site, et de leur demander s'ils proposent un flux officiel.
- Les affiches sont chargées depuis le serveur d'images d'AlloCiné (Lectoure, Mauvezin) et celui du Grand Angle (Fleurance) ; elles restent la propriété de leurs ayants droit.
- Les horaires peuvent changer : le pied de page invite à vérifier auprès du cinéma.
