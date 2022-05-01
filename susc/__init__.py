from io import TextIOWrapper
from shutil import rmtree
from colorama.ansi import Fore
import lark
from lark.exceptions import UnexpectedInput
from os import path, makedirs
from .exceptions import SusOutputError, SusSourceError
from importlib import import_module
from math import ceil

from .things import *
from . import log
from . import linker

KNOWN_SETTINGS = ["output", "html_topbar_logo", "html_topbar_title"]

# read the description file
with open(path.join(path.dirname(__file__), "sus.lark")) as f:
    lark_parser = lark.Lark(f.read(), parser="lalr")

class SusFile():
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


    def resolve_source(self, p, line, col):
        targets = [
            p,
            path.join(path.dirname(self.path), p), # next to the current file
            path.join(path.dirname(__file__), "stdlib", p) # in the standard library
        ]
        targets = [path.abspath(t) for t in targets]
        targets = sorted(set(targets), key=lambda x: targets.index(x)) # remove duplicates keeping the order
        # try each one
        for target in targets:
            try:
                return open(target, "r")
            except FileNotFoundError: pass

        locations = '\n'.join(targets)
        raise SusSourceError([SusLocation(self, line, col, len(p))],
            f"Couldn't find '{p}' in any of the following locations:\n{locations}")

    def parse(self):
        log.verbose(f"Parsing {Fore.WHITE}{self.path}")

        try:
            self.tree = lark_parser.parse(self.source)
            log.verbose(f"AST constructed")
        except UnexpectedInput as e:
            token = e.token.value.split(' ')[0]
            expected = ', '.join(e.expected)
            error_text = f"Unexpected input. Expected one of: {expected}"
            dur = len(token)

            raise SusSourceError([SusLocation(self, e.line, e.column, dur)], error_text)

        # deconstruct the syntax tree
        for thing in self.tree.children:
            if thing.data == "inclusion":
                name = thing.children[0]
                log.verbose(f"Encountered inclusion:{Fore.LIGHTBLACK_EX} path={Fore.WHITE}{name}")
                source = self.resolve_source(name.value, name.line, name.column)
                dependency = SusFile(self)
                dependency.load_from_file(source)
                self.dependencies.append(dependency)

            elif thing.data == "setting":
                name = thing.children[0]
                value = thing.children[1]
                log.verbose(f"Encountered setting:{Fore.LIGHTBLACK_EX} name={Fore.WHITE}{name}{Fore.LIGHTBLACK_EX} value={Fore.WHITE}{value}")
                if name.value not in KNOWN_SETTINGS:
                    SusSourceError([SusLocation(self, name.line, name.column, len(name))], "Unknown setting").print_warn()
                self.settings[name.value] = value.value

            else:
                if thing.data == "definition":
                    thing = thing.children[0]
                log.verbose(f"AST subtree: {log.highlight_ast(thing)}")
                thing = convert_ast(thing, self)
                log.verbose(f"Converted AST subtree: {Fore.WHITE}{log.highlight_thing(thing)}")
                self.things.append(thing)
                # generate optional field select bitfields and methods for entities
                if isinstance(thing, SusEntity):
                    opt_members = [SusEnumMember(f.location, None, f.name, f.optional) for f in thing.fields if f.optional != None]
                    if len(opt_members) != 0:
                        max_value = max([m.value for m in opt_members])
                        bitfield = SusBitfield(thing.location, None, thing.name + "FieldSelect", ceil((max_value + 1) / 8), opt_members)
                        self.things.append(bitfield)
                        log.verbose(f"Generated optional field select bitfield: {Fore.WHITE}{log.highlight_thing(bitfield)}")
                    else:
                        log.verbose("No optional fields, not generating a field select bitfield")
                    # add default methods
                    thing.methods.append(SusMethod(
                        thing.location,
                        f"Gets {thing.name} by ID",
                        True,
                        "get",
                        127,
                        [SusField(thing.location, "ID of the entity to get", "id", SusType(thing.location, None, "Int", [8], []), None, None)],
                        [SusField(thing.location, "Entity with that ID", "entity", SusType(thing.location, None, thing.name, [], []), None, None)],
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
                        [SusField(thing.location, "The values to update", "entity", SusType(thing.location, None, thing.name, [], []), None, None)],
                        [],
                        ["invalid_entity"],
                        [],
                        None
                    ))

        # parse dependencies
        things = self.things
        for dep in self.dependencies:
            things += dep.parse()

        # run linker
        if self.parent == None:
            things = linker.run(things)

        self.things = things
        return things

    def write_output(self, lang, target_dir):
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
            raise SusOutputError(f"No output package for language '{lang}' or it is broken")
