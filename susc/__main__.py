import argparse
import susc, sys
from os import path
from colorama import Fore
from . import log
from time import time

def highlight(file):
    for line in file.readlines():
        print(susc.log.highlight_syntax(line), end='')

def main():
    all_start = time()

    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="file to compile", type=argparse.FileType(mode="r", encoding="utf8"))
    parser.add_argument("-o", "--output", help="override the output dir")
    parser.add_argument("-v", "--verbose", help="verbose logging", action="store_true")
    parser.add_argument("-p", "--highlight", help="print the contents of a SUS file with highlighting", action="store_true")
    args = parser.parse_args()

    log.VERBOSE = args.verbose
    if log.VERBOSE:
        log.verbose("Verbose mode enabled")
    # default value
    if args.output == None:
        args.output = path.join(path.dirname(args.source.name), path.splitext(path.basename(args.source.name))[0] + "_output")

    if args.highlight:
        highlight(args.source)
        return
    
    sus_file = susc.SusFile(args.source)
    try:
        sus_file.parse()
    except susc.exceptions.SusError as ex:
        log.error(str(ex))
        return
    
    if "output" not in sus_file.settings:
        log.warn(f"No output languages specified. Use the {Fore.GREEN}'set output <language list>'{Fore.WHITE} directive")
        return

    langs = sus_file.settings["output"].split()
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