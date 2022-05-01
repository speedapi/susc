from io import TextIOWrapper
from shutil import rmtree
from colorama.ansi import Fore
import lark
from lark.exceptions import UnexpectedInput
from os import path, makedirs
from importlib import import_module
from math import ceil

from .things import *
from . import log
from . import linker
from .exceptions import DiagLevel, Diagnostic, OutputError, SearchError, SourceError

KNOWN_SETTINGS = ["output", "html_topbar_logo", "html_topbar_title"]

# read the description file
with open(path.join(path.dirname(__file__), "sus.lark")) as f:
    lark_parser = lark.Lark(f.read(), parser="lalr")

def token_to_str(token: str):
    return {
        "LPAR": "'('", "RPAR": "')'",
        "LBRACE": "'{'", "RBRACE": "'}'",
        "LSQB": "'['", "RSQB": "']'",
        "DOCSTRING": "'@>'",
        "COLON": "':'",
        "SEMICOLON": "';'",
        "COMMA": "','",
        "PLUS": "'+'",

        "TYPE_IDENTIFIER": "name",
        "ROOT_IDENTIFIER": "name",
        "METHOD_IDENTIFIER": "name",
        "FIELD_IDENTIFIER": "field",
        "VALIDATOR_IDENTIFIER": "validator",
        "NUMBER": "number",
        "SIGNED_NUMBER": "signed_number",
        "REGEX": "regex",
        "RANGE": "range",
        "PARAMETER": "parameter",
        "VALUE": "value",
    # if none matched, turn TOKEN into 'token'
    }.get(token, "'" + token.lower() + "'")

class File():
    def __init__(self, parent=None):
        self.parent = parent
        self.settings = {}
        self.dependencies = []
        self.things = []

    def load_from_text(self, source):
        self.source = source
        self.path = "<from source>"

    def load_from_file(self, source: str|TextIOWrapper):
        # read the file
        if isinstance(source, str):
            self.path = source
            source = open(source, "r")
        else:
            self.path = source.name
        self.source = source.read()
        source.close()

        log.verbose(f"Loaded file: {Fore.WHITE}{self.path}{Fore.LIGHTBLACK_EX} {'(root)' if not self.parent else ''}")

    def resolve_source(self, p):
        targets = [
            p,
            path.join(path.dirname(self.path), p), # next to the current file
            path.join(path.dirname(__file__), "stdlib", p) # in the standard library
        ]
        targets += [t + ".sus" for t in targets if not t.endswith(".sus")] # try with .sus extension
        targets = [path.abspath(t) for t in targets]
        targets = sorted(set(targets), key=lambda x: targets.index(x)) # remove duplicates keeping the order
        # try each one
        for target in targets:
            try:
                return open(target, "r")
            except FileNotFoundError: pass

        locations = '\n'.join(targets)
        raise SearchError(f"Couldn't find or open '{p}' in any of the following locations:\n{locations}")

    def parse(self) -> Tuple[list[SusThing], list[Diagnostic]]:
        log.verbose(f"Parsing {Fore.WHITE}{self.path}")
        diag = []

        try:
            self.tree = lark_parser.parse(self.source)
            log.verbose(f"AST constructed")
        except UnexpectedInput as e:
            token = e.token.value.split(' ')[0]
            expected = ', '.join(token_to_str(t) for t in e.expected)
            error_text = f"Unexpected input. Expected{' one of:' if len(e.expected) > 1 else ''} {expected}"
            dur = len(token)

            if token == "":
                # empty token = EOF
                line = self.source.split('\n')[e.line - 1]
                location = Location(self, e.line, len(line) + 1, 0)
            else:
                location = Location(self, e.line, e.column, dur)

            diag = Diagnostic([location], DiagLevel.ERROR, error_text)

            # inform the user about our naming conventions :)
            if len(e.expected.intersection({"TYPE_IDENTIFIER", "ROOT_IDENTIFIER"})):
                diag.message += "\nHint: identifiers for things except methods, fields and members use PascalCase"
            if len(e.expected.intersection({"FIELD_IDENTIFIER", "METHOD_IDENTIFIER", "VALIDATOR_IDENTIFIER"})):
                diag.message += "\nHint: method, field, member and validator identifiers use snake_case"

            # parsing can't continue any further, just return
            return [], [diag]

        # deconstruct the syntax tree
        for thing in self.tree.children:
            if thing.data == "inclusion":
                name = thing.children[0]
                log.verbose(f"Encountered inclusion:{Fore.LIGHTBLACK_EX} path={Fore.WHITE}{name}")
                # find dependency
                try:
                    source = self.resolve_source(name.value)
                except SearchError as ex:
                    return [], [Diagnostic([Location(self, name.line, name.column, len(name))],
                        DiagLevel.ERROR, ex.msg)]
                # load it
                dependency = File(self)
                dependency.load_from_file(source)
                self.dependencies.append(dependency)

            elif thing.data == "setting":
                name = thing.children[0]
                value = thing.children[1]
                log.verbose(f"Encountered setting:{Fore.LIGHTBLACK_EX} name={Fore.WHITE}{name}{Fore.LIGHTBLACK_EX} value={Fore.WHITE}{value}")
                if name.value not in KNOWN_SETTINGS:
                    diag.append(Diagnostic([Location(self, name.line, name.column, len(name))], DiagLevel.WARN, "Unknown setting"))
                self.settings[name.value] = value.value

            else:
                if thing.data == "definition":
                    thing = thing.children[0]
                log.verbose(f"AST subtree: {log.highlight_ast(thing)}")
                thing = convert_ast(thing, self)
                log.verbose(f"Converted AST subtree: {Fore.WHITE}{log.highlight_thing(thing)}")
                self.things.append(thing)
                # generate standard methods for entities
                if isinstance(thing, SusEntity):
                    thing.methods.append(SusMethod(
                        thing.location,
                        f"Gets {thing.name} by ID",
                        True,
                        "get",
                        127,
                        [SusField(thing.location, "ID of the entity to get", "id", SusType(thing.location, None, "Int", [8], []), None)],
                        [SusField(thing.location, "Entity with that ID", "entity", SusType(thing.location, None, thing.name, [], []), None)],
                        ["invalid_id"],
                        [],
                        None
                    ))
                    thing.methods.append(SusMethod(
                        thing.location,
                        f"Updates {thing.name}",
                        False,
                        "update",
                        127,
                        [SusField(thing.location, "The values to update", "entity", SusType(thing.location, None, thing.name, [], []), None)],
                        [],
                        ["invalid_entity"],
                        [],
                        None
                    ))

        # parse dependencies
        things = self.things
        for dep in self.dependencies:
            things += dep.parse()[0]

        # run linker
        diag = []
        if self.parent == None:
            things, diag = linker.run(things)

        self.things = things
        return things, diag

    def write_output(self, lang, target_dir):
        if not self.things:
            raise OutputError("No data to write. Call parse() first")

        try:
            module = import_module(".output." + lang, package=__package__)
            target_dir = path.abspath(target_dir)

            # clean output dir
            try: rmtree(target_dir)
            except FileNotFoundError: pass
            try: makedirs(target_dir)
            except FileExistsError: pass

            # call the module
            module.write_output(self, target_dir)
        except ImportError as ex:
            log.verbose(ex)
            raise OutputError(f"No output package for language '{lang}' or it is broken")
