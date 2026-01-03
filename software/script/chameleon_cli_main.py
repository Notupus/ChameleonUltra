#!/usr/bin/env python3
import argparse
import os
import sys
import subprocess
import traceback
import chameleon_com
import colorama
import chameleon_cli_unit
import chameleon_utils
import pathlib
import prompt_toolkit
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory
from chameleon_utils import CR, CG, CY, color_string


def check_privileges():
    """
    Check if running with sufficient privileges for USB device access.
    On Linux, either run as root or check for udev rules.
    """
    if sys.platform != 'linux':
        return True  # Non-Linux platforms handle this differently
    
    # Already running as root
    if os.geteuid() == 0:
        return True
    
    # Check if user is in dialout/plugdev group (common for USB access)
    try:
        import grp
        user_groups = [grp.getgrgid(g).gr_name for g in os.getgroups()]
        if 'dialout' in user_groups or 'plugdev' in user_groups:
            return True
    except Exception:
        pass
    
    # Check if udev rules are installed
    udev_paths = [
        '/etc/udev/rules.d/79-chameleon-usb-device-blacklist-dialout.rules',
        '/usr/lib/udev/rules.d/79-chameleon-usb-device-blacklist-dialout.rules'
    ]
    for path in udev_paths:
        if os.path.exists(path):
            return True
    
    return False


def escalate_privileges():
    """
    Re-run the script with sudo if not already privileged.
    """
    print(color_string((CY, "USB device access requires elevated privileges.")))
    print(color_string((CY, "Attempting to restart with sudo...")))
    print()
    
    try:
        # Re-execute with sudo, preserving the Python interpreter and script
        args = ['sudo', sys.executable] + sys.argv
        os.execvp('sudo', args)
    except Exception as e:
        print(color_string((CR, f"Failed to escalate privileges: {e}")))
        print(color_string((CY, "Try running with: sudo " + ' '.join([sys.executable] + sys.argv))))
        sys.exit(1)

ULTRA = r"""
                                                                ╦ ╦╦ ╔╦╗╦═╗╔═╗
                                                   ███████      ║ ║║  ║ ╠╦╝╠═╣
                                                                ╚═╝╩═╝╩ ╩╚═╩ ╩
"""

LITE = r"""
                                                                ╦  ╦╔╦╗╔═╗
                                                   ███████      ║  ║ ║ ║╣
                                                                ╩═╝╩ ╩ ╚═╝
"""

# create by http://patorjk.com/software/taag/#p=display&f=ANSI%20Shadow&t=Chameleon%20Ultra
BANNER = """
 ██████╗██╗  ██╗ █████╗ ██╗   ██╗███████╗██╗     ███████╗ █████╗ ██╗  ██╗
██╔════╝██║  ██║██╔══██╗███╗ ███║██╔════╝██║     ██╔════╝██╔══██╗███╗ ██║
██║     ███████║███████║████████║█████╗  ██║     █████╗  ██║  ██║████╗██║
██║     ██╔══██║██╔══██║██╔██╔██║██╔══╝  ██║     ██╔══╝  ██║  ██║██╔████║
╚██████╗██║  ██║██║  ██║██║╚═╝██║███████╗███████╗███████╗╚█████╔╝██║╚███║
 ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝   ╚═╝╚══════╝╚══════╝╚══════╝ ╚════╝ ╚═╝ ╚══╝
"""


class ChameleonCLI:
    """
        CLI for chameleon
    """

    def __init__(self):
        # new a device communication instance(only communication)
        self.device_com = chameleon_com.ChameleonCom()

    def get_cmd_node(self, node: chameleon_utils.CLITree,
                     cmdline: list[str]) -> tuple[chameleon_utils.CLITree, list[str]]:
        """
        Recursively traverse the command line tree to get to the matching node

        :return: last matching CLITree node, remaining tokens
        """
        # No more subcommands to parse, return node
        if cmdline == []:
            return node, []

        for child in node.children:
            if cmdline[0] == child.name:
                return self.get_cmd_node(child, cmdline[1:])

        # No matching child node
        return node, cmdline[:]

    def get_prompt(self):
        """
        Retrieve the cli prompt

        :return: current cmd prompt
        """
        if self.device_com.isOpen():
            status = color_string((CG, 'USB'))
        else:
            status = color_string((CR, 'Offline'))

        return ANSI(f"[{status}] chameleon --> ")

    @staticmethod
    def print_banner():
        """
            print chameleon ascii banner.

        :return:
        """
        print(color_string((CY, BANNER)))

    def exec_cmd(self, cmd_str):
        if cmd_str == '':
            return

        # look for alternate exit
        if cmd_str in ["quit", "q", "e"]:
            cmd_str = 'exit'

        # look for alternate comments
        if cmd_str[0] in ";#%":
            cmd_str = 'rem ' + cmd_str[1:].lstrip()

        # parse cmd
        argv = cmd_str.split()

        tree_node, arg_list = self.get_cmd_node(chameleon_cli_unit.root, argv)
        if not tree_node.cls:
            # Found tree node is a group without an implementation, print children
            print("".ljust(18, "-") + "".ljust(10) + "".ljust(30, "-"))
            for child in tree_node.children:
                cmd_title = color_string((CG, child.name))
                if not child.cls:
                    help_line = (f" - {cmd_title}".ljust(37)) + f"{{ {child.help_text}... }}"
                else:
                    help_line = (f" - {cmd_title}".ljust(37)) + f"{child.help_text}"
                print(help_line)
            return

        unit: chameleon_cli_unit.BaseCLIUnit = tree_node.cls()
        unit.device_com = self.device_com
        args_parse_result = unit.args_parser()

        assert args_parse_result is not None
        args: argparse.ArgumentParser = args_parse_result
        args.prog = tree_node.fullname
        try:
            args_parse_result = args.parse_args(arg_list)
            if args.help_requested:
                return
        except chameleon_utils.ArgsParserError as e:
            args.print_help()
            print(color_string((CY, str(e).strip())))
            return
        except chameleon_utils.ParserExitIntercept:
            # don't exit process.
            return
        try:
            # before process cmd, we need to do something...
            if not unit.before_exec(args_parse_result):
                return

            # start process cmd, delay error to call after_exec firstly
            error = None
            try:
                unit.on_exec(args_parse_result)
            except Exception as e:
                error = e
            unit.after_exec(args_parse_result)
            if error is not None:
                raise error

        except (chameleon_utils.UnexpectedResponseError, chameleon_utils.ArgsParserError) as e:
            print(color_string((CR, str(e))))
        except Exception:
            print(f"CLI exception: {color_string((CR, traceback.format_exc()))}")

    def startCLI(self):
        """
            start listen input.

        :return:
        """
        self.completer = chameleon_utils.CustomNestedCompleter.from_clitree(chameleon_cli_unit.root)
        self.session = prompt_toolkit.PromptSession(completer=self.completer,
                                                    history=FileHistory(str(pathlib.Path.home() /
                                                                            ".chameleon_history")))

        self.print_banner()
        cmd_strs = []
        while True:
            if cmd_strs:
                cmd_str = cmd_strs.pop(0)
            else:
                # wait user input
                try:
                    cmd_str = self.session.prompt(
                        self.get_prompt()).strip()
                    cmd_strs = cmd_str.replace(
                        "\r\n", "\n").replace("\r", "\n").split("\n")
                    cmd_str = cmd_strs.pop(0)
                except EOFError:
                    cmd_str = 'exit'
                except KeyboardInterrupt:
                    cmd_str = 'exit'
            self.exec_cmd(cmd_str)


if __name__ == '__main__':
    if sys.version_info < (3, 9):
        raise Exception("This script requires at least Python 3.9")
    colorama.init(autoreset=True)
    
    # Check for sufficient privileges on Linux
    if sys.platform == 'linux' and not check_privileges():
        escalate_privileges()
    
    chameleon_cli_unit.check_tools()
    ChameleonCLI().startCLI()
