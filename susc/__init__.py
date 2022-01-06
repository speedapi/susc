from shutil import rmtree
from colorama.ansi import Fore
import lark
from os import path, makedirs

from lark.exceptions import UnexpectedInput
from .things import *
from .exceptions import SusOutputError, SusSourceError
from importlib import import_module
from math import ceil
from . import log

MAGIC_IDENTIFIERS = ["Entity"]
KNOWN_SETTINGS = ["output", "html_topbar_logo", "html_topbar_title"]

# read the description file
with open(path.join(path.dirname(__file__), "sus.lark")) as f:
    lark_parser = lark.Lark(f.read(), parser="lalr")

class SusFile():
    def __init__(self, source, parent=None):
        self.parent = parent
        self.settings = {}
        self.dependencies = []
        self.things = []

        # read the file
        if isinstance(source, str):
            self.path = source
            source = open(source, "r")
        else:
            self.path = source.name
        self.source = source.read()
        source.close()

        log.verbose(f"Loaded {Fore.WHITE}{self.path}{Fore.LIGHTBLACK_EX} {'(root)' if parent == None else ''}")


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
                self.dependencies.append(SusFile(source, self))

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
                # generate optional field select bitfields for entities
                if isinstance(thing, SusEntity):
                    log.verbose(thing.fields)
                    opt_members = [SusEnumMember(f.location, None, f.name, f.optional) for f in thing.fields if f.optional != None]
                    if len(opt_members) != 0:
                        max_value = max([m.value for m in opt_members])
                        bitfield = SusBitfield(thing.location, None, thing.name + "FieldSelect", ceil((max_value + 1) / 8), opt_members)
                        self.things.append(bitfield)
                        log.verbose(f"Generated optional field select bitfield: {Fore.WHITE}{log.highlight_thing(bitfield)}")
                    else:
                        log.verbose("No optional fields, not generating a field select bitfield")

        # parse dependencies
        all_things = self.things
        for dep in self.dependencies:
            all_things += dep.parse()

        # check field overlap 
        if self.parent == None:
            log.verbose("Validating fields")
            # get all identifiers that can be referenced
            identifiers = [t.name for t in all_things if not isinstance(t, SusMethod)] + MAGIC_IDENTIFIERS
            # get all possible fields: entity fields, method params and method return vals
            entities = [t for t in all_things if isinstance(t, SusEntity)]
            methods = [t for t in all_things if isinstance(t, SusMethod)]
            confirmations = [t for t in all_things if isinstance(t, SusConfirmation)]
            for e in entities: methods += e.methods
            field_sets = [e.fields for e in entities]
            field_sets += [m.parameters for m in methods]
            field_sets += [m.returns for m in methods]
            field_sets += [m.req_parameters for m in confirmations]
            field_sets += [m.resp_parameters for m in confirmations]
            
            for fields in field_sets:
                for f1 in fields:
                    # optional values mod 256
                    if f1.optional != None and f1.optional >= 256:
                        SusSourceError([f1.location], f"Optional value '{f1.optional}' will be taken mod 256 ('{f1.optional % 256}')").print_warn()
                        f1.optional %= 256

                    # the fields within one set shouldn't have matching name or values
                    equal = [f2 for f2 in fields if f2.name == f1.name]
                    if len(equal) > 1:
                        raise SusSourceError([f.location for f in equal], f"Multiple fields with matching names '{f1.name}'")
                    equal = [f2 for f2 in fields if f2.optional == f1.optional and f1.optional != None]
                    if len(equal) > 1:
                        raise SusSourceError([f.location for f in equal], f"Multiple fields with matching optional values '{f1.optional}'")

                    # validate the type
                    type_err = f1.type_.find_errors(identifiers)
                    if type_err != None:
                        raise SusSourceError([f1.type_.location], type_err)

        # combine enums and bitfields
        out_things = []
        if self.parent == None:
            log.verbose(f"Combining {len(all_things)} total definitions")
            ignore = []
            for thing1 in all_things:
                if thing1.name in ignore:
                    continue
                # find things with same name
                with_matching_name = []
                for thing2 in all_things:
                    if thing1.name == thing2.name:
                        with_matching_name.append(thing2)
                if len(with_matching_name) > 1:
                    # throw redefinition errors
                    for thing2 in with_matching_name:
                        if type(thing1) is not type(thing2):
                            raise SusSourceError([t.location for t in with_matching_name],
                                f"Multiple things of different types with matching name '{thing1.name}'")
                        elif not isinstance(thing1, (SusEnum, SusBitfield)):
                            raise SusSourceError([t.location for t in with_matching_name],
                                f"Redefinition of '{thing1.name}' (only enums and bitfields can be combined)")
                    # match sizes
                    if not all([t.size == thing1.size for t in with_matching_name]):
                        raise SusSourceError([t.location for t in with_matching_name],
                            "Can't combine things of different sizes")
                    # record members of enums and mitfields
                    opt_members = []
                    for t in with_matching_name:
                        opt_members += t.members
                    # find clashes
                    for m1 in opt_members:
                        for m2 in opt_members:
                            if m1 is not m2 and m1.name == m2.name:
                                raise SusSourceError([m1.location, m2.location], f"Multiple members with matching names '{m1.name}'")
                            if m1 is not m2 and m1.value == m2.value:
                                raise SusSourceError([m1.location, m2.location], f"Multiple members with matching values '{m1.value}'")
                    # finally, combine all members
                    constructor = SusEnum if isinstance(thing1, SusEnum) else SusBitfield
                    doc = (thing1.docstring or "") + "\n" + (thing2.docstring or "")
                    if doc == "\n": doc = None
                    new_thing = constructor(thing1.location, doc, thing1.name, thing1.size, opt_members)
                    out_things.append(new_thing)
                    log.verbose(f"{Fore.LIGHTBLACK_EX}Combined {constructor.__name__[3:].lower()} {Fore.WHITE}{thing1.name}{Fore.LIGHTBLACK_EX} members across {len(with_matching_name)} definitions: {Fore.WHITE}{new_thing}")
                else:
                    out_things.append(thing1)
                ignore.append(thing1.name)

                # check numeric values
                if isinstance(thing1, (SusEnum, SusBitfield)):
                    maximum = (thing1.size * 8 if isinstance(thing1, SusBitfield) else 256 ** thing1.size) - 1
                    for member in thing1.members:
                        if member.value > maximum:
                            SusSourceError([member.location], f"Member value '{member.value}' overflow (max '{maximum}')").print_warn()
                if isinstance(thing1, (SusEntity, SusMethod)) and thing1.value > 127:
                    SusSourceError([thing1.location], f"Value '{thing1.value}' overflow (max '127')").print_warn()
                if isinstance(thing1, SusConfirmation) and thing1.value > 15:
                    SusSourceError([thing1.location], f"Value '{thing1.value}' overflow (max '15')").print_warn()

            log.verbose(f"Combined {len(all_things)} definitions into {len(out_things)} things")
        else:
            out_things = all_things
        all_things = out_things

        # check "errors" and "states"
        if self.parent == None:
            log.verbose("Validating method error codes and states")

            errors = [t for t in all_things if isinstance(t, SusEnum) and t.name == "ErrorCode"]
            states = [t for t in all_things if isinstance(t, SusEnum) and t.name == "State"]
            confirmations = [t.name for t in all_things if isinstance(t, SusConfirmation)]
            if len(errors) == 0: raise SusSourceError([], "No 'ErrorCode' enum defined. Include 'impostor.sus' or use a custom definition")
            if len(states) == 0: raise SusSourceError([], "No 'State' enum defined. Include 'impostor.sus' or use a custom definition")
            errors, states = errors[0], states[0]
            errors, states = [m.name for m in errors.members], [m.name for m in states.members]

            entities = [t for t in all_things if isinstance(t, SusEntity)]
            method_sets = [e.methods for e in entities] + [[t for t in all_things if isinstance(t, SusMethod)]]
            for m_set in method_sets:
                for method in m_set:
                    for err in method.errors:
                        if err not in errors:
                            raise SusSourceError([method.location], f"Undefined error code '{err}'")
                    for state in method.states:
                        if state not in states:
                            raise SusSourceError([method.location], f"Undefined state '{state}'")
                    for conf in method.confirmations:
                        if conf not in confirmations:
                            raise SusSourceError([method.location], f"Undefined confirmation '{conf}'")

        # check method and entity value overlap
        if self.parent == None:
            log.verbose("Validating entities and methods")

            entities = [t for t in all_things if isinstance(t, SusEntity)]
            for thing in entities:
                matching = [t for t in entities if t.value == thing.value]
                if len(matching) != 1:
                    raise SusSourceError([t.location for t in matching], f"Multiple entities with matching values '{thing.value}'")
                # check ID field
                id_field = [f for f in thing.fields if f.name == "id"]
                if not id_field:
                    SusSourceError([thing.location], f"No 'id' field").print_warn()
                else:
                    id_field = id_field[0]
                    if id_field.type_.name != "Int" or id_field.type_.args[0] != 8:
                        SusSourceError([id_field.location], f"The 'id' field is not an Int(8)").print_warn()

            method_sets = [[t for t in all_things if isinstance(t, SusMethod)]]
            method_sets += [[m for m in e.methods if m.static] for e in entities]
            method_sets += [[m for m in e.methods if not m.static] for e in entities]
            for m_set in method_sets:
                for method in m_set:
                    matching = [t for t in m_set if t.value == method.value]
                    if len(matching) != 1:
                        raise SusSourceError([t.location for t in matching], f"Multiple methods with matching values '{thing.value}'")

        # strip docstrings
        log.verbose("Stripping docstrings")
        for thing in out_things:
            doc = thing.docstring
            thing.docstring = doc.strip() if doc else None

        self.things = out_things
        return out_things


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