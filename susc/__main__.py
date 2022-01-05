import argparse
import susc, sys
from os import path
from colorama import Fore

from susc import exceptions
from . import log
from time import time
from .watch import gen_ts

def highlight(file):
    for line in file.readlines():
        print(susc.log.highlight_syntax(line), end='')

def main():
    all_start = time()

    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="file to compile", type=argparse.FileType(mode="r", encoding="utf8"))
    parser.add_argument("-o", "--output", help="override output dir")
    parser.add_argument("-l", "--lang", help="override `set output` directive")
    parser.add_argument("-v", "--verbose", help="verbose logging", action="store_true")
    parser.add_argument("-p", "--highlight", help="print contents of a SUS file with highlighting", action="store_true")
    parser.add_argument("-t", "--gen-ts", help="watch source files and generate .d.ts files in background", action="store_true")
    parser.add_argument("-s", "--single-line-errors", help="output errors in a parsable format", action="store_true")
    args = parser.parse_args()

    exceptions.SINGLE_LINE_ERRORS = args.single_line_errors
    log.VERBOSE = args.verbose
    if log.VERBOSE:
        log.verbose("Verbose mode enabled")
    # default value
    if not args.output:
        args.output = path.join(path.dirname(args.source.name), path.splitext(path.basename(args.source.name))[0] + "_output")

    if args.highlight:
        highlight(args.source)
        return

    if args.gen_ts:
        gen_ts(args.source)
        return
    
    sus_file = susc.SusFile(args.source)
    try:
        sus_file.parse()
    except susc.exceptions.SusError as ex:
        log.error(str(ex))
        return
    
    langs = args.lang or sus_file.settings.get("output", None)
    if not langs:
        log.warn(f"No output languages specified. Use the {Fore.GREEN}'set output <language list>'{Fore.WHITE} directive in the root file or pass {Fore.GREEN}'-l <language list>'{Fore.WHITE} to the compiler")
        return

    langs = langs.split()
    for lang in langs:
        try:
            sus_file.write_output(lang, path.join(args.output, lang))
        except susc.exceptions.SusOutputError as ex:
            log.error(str(ex))
            return

    all_end = time()
    langs = len(langs)
    log.done(f"Compiled project into {langs} language{'s' if langs > 1 else ''} in {int((all_end - all_start) * 1000)}ms")

if __name__ == "__main__":
    main()