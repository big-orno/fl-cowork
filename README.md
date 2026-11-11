# FL Cowork

Produire à plusieurs, en même temps, sur le même projet FL Studio.

Chacun travaille dans son propre FL Studio. Les réglages se synchronisent en direct entre les
participants, et le projet (avec ses samples) se partage d'un clic.

## Prérequis

- Windows 11 à jour
- FL Studio 2025
- Les mêmes plugins tiers chez tous les participants (voir « Plugin manquant » plus bas)

## Installation

À faire par chaque participant.

1. Télécharger `FLCoworkSetup.exe` depuis la
   [dernière release](https://github.com/big-orno/fl-cowork/releases/latest) et le lancer.
2. Accepter la demande de droits administrateur : elle sert à créer un port MIDI virtuel, par lequel
   FL Studio et l'application communiquent.
3. Dans FL Studio, une seule fois : **Options › MIDI settings › Input**, cliquer sur « FL Cowork »,
   choisir le *Controller type* « FL Cowork », puis activer **Enable**.

Dans l'application, le voyant « FL Studio connecté » passe au vert.

> Windows peut afficher un avertissement au lancement, car l'exécutable n'est pas signé :
> « Informations complémentaires » puis « Exécuter quand même ».

## Démarrer une session

**Héberger**
1. Choisir un projet `.flp`, ou laisser vide pour partir d'un projet neuf et lui donner un nom.
2. Cliquer sur **Créer la session**.
3. Envoyer le code `FLC-…` aux autres participants.

**Rejoindre**
1. Coller le code reçu.
2. Cliquer sur **Rejoindre** : le projet et ses samples arrivent et s'ouvrent dans FL Studio.

> Le code de session donne accès à la session : ne l'envoyez qu'aux personnes invitées, pas dans un
> salon public.

## Ce qui se synchronise

### En direct (quelques millisecondes, pour tout le monde, en même temps)

- **Mixeur** : volume, pan, mute, solo, EQ, routages, noms, couleurs
- **Canaux** : volume, pan, pitch, mute, piste cible, noms, couleurs
- **Step sequencer** (les pas de chaque pattern)
- **Paramètres des plugins**, instruments et effets (Serum 2 compris)
- **Tempo**, noms et couleurs des patterns et des pistes
- **Lecture / stop** (option)

### À la publication (Ctrl+S du détenteur du stylo)

- **Notes du piano roll**
- **Clips de la playlist** et automations
- **Structure** : ajout ou suppression de canaux, de plugins, d'effets
- **Nouveaux samples**

Cette séparation vient de FL Studio : ses scripts n'ont accès ni aux notes ni aux clips. Ce qu'ils
exposent est synchronisé en direct, le reste passe par le fichier projet.

### Le stylo ✏️

Une seule personne à la fois publie les versions du projet. C'est elle qui tient le stylo.

- Chaque **Ctrl+S** du détenteur publie une nouvelle version.
- Le stylo se demande et se donne d'un clic dans l'application.
- Tout ce qui est « en direct » reste modifiable par tout le monde, en même temps.

### Quand une nouvelle version arrive

Elle se charge automatiquement, sans aucune question de FL Studio (ni « enregistrer les
modifications ? », ni « projet d'une version plus récente »), même si vos versions de FL Studio
diffèrent.

Votre travail non publié n'est pas perdu : il est enregistré automatiquement, puis **combiné** à la
nouvelle version :

- vos notes du piano roll s'ajoutent à celles reçues ;
- vos clips de playlist s'ajoutent aussi, et si l'un chevauche un clip existant, il est **décalé
  sur la piste libre la plus proche** (vers le bas, sinon vers le haut) ;
- si vous avez ajouté ou retiré des canaux ou des patterns, la combinaison n'est pas possible : votre
  version est conservée dans le dossier `Sauvegardes` de la session, et l'application vous le dit.

Vos ajouts restent chez vous jusqu'à ce que vous teniez le stylo et publiez.

## Samples

Les samples personnels utilisés dans le projet sont envoyés automatiquement à chaque publication, et
reliés au projet chez les autres. Un sample se charge donc même s'il n'a jamais existé sur leur
machine. Les samples fournis avec FL Studio ne sont pas transférés, puisque tout le monde les a.

## Plugin manquant

Si le projet utilise un plugin qu'un participant n'a pas :

- une boîte de dialogue le lui indique, et les autres sont prévenus dans la discussion ;
- la session continue normalement ;
- seuls les réglages de ce plugin ne sont pas synchronisés chez lui.

## Serum 2 et autres VST

Tous les réglages qu'un plugin expose à FL Studio sont synchronisés en direct. Un changement de preset
est détecté : les réglages suivent tout de suite et les autres participants sont prévenus.

Le contenu interne d'un preset qui n'est pas un réglage (tables d'ondes, samples internes, matrice de
modulation) arrive à la publication suivante : Ctrl+S du détenteur du stylo.

## Réseau

- **Même réseau local ou VPN** : le code « Même réseau » suffit.
- **Internet** : l'application de l'hôte tente d'ouvrir automatiquement un port sur sa box le temps de
  la session, puis le referme. Si la box refuse, l'application indique quoi faire.
- Les échanges entre participants sont chiffrés.

## En cas de problème

| Symptôme | À vérifier |
|---|---|
| « FL Studio déconnecté » | L'étape 3 de l'installation, puis redémarrer FL Studio |
| Pas de port « FL Cowork » dans FL | Relancer l'installateur, ou cliquer sur « Réparer l'installation » |
| « Nouvelle version à charger » | Cliquer sur **Charger** dans l'application |
| « Structure différente » | Un canal a été ajouté sans le stylo : recharger la version, ou demander le stylo |
| Erreur du script | Dans FL Studio : **View › Script output**, onglet « FL Cowork » |

## Limites connues

- Windows uniquement.
- Les samples chargés *à l'intérieur* d'un plugin (Slicex, DirectWave, oscillateur sample de Serum…)
  ne sont pas transférés automatiquement.
- La lecture n'est pas synchronisée à l'échantillon près : chacun écoute chez soi.
- Sur un Windows sans service MIDI récent, il faut créer le port virtuel avec un outil tiers comme
  loopMIDI (deux ports reliés, nommés « FL Cowork » et « FL Cowork Bus »).

## Désinstaller

**Paramètres Windows › Applications › FL Cowork › Désinstaller.** Les sessions enregistrées dans
`Documents\FL Cowork` sont conservées.

## Pour les développeurs

| Dossier | Rôle |
|---|---|
| `fl_script/` | Script chargé par FL Studio : observe le projet et applique les changements reçus |
| `cowork/` | Application : session, réseau, partage du projet, interface, installation |
| `tests/` | Test de bout en bout avec deux applications et deux FL Studio simulés |

```
py -3.14 tests\test_e2e.py                            # lancer les tests
py -3.14 -m cowork                                    # lancer l'application sans l'installer
powershell -ExecutionPolicy Bypass -File build.ps1    # reconstruire l'installateur
```

Python 3.13 ou plus récent est nécessaire.
