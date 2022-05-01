from xmlrpc.client import Boolean
from pygls.server import LanguageServer
from pygls.lsp.methods import COMPLETION, TEXT_DOCUMENT_DID_CHANGE
from pygls.lsp.types import DidChangeTextDocumentParams, Diagnostic, Range, Position

from . import log
from . import SusFile
from . import exceptions

server = LanguageServer()

@server.feature(TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: DidChangeTextDocumentParams):
    ls.show_message_log("Parsing project")
    source = ls.workspace.get_document(params.text_document.uri).source

    file = SusFile()
    file.load_from_text(source)
    try:
        file.parse()
        ls.publish_diagnostics(params.text_document.uri, [])
    except exceptions.SusSourceError as ex:
        diag_list = []
        for location in ex.locations:
            if location.file != "<from source>":
                continue
            diag = Diagnostic(
                range=Range(
                    start=Position(line=location.line - 1, character=location.col - 1),
                    end=Position(line=location.line - 1, character=location.col - 1 + location.dur)
                ),
                message=ex.text,
                source="susc",
                severity=1
            )
            diag_list.append(diag)
        
        ls.publish_diagnostics(params.text_document.uri, diag_list)

    ls.show_message_log("Parsing done")

def start(io: Boolean):
    if io:
        log.ALL_STDERR = True
        server.start_io()
    else:
        log.done("Starting on localhost:9090")
        server.start_tcp("127.0.0.1", 9090)
