from os import get_terminal_size
from colorama import Fore, Back
from sys import stderr
import re, lark

VERBOSE = False
SUS_COLORS = {
    "(\".*\")|('.*')": Fore.LIGHTGREEN_EX,
    "/.+/[ims]{0,3}": Fore.LIGHTCYAN_EX,
    "#.*$": Fore.LIGHTBLACK_EX,
    "\\b([0-9]+|false|true|([0-9]+(y|mo|d|h|m|s|ms)))\\b": Fore.LIGHTYELLOW_EX,
    "\\b(enum|bitfield|confirmation|entity|opt|cache|hard|soft|method|staticmethod|globalmethod|compound|request|response|returns|errors|confirmations|states|ratelimit|every)\\b": Fore.MAGENTA,
    "[.,;:]": Fore.LIGHTBLUE_EX,
    "\\b[a-z][a-z_]*\\b": Fore.WHITE,
    "\\b[A-Z][A-Za-z]*\\b": Fore.YELLOW,
}

def log(back, fore, prefix, text, file):
    print(f"{back}{fore} {prefix} {Back.RESET}{Fore.WHITE} {text}", file=file)

def error(text):
    log(Back.RED, Fore.BLACK, "ERR!", text, stderr)
def warn(text):
    log(Back.YELLOW, Fore.BLACK, "WARN", text, stderr)
def info(text):
    log(Back.BLUE, Fore.BLACK, "INFO", text, None)
def done(text):
    log(Back.GREEN, Fore.BLACK, "DONE", text, None)
def verbose(text):
    if VERBOSE:
        log(Back.LIGHTBLACK_EX, Fore.WHITE, "DEBUG", text, None)

def highlight_syntax(line, colors=SUS_COLORS):
    if colors is SUS_COLORS:
        if line.startswith("include"):
            return Fore.MAGENTA + "include" + Fore.LIGHTGREEN_EX + line[7:]
        if line.startswith("set"):
            return Fore.MAGENTA + "set" + Fore.LIGHTGREEN_EX + line[3:]

    color_tokens = []
    for regex, color in colors.items():
        for entry in re.finditer(regex, line):
            start, end = entry.span()
            span = range(start, end)
            # check if something is already in these bounds
            flag = True
            for ex_span, _ in color_tokens:
                if len(set(ex_span).intersection(span)) != 0:
                    flag = False
                    break
            if not flag:
                continue

            color_tokens.append((span, color))
    color_tokens = sorted(color_tokens, key=lambda t: t[0][0])

    # highlight ranges while maintaining an offset
    offs = 0
    for span, color in color_tokens:
        start, end = span[0] + offs, span[-1] + 1 + offs
        replacement = color + line[start:end] + Fore.WHITE
        line = line[:start] + replacement + line[end:]
        offs += len(color) + len(Fore.WHITE)

    return line

def highlight_ast(ast):
    if not VERBOSE:
        return str(ast)
    if isinstance(ast, lark.Tree):
        return f"{Fore.YELLOW}{ast.data}{Fore.WHITE}[{', '.join([highlight_ast(c) for c in ast.children])}{Fore.WHITE}]"
    elif isinstance(ast, lark.Token):
        return f"{Fore.CYAN}{ast.type}{Fore.WHITE}{Fore.GREEN}'{ast.value}'{Fore.WHITE}"
    elif ast is None:
        return Fore.LIGHTBLACK_EX + "None" + Fore.WHITE

def highlight_thing(thing):
    thing = str(thing)
    if not VERBOSE:
        return thing
    thing = highlight_syntax(thing, {
        "'[^,']+'": Fore.GREEN,
        "location=[^:]+:[0-9]+:[0-9]+\([0-9]+\)": Fore.LIGHTBLACK_EX,
        "[a-z][a-z_]+=": Fore.CYAN,
        "\\bSus[A-Za-z]+\\b": Fore.YELLOW,
        "\\b(None|True|False|[0-9]+)\\b": Fore.LIGHTYELLOW_EX,
        "[.,;:]": Fore.LIGHTBLUE_EX,
    })
    
    return thing