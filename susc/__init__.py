from io import TextIOWrapper
from shutil import rmtree
from colorama.ansi import Fore
import lark
from lark.exceptions import UnexpectedInput
from os import path, makedirs
from importlib import import_module
from re import fullmatch

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

        "TYPE_IDENTIFIER": "type",
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
    def __init__(self, parent=None, root=None):
        self.parent = parent
        self.root = root or self
        self.settings = {}
        self.dependencies = []
        self.things = []
        self.diagnostics = []
        if self.parent is None:
            self.all_loaded = set()

    def load_from_text(self, source, file_path=None):
        self.source = source
        self.path = path.abspath(file_path) if file_path else "<from source>"

        if self.parent is None:
            self.all_loaded.add(self.path)

        log.verbose(f"Loaded from source: {self.path} {Fore.LIGHTBLACK_EX}{'(root)' if not self.parent else ''}", "load")

    def load_from_file(self, source: str|TextIOWrapper):
        # read the file
        if isinstance(source, str):
            self.path = source
            source = open(source, "r")
        else:
            self.path = path.abspath(source.name)
        self.source = source.read()
        source.close()

        if self.parent is None:
            self.all_loaded.add(self.path)

        log.verbose(f"Loaded file: {self.path} {Fore.LIGHTBLACK_EX}{'(root)' if not self.parent else ''}", "load")

    def search_paths(self):
        return [
            "",
            ".",
            path.dirname(self.path), # next to this file
            path.join(path.dirname(__file__), "stdlib") # in the standard library
        ]

    def resolve_source(self, p):
        targets = [path.join(d, p) for d in self.search_paths()]
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

    # provides insight into the parser state at that point
    def insight(self, line: int, col: int) -> tuple[set[str], list]:
        # convert line and column numbers to position within the string
        pos = 0
        for _ in range(line):
            pos = self.source.find("\n", pos) + 1
        pos += col

        # get the source up to that point
        source = self.source[:pos]

        # try parsing
        try:
            lark_parser.parse(source, on_error=self.__parsing_error)
        except UnexpectedInput as e:
            return e.expected, e.state.value_stack

        return None, None # no expected tokens here

    # this method tries to deal with parsing errors
    # it's a complete mess since it's really hard to guess what the user
    # really meant when parsing fails
    def __parsing_error(self, e: lark.UnexpectedToken):
        log.verbose(f"Parsing error: {e}", "corrector")

        # for insight()
        if e.token.type == "$END":
            return False

        parser = e.interactive_parser
        tok: Token = e.token
        token = tok.value.split(' ')[0]
        expected = ', '.join(token_to_str(t) for t in e.expected)
        error_text = f"Expected{' one of:' if len(e.expected) > 1 else ''} {expected}"
        dur = len(token)

        # prints and then feeds
        def feed(t: Token):
            log.verbose(f"Feeding {log.highlight_ast(t)}", "corrector")
            parser.feed_token(t)

        if token == "":
            # empty token = EOF
            line = self.source.split('\n')[e.line - 1]
            location = Location(self, e.line, len(line) + 1, 0)
        else:
            location = Location(self, e.line, e.column, dur)

        diag = Diagnostic([location], DiagLevel.ERROR, 1, error_text)
        self.diagnostics += [diag]

        # inform the user about our naming conventions :)
        # while trying to rename
        if "TYPE_IDENTIFIER" in e.expected and fullmatch(r"[a-zA-Z_]+", token):
            diag.message = "This identifier should use PascalCase"
            diag.code = 2
            tok.type = "TYPE_IDENTIFIER"
            tok.value = tok.value[0].upper() + tok.value[1:]
            log.verbose(f"Renamed '{token}' to '{tok.value}'", "corrector")
            feed(tok)
            return True

        inter = e.expected.intersection({"FIELD_IDENTIFIER", "METHOD_IDENTIFIER", "VALIDATOR_IDENTIFIER"})
        if len(inter) and fullmatch(r"[a-zA-Z_]+", token):
            diag.message = "This identifier should use snake_case"
            diag.code = 2
            tok.type = inter.pop()
            tok.value = tok.value.lower()
            log.verbose(f"Renamed '{token}' to '{tok.value}'", "corrector")
            feed(tok)
            return True

        # fill in missing semicolons and things
        fill_in = {
            "SEMICOLON": ";", "COLON": ":",
            "RPAR": ")", "RBRACE": "}", "RSQB": "]",
            "COMMA": ",",
        }
        for k, v in fill_in.items():
            if k in e.expected:
                if k == "COLON" and tok.type in {"RBRACE"}:
                    continue

                feed(Token(k, v))
                # insert an additional semicolon if the next token is not it
                if k in {"RPAR", "RSQB"} and tok.type != "SEMICOLON":
                    feed(Token("SEMICOLON", ";"))
                feed(tok)

                return True

        # fill in missing numeric values
        stack = [None, None] + parser.parser_state.value_stack
        structure = stack[-2]
        structures = {"ENTITY", "GLOBALMETHOD", "METHOD", "STATICMETHOD", "CONFIRMATION"}
        is_enum = isinstance(stack[-1], Token) and stack[-1].type in {"ENUM", "BITFIELD"}
        if e.expected == {"LPAR"} and (is_enum or (isinstance(structure, Token) and structure.type in structures)):
            diag.message = "Missing numeric value"
            diag.code = 3
            feed(Token("LPAR", "("))
            feed(Token("NUMBER", "0"))
            feed(Token("RPAR", ")"))
            feed(tok)
            return True

        # fill in a name
        if e.expected == {"TYPE_IDENTIFIER"} and tok.type == "LBRACE":
            diag.message = "Missing name"
            diag.code = 4
            feed(Token("TYPE_IDENTIFIER", "__unnamed__", 0, 0, 0, 0, 0, 0))
            feed(tok)
            return True

        # unwind last tokens if met a } or a ;
        if tok.type in {"RBRACE", "SEMICOLON"}:
            log.verbose("Unwinding tokens", "corrector")
            stack = parser.parser_state.value_stack
            # unwind until we meet a tree or a {
            while isinstance(stack[-1], Token) and stack[-1].type != "LBRACE":
                unwound = stack[-1]
                log.verbose(f"Unwinding {log.highlight_ast(unwound)}", "corrector")
                parser.parser_state.value_stack.pop()
                parser.parser_state.state_stack.pop()

            # insert }
            feed(Token("RBRACE", "}"))
            return True

        return False

    def parse(self) -> Tuple[list[SusThing], list[Diagnostic]]:
        log.verbose(f"Parsing {Fore.WHITE}{self.path}", "parser")
        self.things = []
        self.dependencies = []
        self.diagnostics = []

        try:
            self.tree = lark_parser.parse(self.source, on_error=self.__parsing_error)
            log.verbose(f"AST constructed", "parser")
        except UnexpectedInput as e:
            log.verbose("LALR is not happy!", "corr_fail")
            stack = "\n".join(f"{i}: {log.highlight_ast(a)}" for i, a in enumerate(e.state.value_stack))
            log.verbose(f"Parser stack:\n{stack}", "corr_fail")
            log.verbose(f"Incoming token: {log.highlight_ast(e.token)}", "corr_fail")
            log.verbose(f"Expected: {', '.join(e.expected)}", "corr_fail")
            # parsing can't continue any further, just return
            return [], self.diagnostics

        # deconstruct the syntax tree
        for thing in self.tree.children:
            if thing.data == "inclusion":
                name = thing.children[0]
                log.verbose(f"Encountered inclusion:{Fore.LIGHTBLACK_EX} path={Fore.WHITE}{name}", "parser")
                # find dependency
                try:
                    source = self.resolve_source(name.value)
                except SearchError as ex:
                    return [], [Diagnostic([Location(self, name.line, name.column, len(name))],
                        DiagLevel.ERROR, 5, ex.msg)]

                # load it
                if source.name not in self.root.all_loaded:
                    dependency = File(self, self.root)
                    dependency.load_from_file(source)
                    self.dependencies.append(dependency)
                    self.root.all_loaded.add(source.name)
                else:
                    self.diagnostics.append(Diagnostic([Location(self, name.line, name.column, len(name))],
                        DiagLevel.WARN, 6, "This file has already been included directly or by a dependency within this project\n" +\
                        f"Note: inclusion resolved to '{source.name}'"))

            elif thing.data == "setting":
                name = thing.children[0]
                value = thing.children[1]
                log.verbose(f"Encountered setting:{Fore.LIGHTBLACK_EX} name={Fore.WHITE}{name}{Fore.LIGHTBLACK_EX} value={Fore.WHITE}{value}", "parser")
                if name.value not in KNOWN_SETTINGS:
                    self.diagnostics.append(Diagnostic([Location(self, name.line, name.column, len(name))],
                        DiagLevel.WARN, 7, "Unknown setting"))
                self.settings[name.value] = value.value

            else:
                if thing.data == "definition":
                    thing = thing.children[0]
                log.verbose(f"AST subtree: {log.highlight_ast(thing)}", "parser")
                thing = convert_ast(thing, self)
                log.verbose(f"Converted AST subtree: {Fore.WHITE}{log.highlight_thing(thing)}", "parser")
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

        log.verbose(f"Parsing dependencies for {Fore.WHITE}{self.path}", "deps")
        # parse dependencies
        things = self.things
        for dep in self.dependencies:
            things += dep.parse()[0]
        log.verbose(f"Parsing dependencies done for {Fore.WHITE}{self.path}", "deps")

        # run linker
        if not self.parent:
            things, diag = linker.run(things)
            self.diagnostics += diag

        self.things = things
        return things, self.diagnostics

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
