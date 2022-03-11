from colorama import Fore
from textwrap import dedent
from dataclasses import dataclass
from os.path import basename
from typing import *
from . import log

@dataclass
class SusLocation():
    file: Any
    line: int
    col: int
    dur: int
    def __repr__(self):
        return f"{basename(self.file.path)}:{self.line}:{self.col}({self.dur})"

class SusError(Exception):
    pass

SINGLE_LINE_ERRORS = False
class SusSourceError(SusError):
    def __init__(self, locations, text):
        self.locations = locations
        self.text = text
        self.accent = Fore.RED

    def print_err(self):
        self.accent = Fore.RED
        log.error(str(self))
    def print_warn(self):
        self.accent = Fore.YELLOW
        log.warn(str(self))
    def print_info(self):
        self.accent = Fore.BLUE
        log.info(str(self))

    def __str__(self):
        if SINGLE_LINE_ERRORS:
            location = self.locations[0]
            location = f"{location.file.path}:{location.line}:{location.col}"
            return f"{location}: {self.text}"

        error = Fore.WHITE + ("" if len(self.locations) in [0, 1] else "multiple locations: ")

        for loc in self.locations:
            padding = " " * (len(str(loc.line)) + 4 + loc.col - 1)
            squiggly = "~" * loc.dur if loc.dur > 0 else "^"
            src_line = loc.file.source.split('\n')[loc.line - 1]

            # get the inclusion path
            inclusion = Fore.LIGHTBLACK_EX
            cur = loc.file
            while cur.parent != None:
                cur = cur.parent
                inclusion += f" included from {cur.path}"

            error += dedent(f"""\
            {Fore.LIGHTBLACK_EX}in {Fore.WHITE}{loc.file.path}:{loc.line}:{loc.col}{inclusion}:
            {Fore.LIGHTBLACK_EX}{loc.line}  |{Fore.WHITE} {log.highlight_syntax(src_line)}
            {padding}{self.accent}{squiggly}
            """)

        error += f"{self.accent}{self.text}{Fore.RESET}\n"
        return error.strip("\n")

class SusOutputError(SusError):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg