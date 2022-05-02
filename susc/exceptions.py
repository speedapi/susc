from colorama import Fore
from textwrap import dedent
from dataclasses import dataclass
from os.path import basename
from typing import *
from enum import Enum

from . import log

@dataclass
class Location():
    file: Any
    line: int
    col: int
    dur: int
    def __repr__(self):
        return f"{basename(self.file.path)}:{self.line}:{self.col}({self.dur})"
    def __hash__(self) -> int:
        return hash(self.file.source) + self.line + self.col + self.dur

class DiagLevel(Enum):
    ERROR = 1
    WARN = 2
    INFO = 3

@dataclass
class Diagnostic():
    locations: list[Location]
    level: DiagLevel
    code: int
    message: str

class SusError(Exception):
    pass

SINGLE_LINE_ERRORS = False
RECOMMENDED_EXPLAIN = False
class SourceError(SusError):
    def __init__(self, diag: Diagnostic):
        self.diag = diag
        self.accent = {
            DiagLevel.ERROR: Fore.RED,
            DiagLevel.WARN: Fore.YELLOW,
            DiagLevel.INFO: Fore.BLUE,
        }[diag.level]

    def print(self):
        function = {
            DiagLevel.ERROR: log.error,
            DiagLevel.WARN: log.warn,
            DiagLevel.INFO: log.info,
        }[self.diag.level]
        function(str(self))

    def __str__(self):
        global SINGLE_LINE_ERRORS, RECOMMENDED_EXPLAIN
        if SINGLE_LINE_ERRORS:
            location = self.diag.locations[0]
            location = f"{location.file.path}:{location.line}:{location.col}"
            return f"{location}: {self.text}"

        code = str(self.diag.code).rjust(4, "0")
        error = Fore.LIGHTBLACK_EX + f"(code {Fore.WHITE}{code}{Fore.LIGHTBLACK_EX}) "
        error += Fore.WHITE + ("" if len(self.diag.locations) < 2 else "multiple locations: ")

        for loc in self.diag.locations:
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

        error += f"{self.accent}{self.diag.message}\n"
        if not RECOMMENDED_EXPLAIN:
            error += f"Tip: try 'susc --explain {code}' to see an explanation"
            RECOMMENDED_EXPLAIN = True
        return error.strip("\n") + Fore.RESET

class OutputError(SusError):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg

class SearchError(SusError):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg