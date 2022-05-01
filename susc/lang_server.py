from xmlrpc.client import Boolean
from pygls.server import LanguageServer
from pygls.lsp.methods import COMPLETION, TEXT_DOCUMENT_DID_CHANGE
from pygls.lsp.types import DidChangeTextDocumentParams, Diagnostic, Range, Position, DiagnosticSeverity

from . import log
from . import File
from . import exceptions

server = LanguageServer()

@server.feature(TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: DidChangeTextDocumentParams):
    ls.show_message_log("Parsing project")
    source = ls.workspace.get_document(params.text_document.uri).source

    file = File()
    file.load_from_text(source)
    _, diagnostics = file.parse()
    diag_list = []

    for diag in diagnostics:
        for location in diag.locations:
            # ignore locations that are not in the current file
            if location.file.path != "<from source>":
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

def start(io: Boolean):
    if io:
        log.ALL_STDERR = True
        server.start_io()
    else:
        log.done("Starting on localhost:9090")
        server.start_tcp("127.0.0.1", 9090)
