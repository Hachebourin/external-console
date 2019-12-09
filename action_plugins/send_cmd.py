#!/usr/bin/python
import time, re
import socket, paramiko
from collections import OrderedDict
from ansible.plugins.action import ActionBase
from ansible.parsing.yaml.objects import AnsibleUnicode
from ansible.errors import AnsibleError

import os, tempfile, shutil, json, copy
class Fact(object):
    def __init__(self, dir, name ):
        self.dir = dir
        self.name = name
        self.value = {}
        self.file = os.path.join(self.dir, self.name) + EXT
        self._create_file()
        self.current = self._get_current_value()

    def immortalize(self, value):
        if self._diff(value):
        # pas d'union entre l existant et les nouvelles valeurs pour pouvoir supprimer des datas
        #      self.value = dict(self.current.items() + self.value.items())
            self._write_datas(value)
            return True
        return False

    def append(self, value, key=None):
        self.current = self._get_current_value()
        new = self._get_current_value()
        # new = self.current.copy()
        if key == None:
            new.update(value)
        else:
            if not str(key) in new:
                new[str(key)]={}
            new[str(key)].update(value)
        value = new
        return self.immortalize(value)

    def remove(self):
        self.current = self._get_current_value()
        new = self._get_current_value()
        value = self._remove(new, value)
        return self.immortalize(value)

    # fonction recursive de suppression des cles dans le dictionnaire base
    def _remove(self, base, delete):
        # pour toutes les cles a supprimer
        for key in delete.keys():
            # si la cle  correspond a un dictionnaire pour la valeur courrante et la valeur a supprimer
            # on recurse afin de ne supprimer que les cles concernees dans le dictionnaire fils
            if key in base.keys() and isinstance(base[key], dict) and isinstance(delete[key], dict):
                base[key] = self._remove(base[key], rm[key])
            elif key in base.keys():
                # suppression de la cle et de sa valeur dans le dictionnaire de base
                del base[key]
        return base

    def clean(self):
        if not os.path.isfile(self.file):
            return False
        os.remove(self.file)
        self._create_file()
        return True

    def _get_current_value(self):
        if os.stat(self.file).st_size == 0:
            return json.loads("{}")
        tmpstr = ""
        with open(self.file) as current_file:
            for line in current_file:
                tmpstr += line
        datas = json.loads(tmpstr)
        return datas

    def _diff(self, value):
        return self.current != value

    def _create_file(self):
        if not os.path.isdir(self.dir):
            os.makedirs(self.dir)
            # maj des droits en 0755 pour /etc/ansible et /etc/ansible/facts.d en 0755 pour
            # surcharger les droits imposes par umask
            os.chmod(os.path.dirname(self.dir), 0755)
            os.chmod(self.dir, 0755)
        if not os.path.isfile(self.file):
            open(self.file, "w").close()
            os.chmod(self.file, 0644)

    def _write_datas(self, value):
        fh, abs_path = tempfile.mkstemp()
        new_file = open(abs_path, "w")
        new_file.write(json.dumps(value))
        new_file.close()
        os.close(fh)
        os.remove(self.file)
        shutil.move(abs_path, self.file)
        os.chmod(self.file, 0644)

DIR = "/etc/ansible/facts.d/"
EXT = ".fact"

def send_string_and_wait_for_string(command, wait_string, should_print, shell, timeout, fact_cache):
    flag=False
    timeout = time.time() + timeout
    output, receive_buffer= "", ""

    shell.setblocking(0)
    shell.send(command+"\n")

    match = re.search(r'%s' % wait_string, receive_buffer, re.S)

    while not match and time.time() < timeout:
        try:
            receive_buffer = shell.recv(1024)
            output+=receive_buffer
            # wait_string='.*ls(?P<word>.*)vagrant'
            match = re.search(r'%s' % wait_string, output, re.S)
            if match and match.groupdict():
                group_name=list(match.groupdict())[0]
                fact_cache[group_name] = match.groupdict()[group_name]
        except (socket.timeout) as error:
            pass

        if match: flag=True
        time.sleep(1)

    return output, flag

def bloc_not_complete(check_fact, order):
    # Si la procedure n'est pas terminee et que le bloc de commande n'est pas termine
    if not ('complete' in check_fact and check_fact['complete']) \
    and not ( order in check_fact and
            'complete' in check_fact[order] and
             check_fact[order]['complete']):
        return True

def cmd_not_complete(check_fact, order, cmd):
    if not order in check_fact or \
            not str(cmd) in check_fact[order] or \
            not check_fact[order][str(cmd)]:
        return True

def build_result(fact, output, result, flag, order, cmd, bloc_cmds ):
    result[order][cmd]={}
    result[order][cmd]['command'] = bloc_cmds[cmd][0]
    result[order][cmd]['expected'] = bloc_cmds[cmd][1]
    result[order][cmd]['output'] = output.replace('\r',' ').split('\n')

    if not flag:
        fact.append({ str(cmd) : False }, order)
        result['failed']=True
        result[order]['state'] = "failed"
        return False
    else:
        fact.append({ str(cmd) : True }, order)
    return True

class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):

        result = super(ActionModule, self).run(task_vars)

        clean_fact = self._task.args.get('clean_fact',False)
        procedure = self._task.args.get('procedure',False)

        fact_cache = {}
        fact = Fact(DIR, 'check')
        # On efface les facts pour rejouter la procedure de zero
        if clean_fact:
            fact.clean()
            fact.immortalize({"0" : {'init':True} })

        for bloc in procedure:
            host = bloc["host"]
            init_commands = "" if not "init_commands" in bloc else bloc["init_commands"]
            commands = bloc["commands"]
            order = str(bloc["order"])
            type = bloc["type"]

            init_bloc_cmds={}
            for command in init_commands:
                timeout = 10 if not 'timeout' in command else command['timeout']
                init_bloc_cmds[command['order']] = [ command['cmd'], command['expected'], timeout ]

            bloc_cmds={}
            for command in commands:
                timeout = 10 if not 'timeout' in command else command['timeout']
                bloc_cmds[command['order']] = [ command['cmd'], command['expected'], timeout ]

            # Initialisation de la connexion SSH
            k = paramiko.RSAKey.from_private_key_file("/home/vagrant/.ssh/id_rsa",password=None)
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(host, username = "vagrant", pkey = k)
            shell = ssh.invoke_shell()

            # Chargement des facts
            with open(DIR+"check.fact") as json_data:
                check_fact=json.load(json_data)

            result[order] = {}

            if bloc_not_complete(check_fact, order):
                init_bloc_cmds = OrderedDict(sorted(init_bloc_cmds.items(), key=lambda t: t[0]))
                bloc_cmds = OrderedDict(sorted(bloc_cmds.items(), key=lambda t: t[0]))

                # S'il y a des commandes d'init (on les lance a chaque fois)
                if init_bloc_cmds:
                    for cmd in init_bloc_cmds:
                        output, flag = send_string_and_wait_for_string(init_bloc_cmds[cmd][0], init_bloc_cmds[cmd][1], True, shell,  init_bloc_cmds[cmd][2], fact_cache)
                        if not build_result(fact, output, result, flag, order, cmd, init_bloc_cmds):
                            return result

                for cmd in bloc_cmds:
                    if cmd_not_complete(check_fact, order, cmd):

                        if "WORD" in fact_cache:
                            bloc_cmds[cmd][0] = re.sub('(\[CACHE:.*\])', fact_cache["WORD"], bloc_cmds[cmd][0])
                        output, flag = send_string_and_wait_for_string(bloc_cmds[cmd][0], bloc_cmds[cmd][1], True, shell,  bloc_cmds[cmd][2], fact_cache)
                        if not build_result(fact, output, result, flag, order, cmd, bloc_cmds):
                            return result

            # On passe l'execution du bloc en complete
            result[order]['state'] = "success"
            fact.append({ "complete" : True }, order)
            shell.close()
        # On passe l'execution de la procedure en complete
        fact.append({ 'complete' : True })
        return result
