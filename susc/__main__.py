import argparse
from os import path
from colorama import Fore
from time import time

from . import File
from . import exceptions
from . import log
from . import lang_server
from .explain import explain

def highlight(file):
    for line in file.readlines():
        print(log.highlight_syntax(line), end='')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="file(s) to compile", type=argparse.FileType(mode="r", encoding="utf8"), nargs="*")
    parser.add_argument("-o", "--output", help="override output dir")
    parser.add_argument("-l", "--lang", help="override `set output` directive")
    parser.add_argument("-v", "--verbose", help="verbose logging", action="store_true")
    parser.add_argument("-p", "--highlight", help="print contents of a SUS file with highlighting", action="store_true")
    parser.add_argument("-e", "--single-line-errors", help="output errors in a parsable format", action="store_true")
    parser.add_argument("-s", "--language-server", help="run as a language server", action="store_true")
    parser.add_argument("-i", "--ls-stdio", help="run LS in stdio mode", action="store_true")
    parser.add_argument("-x", "--explain", help="explain an error code")
    args = parser.parse_args()

    exceptions.SINGLE_LINE_ERRORS = args.single_line_errors
    log.VERBOSE = args.verbose
    if log.VERBOSE:
        log.verbose("Verbose mode enabled")

    if args.explain:
        explain(int(args.explain))
        return

    if args.language_server:
        lang_server.start(args.ls_stdio)
        return
    if args.ls_stdio:
        log.error("--ls-stdio can only be used with --language-server")
        return

    if args.highlight:
        for file in args.source:
            log.info(file.name)
            highlight(file)
        return

    if len(args.source) > 1 and args.output is not None:
        log.warn(f"More than one project specified. {Fore.GREEN}'-o {args.output}'{Fore.WHITE} will be ignored")
    
    if len(args.source) == 0:
        log.error("No source files specified")
        return

    successful = 0
    global_start = time()
    for i, source in enumerate(args.source):
        proj_start = time()
        if len(args.source) > 1:
            log.info(f"Compiling project {Fore.GREEN}'{source.name}'{Fore.WHITE} ({Fore.GREEN}{i + 1}/{len(args.source)}{Fore.WHITE})")

        sus_file = File()
        sus_file.load_from_file(source)

        # parse file and print diagnostics
        _, diagnostics = sus_file.parse()
        has_error = False
        for diag in diagnostics:
            exceptions.SourceError(diag).print()
            print()
            if diag.level == exceptions.DiagLevel.ERROR:
                has_error = True
        if has_error:
            continue
        
        langs = args.lang or sus_file.settings.get("output", None)
        if not langs:
            log.error(f"{Fore.RED}No output languages specified. Use the 'set output <language list>' directive in the root file or pass '-l <language list>' to the compiler")
            continue

        langs = langs.split()
        for lang in langs:
            output = args.output
            if len(args.source) > 1 or output is None:
                output = path.join(path.dirname(source.name), path.splitext(path.basename(source.name))[0] + "_output")
                
            try:
                sus_file.write_output(lang, path.join(output, lang))
            except exceptions.OutputError as ex:
                log.error(str(ex))
                continue

        proj_end = time()
        successful += 1
        took = int((proj_end - proj_start) * 1000)
        log.done(f"Compiled project into {len(langs)} language{'s' if len(langs) > 1 else ''} in {took}ms")

    global_end = time()
    took = int((global_end - global_start) * 1000)
    if len(args.source) > 1:
        log.done(f"Compiled {Fore.GREEN}{successful}/{len(args.source)}{Fore.WHITE} projects successfully in {took}ms")

if __name__ == "__main__":
    main()
