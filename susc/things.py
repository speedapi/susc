from abc import ABC
from dataclasses import dataclass
from os import times
from typing import *
from enum import Enum
from lark.lexer import Token
from lark.tree import Tree
import re
from .exceptions import SourceError, Location
from .log import verbose
from textwrap import dedent

@dataclass
class SusThing(ABC):
    location: Location
    docstring: str

@dataclass
class SusValidator(SusThing):
    param: str
    restriction: Any

class SusTypeBase(SusThing):
    @overload
    def find_errors(self, identifiers):
        raise NotImplemented()

@dataclass
class SusType(SusTypeBase):
    name: str
    args: List[Any]
    validators: List[SusValidator]
    def find_errors(self, identifiers):
        if self.name == "Int":
            if len(self.args) != 1:
                return "Int requires one argument"
            if not isinstance(self.args[0], int) or self.args[0] <= 0:
                return "Argument to Int should be a positive integer"
            for v in self.validators:
                if v.param != "val":
                    return "The following validators are valid for Int: 'val'"
                if not isinstance(v.restriction, range):
                    return "Int[val] must be a range"
        elif self.name == "Str":
            if len(self.args) != 0:
                return "Str takes no arguments"
            for v in self.validators:
                if v.param not in ["len", "match"]:
                    return "The following validators are valid for Str: 'len', 'match'"
                if v.param == "len" and not isinstance(v.restriction, range):
                    return "Str[len] must be a range"
                if v.param == "match" and not isinstance(v.restriction, re.Pattern):
                    return "Str[match] must be a regular expression"
        elif self.name == "List":
            if len(self.args) != 2:
                return "List takes two arguments"
            if not isinstance(self.args[0], SusTypeBase):
                return "First argument to List should be a type"
            err = self.args[0].find_errors(identifiers)
            if err is not None: return err
            if not isinstance(self.args[1], int) or self.args[1] <= 0:
                return "Second argument to List should be a positive integer"
            for v in self.validators:
                if v.param != "cnt":
                    return "The following validators are valid for List: 'cnt'"
                if not isinstance(v.restriction, range):
                    return "List[cnt] must be a range"
        elif self.name == "Bool":
            if len(self.args) != 0:
                return "Bool takes no arguments"
            if len(self.validators) != 0:
                return "Bool can't be validated"
        elif self.name == "Bin":
            if len(self.args) != 0:
                return "Bin takes no arguments"
            for v in self.validators:
                if v.param != "len":
                    return "The following validators are valid for Bin: 'len'"
                if not isinstance(v.restriction, range):
                    return "Bin[len] must be a range"
        elif self.name not in identifiers:
            return "Unknown type"
        else:
            if len(self.args):
                return f"{self.name} takes no arguments"
            if len(self.validators):
                return f"{self.name} can't be validated"

@dataclass
class SusCompoundMember(SusThing):
    name: str
    type_: SusTypeBase

@dataclass
class SusCompound(SusTypeBase):
    members: List[SusCompoundMember]
    def find_errors(self, identifiers):
        for m in self.members:
            err = m.type_.find_errors(identifiers)
            if err != None:
                return err

@dataclass
class SusEnumMember(SusThing):
    name: str
    value: int

@dataclass
class SusEnum(SusThing):
    name: str
    size: int
    members: List[SusEnumMember]

@dataclass
class SusBitfield(SusThing):
    name: str
    size: int
    members: List[SusEnumMember]

@dataclass
class SusField(SusThing):
    name: str
    type_: SusType
    optional: int

@dataclass
class SusMethod(SusThing):
    static: bool
    name: str
    value: int
    parameters: List[SusField]
    returns: List[SusField]
    errors: List[str]
    confirmations: List[str]
    rate_limit: Tuple[int, int]

@dataclass
class SusEntity(SusThing):
    name: str
    value: int
    fields: List[SusField]
    methods: List[SusMethod]

@dataclass
class SusConfirmation(SusThing):
    name: str
    value: int
    req_parameters: List[SusField]
    resp_parameters: List[SusField]

@dataclass
class SusCompound(SusThing):
    name: str
    fields: List[SusField]


def convert_docstring(doc: str) -> str:
    if doc is None:
        return None
    doc = doc.value
    doc = doc.strip(" \r\n")
    doc = doc[2:-2] # remove @> and <@
    doc = doc.strip("\r\n")
    return dedent(doc).strip()

def convert_ebf_members(ast, file): # Enum or Bitfield
    list = []
    for member in ast:
        if not member: continue
        doc = convert_docstring(member.children[0])
        name = member.children[1]
        value = int(member.children[2].value)
        list.append(SusEnumMember(Location(file, name.line, name.column, len(name.value)), doc, name.value, value))
    return list
    
def convert_range(ast, max_val):
    if len(ast.children) == 1:
        return range(int(ast.children[0].value), max_val)
    elif len(ast.children) == 2:
        return range(int(ast.children[0].value), int(ast.children[1].value) + 1) # python ranges exclude the right end

def convert_type(ast, file):
    name = ast.children[0]
    args = []
    validators = []
    for directive in ast.children[1:]:
        if directive is None:
            continue
        elif directive.data == "type_argument":
            arg_val = directive.children[0]
            if isinstance(arg_val, Token) and arg_val.type == "NUMBER":
                args.append(int(arg_val.value))
            elif isinstance(arg_val, Tree) and arg_val.data in ["type", "compound"]:
                args.append(convert_type(arg_val, file))
        elif directive.data == "type_validator":
            val_name = directive.children[0] # validator name
            val_val = directive.children[1].children[0] # validator value
            if isinstance(val_val, Token) and val_val.type == "SIGNED_NUMBER":
                val_val = int(val_val)
            elif isinstance(val_val, Token) and val_val.type == "REGEX":
                regex_tokens = val_val.split('/')
                regex = '/'.join(regex_tokens[1:-1])
                flags = regex_tokens[-1]
                flags_num = 0
                for f in flags:
                    if f == "i": flags_num |= re.I
                    if f == "m": flags_num |= re.M
                    if f == "s": flags_num |= re.S
                try:
                    val_val = re.compile(regex, flags_num)
                except re.error as exc:
                    raise SourceError([Location(file, val_val.line, val_val.column + exc.pos + 1, 0)],
                        f"Invalid regular expression: {exc.msg}")
            elif isinstance(val_val, Tree) and val_val.data == "range":
                max_val = 2 ** 64
                # we can infer the maximum value from the int length
                if name == "Int" and len(args) == 1 and isinstance(args[0], int):
                    max_val = 2 ** (args[0] * 8)
                val_val = convert_range(val_val, max_val)
            validators.append(SusValidator(Location(file, val_name.line, val_name.column, len(val_name.value)), None,
                val_name.value, val_val))

    location = Location(file, name.line, name.column, len(name.value))
    return SusType(location, None, name.value, args, validators)

def convert_opt(ast):
    if ast is None:
        return ast
    return int(ast.value)

def convert_value(ast):
    if isinstance(ast, Tree) and ast.data == "value":
        ast = ast.children[0]
    if isinstance(ast, Token):
        if ast.type == "SIGNED_NUMBER": return int(ast.value)
        if ast.type == "BOOL": return ast.value == "true"
        if ast.type == "STRING": return ast.value[1:-1] # strip quotation marks
    elif isinstance(ast, Tree):
        if ast.data == "list":
            return [convert_value(val) for val in ast.children]

def convert_param(ast, file):
    doc = convert_docstring(ast.children[0])
    name = ast.children[1]
    opt = convert_opt(ast.children[2])
    type_ = convert_type(ast.children[3], file)

    location = Location(file, name.line, name.column, len(name.value))

    return SusField(location, doc, name.value, type_, opt)

def convert_timeout(val):
    num, mul = re.match("(\d+)(\w+)", val).groups()
    num = int(num)
    return num * {
        "ms":                      1,
        "s":                    1000,
        "m":               60 * 1000,
        "h":             3600 * 1000,
        "d":        24 * 3600 * 1000,
        "mo":  30 * 24 * 3600 * 1000,
        "y":  356 * 24 * 3600 * 1000,
    }[mul]

def convert_method(ast, file):
    static = None
    if ast.data == "static_method": static = True
    elif ast.data == "normal_method": static = False

    doc = convert_docstring(ast.children[0])
    name = ast.children[1]
    value = int(ast.children[2].value)

    params, returns, errors, confirmations, states, rate_limit = [], [], [], [], [], None
    for directive in ast.children[3:]:
        if not directive: continue
        if directive.data == "method_param":
            params.append(convert_param(directive, file))
        elif directive.data == "returns":
            for p in directive.children:
                returns.append(convert_param(p, file))
        elif directive.data in ["errors", "confirmations"]:
            lst = {"errors": errors, "confirmations": confirmations}[directive.data]
            for e in directive.children:
                if not e: continue
                if e.value in lst:
                    SourceError([Location(file, e.line, e.column, len(e.value))],
                        f"Duplicate member \"{e.value}\" for this directive").print_warn()
                lst.append(e.value)
        elif directive.data == "rate_limit":
            amount = int(directive.children[0].value)
            window = convert_timeout(directive.children[1].value)
            rate_limit = (amount, window)

    return SusMethod(Location(file, name.line, name.column, len(name.value)), doc, static, name.value,
        value, params, returns, errors, confirmations, rate_limit)

def convert_ast(ast, file):
    if ast.data in ["enum", "bitfield"]:
        constructor = SusEnum if ast.data == "enum" else SusBitfield
        doc = convert_docstring(ast.children[0])
        size = int(ast.children[1].value)
        name = ast.children[2]
        return constructor(Location(file, name.line, name.column, len(name)), doc,
            name.value, size, convert_ebf_members(ast.children[3:], file))

    elif ast.data == "entity":
        doc = convert_docstring(ast.children[0])
        name = ast.children[1]
        value = ast.children[2]

        directives = ast.children[3:]
        fields, methods = [], []
        for directive in directives:
            if directive.data == "entity_field":
                f_doc = convert_docstring(directive.children[0])
                identifier = directive.children[1]
                opt = convert_opt(directive.children[2])
                type_ = convert_type(directive.children[3], file)
                location = Location(file, identifier.line, identifier.column, len(identifier.value))

                fields.append(SusField(location, f_doc, identifier.value, type_, opt))

            if directive.data.endswith("method"):
                methods.append(convert_method(directive, file))

        return SusEntity(Location(file, name.line, name.column, len(name.value)), doc,
            name.value, int(value.value), fields, methods)

    elif ast.data == "global_method":
        return convert_method(ast, file)

    elif ast.data == "confirmation":
        doc = convert_docstring(ast.children[0])
        name = ast.children[1]
        value = int(ast.children[2].value)
        req = ast.children[3]
        resp = ast.children[4]

        req = [convert_param(par, file) for par in req.children if par]
        resp = [convert_param(par, file) for par in resp.children if par]

        return SusConfirmation(Location(file, name.line, name.column, len(name)), doc, name.value, value,
            req, resp)

    elif ast.data == "compound":
        doc = convert_docstring(ast.children[0])
        name = ast.children[1]

        directives = ast.children[2:]
        fields, methods = [], []
        for directive in directives:
            if not directive: continue
            d_doc = convert_docstring(directive.children[0])
            identifier = directive.children[1]
            opt = convert_opt(directive.children[2])
            type_ = convert_type(directive.children[3], file)
            location = Location(file, identifier.line, identifier.column, len(identifier.value))

            fields.append(SusField(location, d_doc, identifier.value, type_, opt))

        return SusCompound(Location(file, name.line, name.column, len(name.value)), doc,
            name.value, fields)
