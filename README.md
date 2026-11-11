# FL Cowork

Produire à plusieurs sur le même projet FL Studio.

Chacun travaille dans son propre FL Studio. À chaque Ctrl+S, le projet complet (avec ses samples) part
chez les autres et se fusionne avec leur travail.

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

## Comment ça marche

Chacun travaille dans son FL Studio, sans rien changer à ses habitudes. À **chaque Ctrl+S** :

1. le projet complet est envoyé aux autres : notes, clips, automations, plugins et leurs réglages
   (Serum 2 compris), mixeur, tempo, et les samples qui manquent chez eux ;
2. chez chacun, la nouvelle version se charge toute seule, sans aucune question de FL Studio
   (ni « enregistrer les modifications ? », ni « projet d'une version plus récente »), même si vos
   versions de FL Studio diffèrent ;
3. **n'importe qui peut enregistrer, à tout moment** : il n'y a pas de tour de rôle.

Rien n'est synchronisé « en direct » pendant que vous jouez ou réglez : c'est l'enregistrement qui
déclenche l'envoi.

### Ce qui est partagé, et ce qui reste à vous

Tout ce qui appartient au morceau est partagé : notes, clips, automations, canaux, plugins et leurs
presets, mixeur complet (master compris), tempo, signature rythmique, noms et couleurs.

Vos réglages personnels de FL Studio ne sont **jamais** écrasés par ceux des autres : volume et pitch
généraux de FL, motif et filtre sélectionnés, taille de fenêtre, nom d'enregistrement, dossier de
données, fréquence d'échantillonnage, mode de lecture.

### Quand vous avez travaillé de votre côté

Si une version arrive alors que vous avez des modifications que vous n'avez pas encore envoyées, elles
sont enregistrées puis **fusionnées** avec la version reçue, puis le résultat est renvoyé aux autres :

- ce que vous seul avez changé est gardé, ce que l'autre seul a changé aussi ;
- les notes du piano roll des deux côtés sont réunies ;
- les clips de la playlist des deux côtés sont réunis **sans doublons** : un clip qui se trouve au même
  endroit, sur la même piste, avec le même contenu, est un seul et même clip, quel que soit son
  historique ; un clip réellement différent qui en chevauche un autre est **décalé sur la piste libre
  la plus proche** (vers le bas, sinon vers le haut) ;
- un clip déplacé ou supprimé d'un côté suit ce changement, sans laisser de copie derrière lui ;
- les ajouts de canaux, de patterns et de plugins faits d'un côté et de l'autre sont gardés, même si vous
  avez créé un instrument en même temps (le vôtre est renuméroté, chacun garde son synthé, son preset et
  ses notes) ;
- un simple enregistrement de FL Studio (horodatage, numéros internes) n'est pas une modification : il
  ne déclenche aucun envoi ;
- si le même réglage a été modifié des deux côtés, **la valeur de celui qui enregistre** est gardée,
  et l'application le dit dans la discussion.

Une copie de votre version d'avant la fusion est conservée dans le dossier `Sauvegardes` de la
session.

### Quand la fusion n'est pas ce que vous voulez

Deux boutons de l'application court-circuitent la fusion. Ils servent surtout quand vous avez ouvert
le mauvais projet : fusionner deux fichiers sans rapport donnerait n'importe quoi.

- **Imposer ma version** : votre projet, tel qu'il est chez vous, remplace la version partagée chez tous.
  Chez les autres, leur travail non envoyé est copié dans leur dossier `Sauvegardes`, puis ils chargent
  votre version sans fusion.
- **Prendre leur version** : vous rechargez la dernière version partagée, sans fusion. Votre projet
  actuel est copié dans `Sauvegardes` avant d'être remplacé.

Ctrl+S et le bouton **Envoyer et fusionner** font, eux, toujours une fusion : jamais d'écrasement.

## Samples

Les samples personnels utilisés dans le projet sont envoyés automatiquement à chaque enregistrement, et
reliés au projet chez les autres. Un sample se charge donc même s'il n'a jamais existé sur leur
machine. Les samples fournis avec FL Studio ne sont pas transférés, puisque tout le monde les a.

## Plugin manquant

Si le projet utilise un plugin qu'un participant n'a pas :

- une boîte de dialogue le lui indique, et les autres sont prévenus dans la discussion ;
- la session continue normalement ;

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

Python 3.13 ou plus récent est nécessaire (Tkinter inclus, c'est le cas par défaut sous Windows).
