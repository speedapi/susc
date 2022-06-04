from susc import File, log
from susc.things import *
from colorama import Fore
from lark import Tree, Token

def print_subtree(tree: Tree|Token, level: int = 0):
    line = Fore.LIGHTBLACK_EX + ("| " * level) + Fore.RESET

    if isinstance(tree, Tree):
        line += f"{Fore.YELLOW}{tree.data}"
        log.info(line)
        for child in tree.children:
            print_subtree(child, level + 1)

    elif not tree:
        line += f"{Fore.WHITE}None"
        log.info(line)

    else:
        value = tree.value.replace("\n", "\\n")
        if len(value) > 80:
            value = value[:77] + "..."
        line += f"{Fore.CYAN}{tree.type} {Fore.GREEN}'{value}'"
        log.info(line)

def write_output(root_file: File, _target_dir: str) -> None:
    # pretty-print "Pretty print"
    log.info("Abstract syntax tree " +\
             f"{Fore.CYAN}p{Fore.GREEN}r{Fore.MAGENTA}e{Fore.RED}t{Fore.YELLOW}t{Fore.BLUE}y " +\
             f"{Fore.MAGENTA}p{Fore.GREEN}r{Fore.CYAN}i{Fore.RED}n{Fore.YELLOW}t{Fore.RESET}")

    print_subtree(root_file.tree)
