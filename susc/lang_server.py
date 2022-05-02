from glob import iglob
from os import path
from lark import Tree, Token
from pygls.server import LanguageServer
from pygls.lsp.methods import (COMPLETION, TEXT_DOCUMENT_DID_CHANGE, TEXT_DOCUMENT_DID_OPEN,
                               TEXT_DOCUMENT_DID_CLOSE, HOVER, DEFINITION)
from pygls.lsp.types import (DidChangeTextDocumentParams, Diagnostic, Range,
                             Position, DiagnosticSeverity, CompletionOptions, CompletionParams,
                             CompletionList, CompletionItem, CompletionItemKind, HoverParams,
                             Hover, MarkedString, VersionedTextDocumentIdentifier,
                             DidOpenTextDocumentParams, DidCloseTextDocumentParams, DefinitionParams,
                             TextDocumentPositionParams, Location)

from .things import (SusBitfield, SusCompound, SusConfirmation, SusEntity, SusEnum, SusThing, SusField, SusType,
                    SusValidator, SusMethod)
from . import log
from . import File, KNOWN_SETTINGS

server = LanguageServer()
files: dict[str, File] = {}

def recompile_file(ls: LanguageServer, doc: VersionedTextDocumentIdentifier):
    path = doc.uri[len("file://"):]

    global files
    source = ls.workspace.get_document(doc.uri).source

    file = File()
    files[doc.uri] = file

    file.load_from_text(source, path)
    _, diagnostics = file.parse()
    diag_list = []

    for diag in diagnostics:
        for location in diag.locations:
            # ignore locations that are not in the current file
            if location.file.path != path:
                continue

            diag_list.append(Diagnostic(
                range=Range(
                    start=Position(line=location.line - 1, character=location.col - 1),
                    end=Position(line=location.line - 1, character=location.col - 1 + location.dur)
                ),
                message=diag.message,
                source=f"susc({str(diag.code).rjust(4, '0')})",
                severity=DiagnosticSeverity(diag.level.value)
            ))
        
    log.verbose("Pushing diagnostics", "ls")
    ls.publish_diagnostics(doc.uri, diag_list)

@server.feature(TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: DidChangeTextDocumentParams):
    log.verbose("File did change", "ls")
    recompile_file(ls, params.text_document)

@server.feature(TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: LanguageServer, params: DidOpenTextDocumentParams):
    log.verbose("File did open", "ls")
    recompile_file(ls, params.text_document)

@server.feature(TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: LanguageServer, params: DidCloseTextDocumentParams):
    global files
    log.verbose("File did close", "ls")
    files.pop(params.text_document.uri)

# searches for `token` in `state` from right to left, stopping if one of `stop` gets hit
def unwind_state(state: list[Tree|Token], token: str, stop: list[str]=[]) -> bool:
    if not len(state): return False
    tok = len(state) - 1
    while tok:
        t = state[tok]
        if isinstance(t, Token) and t.type not in stop and t.type == token:
            return True
        tok -= 1
    return False

@server.feature(COMPLETION, CompletionOptions(trigger_characters=[":", "(", "[", ",", " ", "{"]))
def completions(params: CompletionParams):
    global files
    file = files[params.text_document.uri]

    # go to the first alpha char to the right
    line = file.source.split("\n")[params.position.line]
    cutoff = params.position.character - 1
    while cutoff > 0 and line[cutoff].isalpha():
        cutoff -= 1

    # get parser state
    expected, stack = file.insight(params.position.line, cutoff + 1)
    if not expected or not stack:
        return None

    log.verbose(f"Parser expected: {', '.join(expected)}", "ls")
    pretty_stack = "\n".join(f"{i}: {log.highlight_ast(s)}" for i, s in enumerate(stack))
    log.verbose(f"Parser stack:\n{pretty_stack}", "ls")

    # find the first token in the chain
    first_token = 0
    while isinstance(stack[first_token], Tree):
        first_token += 1
    first_token = stack[first_token]

    if "TYPE_IDENTIFIER" in expected:
        finding = "types"
    elif "VALIDATOR_IDENTIFIER" in expected:
        finding = "validators"
    elif "PATH" in expected:
        finding = "paths"
    elif "PARAMETER" in expected:
        finding = "parameters"
    elif "FIELD_IDENTIFIER" in expected and unwind_state(stack, "ERRORS", ["CONFIRMATIONS"]):
        finding = "errors"
    elif "TYPE_IDENTIFIER" in expected and unwind_state(stack, "CONFIRMATIONS", ["ERRORS"]):
        finding = "confirmations"
    else:
        log.verbose("I don't know what to find :(", "ls")
        return None

    # find precisely that
    log.verbose(f"Finding {finding}", "ls")
    items = []

    # types: built-ins, entities, compounds, enums, bitfields
    if finding == "types":
        for thing in file.things:
            kind = {
                SusEntity: CompletionItemKind.Class,
                SusCompound: CompletionItemKind.Struct,
                SusEnum: CompletionItemKind.Enum,
                SusBitfield: CompletionItemKind.Enum
            }.get(type(thing), None)
            if kind:
                items.append(CompletionItem(label=thing.name, kind=kind))
        # built-in types
        items += [
            CompletionItem(label=n, kind=CompletionItemKind.TypeParameter)
            for n in ("Str", "Int", "List", "Bool")
        ]

    # validators: all validators for all types
    if finding == "validators":
        items += [
            CompletionItem(label=n, kind=CompletionItemKind.Property)
            for n in ("val", "len", "match", "cnt")
        ]

    # parameters: setting titles
    if finding == "parameters":
        items += [
            CompletionItem(label=n, kind=CompletionItemKind.Property)
            for n in KNOWN_SETTINGS
        ]

    # paths: files that can be included
    if finding == "paths":
        # find .sus files near this one
        basenames = set()
        for directory in file.search_paths():
            basenames.update(path.basename(n) for n in iglob(path.join(directory, "*.sus")))
        items += [
            CompletionItem(label=path.basename(n), kind=CompletionItemKind.File)
            for n in basenames
        ]

    # errors: members of ErrorCode if it's defined
    error_enums = [t for t in file.things if isinstance(t, SusEnum) and t.name == "ErrorCode"]
    if finding == "errors" and len(error_enums):
        enum = error_enums[0]
        items += [
            CompletionItem(label=path.basename(m.name), kind=CompletionItemKind.EnumMember)
            for m in enum.members
        ]

    # confirmations: all confirmations
    if finding == "confirmations":
        items += [
            CompletionItem(label=path.basename(c.name), kind=CompletionItemKind.Constructor)
            for c in file.things if isinstance(c, SusConfirmation)
        ]

    log.verbose("Sending completions", "ls")
    return CompletionList(
        is_incomplete=False,
        items=items
    )

def display_t_arg(a):
    if isinstance(a, SusType):
        return display_type(a)
    return str(a)

def display_t_val(v: SusValidator):
    return f"{v.param}: {v.restriction}"

def display_type(t: SusType):
    return f"{t.name}" +\
        (("(" + ', '.join(display_t_arg(a) for a in t.args) + ")") if len(t.args) else "") +\
        (("[" + ', '.join(display_t_val(v) for v in t.validators) + "]") if len(t.validators) else "")

def display_field(field: SusField):
    opt = f"opt({field.optional}) " if field.optional != None else ""
    return f"{field.name}: {opt}{display_type(field.type_)}"

def display_method(method: SusMethod):
    kw = "staticmethod" if method.static else "method"
    return f"\t{kw} {method.name}({method.value})" + " {\n" +\
        "".join(f"\t\t{display_field(f)};\n" for f in method.parameters) +\
        "\t\treturns {\n" +\
        "".join(f"\t\t\t{display_field(f)};\n" for f in method.returns) +\
        "\t\t}\n" +\
        "\t}\n"

def display_thing(thing: SusThing):
    if isinstance(thing, (SusBitfield, SusEnum)):
        kw = "enum" if isinstance(thing, SusEnum) else "bitfield"
        return f"{kw} {thing.name} " + "{\n" +\
            "".join(f"\t{m.name}({m.value}),\n" for m in thing.members) +\
            "}"

    elif isinstance(thing, SusEntity):
        return f"entity {thing.name} " + "{\n" +\
            "".join(f"\t{display_field(f)};\n" for f in thing.fields) +\
            "".join("\n" + display_method(m) for m in thing.methods) +\
            "}"

    elif isinstance(thing, SusCompound):
        return f"compound {thing.name} " + "{\n" +\
            "".join(f"\t{display_field(f)};\n" for f in thing.fields) +\
            "}"

# finds the thing (that can be used as a type) from a token at that position
def find_thing(params: TextDocumentPositionParams) -> tuple[str, SusThing]:
    global foles
    file = files[params.text_document.uri]

    # list of things that can be used as types
    things: list[SusThing] = []
    for thing in file.things:
        if isinstance(thing, (SusEntity, SusCompound, SusEnum, SusBitfield)):
            things.append(thing)

    line = file.source.split("\n")[params.position.line]
    # find first non-alpha char to the left
    start = params.position.character
    while start > 0 and line[start - 1].isalpha():
        start -= 1
    # find last alpha char to the right
    end = start
    while end < len(line) and line[end].isalpha():
        end += 1

    # find token
    token = line[start:end]
    for thing in things:
        if thing.name == token:
            return token, thing
    return token, None

@server.feature(HOVER)
def hover(params: HoverParams):
    # find the thing that is being hovered over
    token, thing = find_thing(params)
    log.verbose(f"Hovering: '{token}'", "ls")
    if thing:
        contents = [MarkedString(
            language="sus",
            value=display_thing(thing)
        )]
        if thing.docstring:
            contents.append(thing.docstring)
        return Hover(contents=contents)
        
    if token in ("Str", "Int", "List", "Bool"):
        return Hover(contents=[MarkedString(
            language="sus",
            value = f"(built-in) {token}"
        )])

@server.feature(DEFINITION)
def definition(params: DefinitionParams):
    # find the thing that is being hovered over
    token, thing = find_thing(params)
    log.verbose(f"Go to def: '{token}'", "ls")
    if thing:
        location = thing.location
        uri = "file://" + location.file.path
        return Location(
            uri=uri,
            range=Range(
                start=Position(line=location.line - 1, character=location.col - 1),
                end=Position(line=location.line - 1, character=location.col - 1 + location.dur)
            ),
        )

def start(io: bool):
    if io:
        log.ALL_STDERR = True
        server.start_io()
    else:
        log.done("Starting on localhost:9090")
        server.start_tcp("127.0.0.1", 9090)
