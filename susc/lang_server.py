from glob import iglob
from os import path
from pygls.server import LanguageServer
from pygls.lsp.methods import COMPLETION, TEXT_DOCUMENT_DID_CHANGE, HOVER
from pygls.lsp.types import (DidChangeTextDocumentParams, Diagnostic, Range,
                             Position, DiagnosticSeverity, CompletionOptions, CompletionParams,
                             CompletionList, CompletionItem, CompletionItemKind, HoverParams,
                             Hover, MarkedString)

from .things import SusBitfield, SusCompound, SusEntity, SusEnum, SusThing, SusField, SusType, SusValidator, SusMethod
from . import log
from . import File, KNOWN_SETTINGS

server = LanguageServer()
files: dict[str, File] = {}

@server.feature(TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: DidChangeTextDocumentParams):
    path = params.text_document.uri[len("file://"):]

    global files
    ls.show_message_log("Parsing project")
    source = ls.workspace.get_document(params.text_document.uri).source

    file = File()
    files[params.text_document.uri] = file

    file.load_from_text(source)
    file.path = path
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
                source="susc",
                severity=DiagnosticSeverity(diag.level.value)
            ))
        
    log.verbose("Pushing diagnostics")
    ls.publish_diagnostics(params.text_document.uri, diag_list)

    ls.show_message_log("Parsing done")

@server.feature(COMPLETION, CompletionOptions(trigger_characters=[":", "(", "[", ","]))
def completions(params: CompletionParams):
    global files
    file = files[params.text_document.uri]

    # what should we be finding?
    expected, state = file.insight(params.position.line, params.position.character)
    log.verbose(f"Parser expected {expected}")
    log.verbose(f"Parser state {state}")

    if "TYPE_IDENTIFIER" in expected:
        finding = "types"
    elif "VALIDATOR_IDENTIFIER" in expected:
        finding = "validators"
    elif "PATH" in expected:
        finding = "paths"
    elif "PARAMETER" in expected:
        finding = "parameters"
    else:
        return None

    # find precisely that
    log.verbose(f"Finding {finding}")
    items = []

    if finding == "types":
        for thing in file.things:
            if isinstance(thing, (SusEntity, SusCompound)):
                items.append(CompletionItem(label=thing.name, kind=CompletionItemKind.Class))
        items += [
            CompletionItem(label=n, kind=CompletionItemKind.TypeParameter)
            for n in ("Str", "Int", "List", "Bool")
        ]

    if finding == "validators":
        items += [
            CompletionItem(label=n, kind=CompletionItemKind.Property)
            for n in ["val", "len", "match"]
        ]

    if finding == "parameters":
        items += [
            CompletionItem(label=n, kind=CompletionItemKind.Property)
            for n in KNOWN_SETTINGS
        ]

    if finding == "paths":
        # find .sus files near this one
        for directory in file.search_paths():
            items += [
                CompletionItem(label=path.basename(n), kind=CompletionItemKind.File)
                for n in iglob(path.join(directory, "*.sus"))
            ]

    log.verbose("Sending completions")
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
        "(" + ','.join(display_t_arg(a) for a in t.args) + ")" +\
        "[" + ','.join(display_t_val(v) for v in t.validators) + "]"

def display_field(field: SusField):
    opt = f"opt({field.optional}) " if field.optional != None else ""
    return f"{field.name}: {opt}{display_type(field.type_)}"

def display_method(method: SusMethod):
    kw = "staticmethod" if method.static else "method"
    return f"\t{kw} {method.name}({method.value})" + "{\n" +\
        "".join(f"\t\t{display_field(f)};\n" for f in method.parameters) +\
        "\t\treturns {\n" +\
        "".join(f"\t\t\t{display_field(f)};\n" for f in method.returns) +\
        "\t\t}\n" +\
        "\t}\n"

def display_thing(thing: SusThing):
    if isinstance(thing, (SusBitfield, SusEnum)):
        kw = "enum" if isinstance(thing, SusEnum) else "bitfield"
        return f"{kw} {thing.name} " + "{\n" +\
            "".join(f"\t{m.name}({f.value}),\n" for m in thing.members) +\
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

@server.feature(HOVER)
def hover(params: HoverParams):
    global files
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
    # find token that is being hovered over
    token = line[start:end]

    # find the thing that is being hovered over
    for thing in things:
        if thing.location.file != file:
            continue
        if isinstance(thing, (SusEntity, SusEnum, SusBitfield, SusCompound)):
            if thing.name == token:
                contents = [MarkedString(
                    language="sus",
                    value=display_thing(thing)
                )]
                if thing.docstring:
                    contents.append(MarkedString(
                        language="markdown",
                        value=thing.docstring
                    ))
                return Hover(contents=contents)
        
    if token in ("Str", "Int", "List", "Bool"):
        return Hover(contents=[MarkedString(
            language="sus",
            value = f"(built-in) {token}"
        )])

def start(io: bool):
    if io:
        log.ALL_STDERR = True
        server.start_io()
    else:
        log.done("Starting on localhost:9090")
        server.start_tcp("127.0.0.1", 9090)
