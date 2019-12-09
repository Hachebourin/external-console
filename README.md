# external-console

## Contexte

- Il n’est pas évident avec ansible d’exécuter des commandes dans des interpreteurs de commandes (mysql, hbase, sqlplus, dgmgrl, shell …)

- Les modules pour le faire n'existent pas forcément (hbase, sqlplus, dgmgrl ...)

- Il n’est pas possible de garder la même session ssh pour exécuter plusieurs commandes

## Solution

- Récupération de la liste des commandes à exécuter

- Création d’une session ssh vers la machine cible

- Exécution des commandes via la même connexion ssh

- Vérification pour chaque commande du résultat via une regex

- La liste des commandes est appelé procedure

- Une procedure doit etre execute qu'une seule fois (utilisation des clean facts pour relancer la procedure de zero)

- Une procedure garde en memoire la derniere commande en echec pour etre reexecute

## POC

- Création d’un action plugin ansible

- Utilisation de la librairie python paramiko pour créer la connexion ssh

- Utilisation d’un fichier yml (playbook ansible) pour définir les commandes à exécuter et autres paramètres

- L’action plugin va récupérer l’ensemble des paramètres contenu dans le playbook pour initialiser la connexion ssh, exécuter les commandes, vérifier les resultats …

- Utilisation d’un fichier de fact pour connaitre l’état d’exécution de chaque commande et reprendre la procédure à la dernière commande en échec.

## Exemple

```
---
- hosts: admin
  tasks:
    - name: "SHELL procedure"
      send_cmd:
        clean_fact: "{{ clean_fact_var }}"
        procedure:
          - order: 1
            type: SHELL
            host: "localhost"
            commands:
              - order: 1
                cmd: "\\ls -l"
                # The [^;] is a character class, it matches everything but a semicolon.
                # match first occurence \r\n : [^(\r\n)]*
                expected: "ls (?P<WORD>[^(\r\n)]*).*vagrant"

              - order: 2
                cmd: "ls -l /etc/"
                expected: ".*ls.*hosts.*vagrant.*"
```

- clean_fact : boolean => Purge des facts contenant l’état d’exécution de la procédure

- order : ordre d’exécution des blocs de commandes et des commandes

- host: machine cible ou seront exécuté les commandes

- type : le type d'interpreteur

- cmd : commande à exécuter

- expected : résultat attendu (sous forme de regex)

- timeout : durée max pour que la regex match sinon erreur

## Fichier des facts :

```
{
    "1": {
        "1": true,
        "2": true,
        "complete": true
    },
    "2": {
        "1": true,
        "2": true,
        "complete": true
    },
    "complete": true
}
```

- Le fichier des facts se trouve : `/etc/ansible/facts.d/check.fact`

- La première clé correspond à un bloc de commandes de type hbase, shell, dgmgrl …

- Pour chaque bloc, il y a une clé « complete » qui indique la bonne exécution du bloc

- La deuxième clé correspond à la bonne exécution d’une commande dans un bloc

- Pour l’ensemble des blocs, il y a une clé « complete » qui indique la bonne exécution de la procédure.

## Execution

Prerequis :

- Utilisateur vagrant avec une cle ssh id_rsa
- Autoriser la connection ssh par cle en localhost a vagrant

Lancement du playbook :

- ansible-playbook send_cmd_playbook.yml -i inventory/hosts -vvv 

Reinitialisation des facts :

- ansible-playbook send_cmd_playbook.yml -i inventory/hosts -vvv --extra-vars "{'clean_fact_var':true}"
