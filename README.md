# FL Cowork

Produire à plusieurs, en même temps, sur le même projet FL Studio.

**Installation : lancer `dist\FLCoworkSetup.exe`** (chaque participant). Il installe l'application,
le script FL Studio et le port MIDI virtuel, puis démarre FL Cowork.

## Utilisation

1. Une seule fois, dans FL Studio : *Options › MIDI settings › Input › « FL Cowork » ›
   Controller type « FL Cowork » › Enable*. Le voyant « FL Studio connecté » passe au vert.
2. **Héberger** : choisir un `.flp` (ou laisser vide pour un projet neuf) › *Créer la session* ›
   envoyer le code `FLC-…` aux autres.
3. **Rejoindre** : coller le code › *Rejoindre*. Le projet et ses samples arrivent et s'ouvrent dans FL.

## Ce qui est synchronisé

| En direct (tout le monde, en même temps) | Par publication (détenteur du « stylo ») |
|---|---|
| Mixeur : volume, pan, stéréo, mute, EQ, routages et niveaux d'envoi, noms, couleurs | Notes du piano roll |
| Canaux : volume, pan, pitch, mute, piste mixeur cible, noms, couleurs | Clips de la playlist, automations |
| Step sequencer (64 pas, tous les patterns) | Ajout / suppression de canaux, plugins, effets |
| Paramètres des plugins (générateurs et effets) | Nouveaux samples (copiés et transférés automatiquement) |
| Tempo, noms/couleurs des patterns et pistes de playlist | |
| Lecture / stop (option) | |

Le **stylo** ✏️ : une personne à la fois modifie la *structure*. Chaque Ctrl+S du détenteur publie
une nouvelle version que les autres chargent automatiquement. Le stylo se demande et se donne d'un clic
(le projet du détenteur est enregistré et publié avant le passage).

Pourquoi cette limite : l'API de script de FL Studio ne donne accès ni aux notes ni aux clips, et ne
permet pas de créer de canaux ou de plugins. Tout ce qu'elle expose est synchronisé en direct ; le reste
passe par le fichier `.flp`.

## Architecture

```
FL Studio ── script Python (device_FLCowork.py) ── SysEx MIDI (port virtuel) ── FL Cowork (app)
                                                                    │ TLS-PSK (clé dans le code de session)
                                              autres participants ──┴── hub (dans l'app de l'hôte)
```

- `fl_script/device_FLCowork.py` — tourne dans FL. Observe l'état par passes bornées en temps
  (1,5 ms par tick, 4 ms après une action, plugin au premier plan prioritaire), n'émet que les différences,
  applique les valeurs distantes sans écho. Aucun appel bloquant. Le Python de FL Studio interdit
  les sockets et l'écriture de fichiers : le script échange avec l'application en SysEx sur la boucle
  MIDI virtuelle « FL Cowork » ↔ « FL Cowork Bus » (`cowork/midi.py`). Diagnostic : View › Script output.
- `cowork/hub.py` — ordonne les opérations (numéro de séquence par opération, le dernier écrivain gagne,
  convergence garantie), stocke les révisions par empreinte SHA-1, gère le stylo.
- `cowork/app.py` — relie script et hub, regroupe les envois (30 ms), surveille le `.flp`, transfère
  projet et samples (seuls les fichiers manquants, compressés), sert l'interface.
- `cowork/flp.py` — lit le `.flp` pour retrouver les samples à embarquer.
- `cowork/setup.py` — installation ; `cowork/upnp.py` — ouverture/fermeture du port sur la box.

Garde-fous : si la structure d'un participant diverge (canal ajouté sans le stylo, plugin manquant),
sa synchro directe est suspendue jusqu'au rechargement, pour ne pas propager de valeurs décalées.
Un paramètre automatisé qui « se bat » entre deux machines est détecté et retiré de la synchro.

## Réseau

- Même réseau local ou VPN (Tailscale, ZeroTier…) : le code « Même réseau » suffit.
- Internet : l'hôte ouvre automatiquement le port TCP 47810 par UPnP (refermé en fin de session).
  Si la box refuse : rediriger ce port à la main puis générer un code avec l'IP publique.
- Tout le trafic est chiffré et authentifié par la clé contenue dans le code de session.

## Samples, plugins manquants, Serum 2

**Samples.** À chaque publication, les samples utilisateur du projet sont copiés dans le dossier de session
et envoyés (seuls les fichiers nouveaux transitent). À la réception, les chemins du `.flp` sont réécrits vers
les copies locales : le sample se charge même s'il n'a jamais existé sur la machine de l'autre. Deux samples
de même nom sont distingués automatiquement ; un sample introuvable chez l'auteur est signalé. Les samples
d'usine de FL ne sont pas transférés (tout le monde les a).

**Plugin manquant.** Chaque version embarque la liste des plugins du projet. S'il en manque un chez un
participant : une boîte de dialogue le lui indique, les autres sont prévenus dans la discussion, et la session
continue — seuls les réglages de ce plugin sont exclus de la synchro chez lui.

**Serum 2 (et tout VST).** Tous les paramètres exposés à l'hôte sont synchronisés en direct (≈ 540 pour
Serum 2 ; le script ignore les 3 700 emplacements vides annoncés par FL). Un changement de preset est détecté :
les réglages suivent immédiatement et les autres sont prévenus. Le contenu interne d'un preset qui n'est pas
un paramètre (tables d'ondes, samples, matrice de modulation) n'est pas accessible aux scripts FL : il est
transmis avec la publication suivante (Ctrl+S du détenteur du stylo).

## Limites connues

- Les samples chargés *à l'intérieur* d'un plugin (Slicex, DirectWave, oscillateur sample de Serum…) ne sont
  pas détectés : seuls les samplers et clips audio de FL le sont.
- Le port MIDI virtuel repose sur Windows MIDI Services (Windows 11 récent). Sinon : installer
  loopMIDI et créer deux ports reliés nommés « FL Cowork » et « FL Cowork Bus ».
- Windows uniquement. La lecture n'est pas synchronisée à l'échantillon près (chacun écoute chez soi).

## Développement

```
py -3.14 tests\test_e2e.py                                   # deux apps + deux faux FL Studio
py -3.14 -m cowork                                           # lancer sans installer
powershell -ExecutionPolicy Bypass -File build.ps1           # reconstruire l'exe
```
