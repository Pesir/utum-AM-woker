#!/usr/bin/python
import logging

import paramiko
import time
import socket
import re
import yaml


# Class for SSH CLI
class SwitchSSHCLI:

    def __init__(self, **paramiko_ssh_connection_args):
        """
        Init all variables and starts login
        :param module: module objects itself
        """

        # Login
        self.ssh_client = paramiko.SSHClient()
        # Default AutoAdd as Policy
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # Connect to Switch via SSH
        self.ssh_client.connect(**paramiko_ssh_connection_args)
        self.prompt = ''
        # SSH Command execution not allowed, therefor using the following paramiko functionality
        self.shell_chanel = self.ssh_client.invoke_shell()
        self.shell_chanel.settimeout(8)
        # AOS-Switch specific
        self.additional_connection_setup()

    def execute_cli_command(self, command_list):
        """
        Executes the list of CLI commands
        :param command_list: List of Strings with commands
        """
        for command in command_list:
            self.in_channel(command)

    def execute_show_command(self, command_list):
        """
        Execute show command and returns output
        :param command_list: list of commands
        :return: output of show command
        """
        # Regex for ANSI escape chars, prompt and hostname command
        ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
        prompt = re.compile(r'' + re.escape(self.prompt.replace('#', '')) + '.*#')
        hostname = re.compile(r'^ho[^ ]*')

        cli_output = []
        for command in command_list:
            if hostname.search(command):
                logging.error(
                    msg='You are not allowed to change the hostname while using show command function.')
                return
            self.in_channel(command)
            count = 0
            text = ""
            fail = True
            while count < 120:
                time.sleep(0.5)
                curr_text = self.out_channel()
                text += ansi_escape.sub('', curr_text).replace('\r', '')
                if prompt.search(curr_text):
                    fail = False
                    break
                count += 1

            if fail:
                logging.error(msg='Unable to read CLI Output in given Time')
                return

            # Format Text
            text_lines = text.split('\n')[:-1]
            # Remove Command from Output
            if text_lines:
                text_lines[0] = text_lines[0].replace(command, '', 1)
            cli_output.append('\n'.join(text_lines))
        return cli_output

    def additional_connection_setup(self):
        """
        Additional needed Setup for Connection
        """
        chanel_out = ''
        # Max Timeout ca. 1.30 Min (45 * 2)
        count = 0
        no_fail = False
        while count < 120:
            chanel_out += self.out_channel()
            if 'any key to continue' in chanel_out:
                self.in_channel("")
                no_fail = True
                break
            else:
                time.sleep(0.8)
            count += 1

        if not no_fail:
            logging.error(msg='Unable to connect correctly to Switch')
            return

        # Additional Sleep
        time.sleep(1)
        # Clear buffer
        self.out_channel()

        # Set prompt
        count = 0
        self.in_channel("")
        # Regex for ANSI escape chars and prompt
        ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
        text = ''
        while count < 110:
            time.sleep(0.8)
            curr_text = self.out_channel()
            text += ansi_escape.sub('', curr_text).replace('\r', '')
            if '#' in curr_text:
                fail = False
                break
            count += 1

        if fail:
            logging.error(msg='Unable to read CLI Output in given Time for prompt')
            return

        text.strip('\n')
        self.prompt = text.replace(' ', '')

    def out_channel(self):
        """
        Clear Buffer/Read from Shell
        :return: Read lines
        """
        recv = ""
        # Loop while shell is able to recv data
        while self.shell_chanel.recv_ready():
            recv = self.shell_chanel.recv(65535)
            if not recv:
                logging.error(msg='Chanel gives no data. Chanel is closed by Switch.')
                return
            recv = recv.decode('utf-8', 'ignore')
        return recv

    def in_channel(self, cmd):
        """
        Sends cli command to Shell
        :param cmd: the command itself
        """
        cmd = cmd.rstrip()
        cmd += '\n'
        cmd = cmd.encode('ascii', 'ignore')
        self.shell_chanel.sendall(cmd)

    def logout(self):
        """
        Logout from Switch
        :return:
        """
        self.in_channel('logout')
        count = 0
        while count < 90:
            time.sleep(0.6)
            curr_text = self.out_channel()
            if 'want to log out' in curr_text:
                self.in_channel("y")
            elif 'save the current' in curr_text:
                self.in_channel("n")
            try:
                self.in_channel("")
            except socket.error:
                break
            count += 1
        self.shell_chanel.close()
        self.ssh_client.close()


def get_ssh_config(**args):
    config = None
    config_path = args.get("configfile", "aruba_switches.yml")
    with open(config_path, 'r') as stream:
        try:
            config = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            logging.error("failed to load config")
            logging.error(exc)
            return None,None
    if config is None:
        logging.error("failed to load config")
        return None,None
    instance = args.get("instance")
    if instance is None:
        logging.error("No instance param. found")
        return None,None

    ssh_config = None
    if args["instance"] in config["hosts"]:
        ssh_config = config[args["instance"]]
    else:
        ssh_config = config["hosts"]["default"]

    hostname = ""
    if "instance" in ssh_config:
        hostname = ssh_config.get("instance")
    else:
        hostname = args["instance"]
    full_ssh_config = {"hostname": hostname, "username": ssh_config.get("username"),
                       "password": ssh_config.get("password"), "port": ssh_config.get("port", 22),
                       "look_for_keys": ssh_config.get("look_for_keys", False),
                       'allow_agent': ssh_config.get("allow_agent", False),
                       "key_filename": ssh_config.get("key_filename", None), "timeout": ssh_config.get("timeout", 60)}
    return full_ssh_config,config

def get_commands(config,**args):
    commands = []
    if args.get("function") is None:
        return  commands
    if args.get("function") == "clear-specific-intrusion-flags" and not args.get("ifDescr") is None:
        commands.append("configure t")
        clear_int_flag = "port-security " + args.get("ifDescr") + " clear-intrusion-flag"
        commands.append(clear_int_flag)
    elif args.get("function") == "clear-all-intrusion-flags":
        commands.append("clear intrusion-flags")

    return commands


def execute(**args):

    ssh_config,config = get_ssh_config(**args)
    commands = get_commands(config,**args)

    if len(commands) == 0:
        return -1
    try:
        class_init = SwitchSSHCLI(**ssh_config)
        class_init.execute_cli_command(commands)
        class_init.logout()
    except Exception as e:
        logging.error("failed to load config")
        logging.error(e)
        return -1
    return 0