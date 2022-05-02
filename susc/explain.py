import re
from textwrap import dedent
from colorama import Fore, Back

from .exceptions import DiagLevel
from . import log
from . import File

class Explanation:
    source: str
    level: DiagLevel
    explanation: str

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

EXPLANATIONS = {
    #
    # PARSER
    #
    
    1: Explanation(
        source="parser",
        level=DiagLevel.ERROR,
        explanation="""
        A generic syntax error in the source code that the parser was not able
        to narrow down further.

        ```
        compound Example {
            field: 
        }
        ``````
        compound Example {
            a: Str
            b: Str;
        }
        ```
        """
    ),
    2: Explanation(
        source="parser",
        level=DiagLevel.ERROR,
        explanation="""
        A naming convention violation was detected.

        WRONG:
        ```
        compound example { }
        ``````
        globalmethod Example(0) { }
        ```
        RIGHT:
        ```
        compound Example { }
        ``````
        globalmethod example(0) { }
        ```
        """
    ),
    3: Explanation(
        source="parser",
        level=DiagLevel.ERROR,
        explanation="""
        The item was supposed to declare a numeric value or size parameter.

        WRONG:
        ```
        entity Example { }
        ``````
        enum Example { }
        ```
        RIGHT:
        ```
        # to learn why entities have to have this parameter,
        # run 'susc --explain 8'
        entity Example(0) { }
        ``````
        # this is different and defines the enum representation size
        enum(1) Example { }
        ```
        """
    ),
    4: Explanation(
        source="parser",
        level=DiagLevel.ERROR,
        explanation="""
        The name was omitted.

        WRONG:
        ```
        compound { }
        ```
        RIGHT:
        ```
        compound Name { }
        ```
        """
    ),

    #
    # RESOLVER
    #

    5: Explanation(
        source="resolver",
        level=DiagLevel.ERROR,
        explanation="""
        The compiler was not able to find a file referenced in "include".

        ```
        include this_file_doesnt_exist
        ```
        """
    ),
    6: Explanation(
        source="resolver",
        level=DiagLevel.WARN,
        explanation="""
        A file was included multiple times.
        Declarations that resolve to the same file are considered to be
        equivalent.

        ```
        include impostor
        include impostor
        ``````
        include impostor
        include impostor.sus
        ```
        """
    ),
    7: Explanation(
        source="resolver",
        level=DiagLevel.WARN,
        explanation="""
        The compiler encountered a setting that it does not know.
        This diagnostic doesn't mean that the setting was ignored.

        ```
        set example 123
        ```
        """
    ),

    #
    # LINKER
    #

    8: Explanation(
        source="linker",
        level=DiagLevel.WARN,
        explanation="""
        A numeric value was taken modulo its max possible value.
          - In `opt(x)`, x must be <= 255
          - In `method|globalmethod|staticmethod name(x)`, x must be <= 127
          - In `entity Name(x)`, x must be <= 63
          - In `confirmation Name(x)`, x must be <= 15
          - In `enum(x) Name { member(y) }`, y must be <= 2^x - 1
          - In `bitfield(x) Name { member(y) }`, y must be <= x*8 - 1

        This numeric value is used to distinguish between different things when
        they're sent over the wire. We don't use names for that because they're
        too large.

        ```
        compound Example {
            field: opt(1000) Str;
        }
        ``````
        entity Name(1000) { }
        ``````
        confirmation Name(100) {
            request { }
            response { }
        }
        ```
        """
    ),
    9: Explanation(
        source="linker",
        level=DiagLevel.ERROR,
        explanation="""
        There were multiple fields with the same name in the same structure.

        ```
        compound Example {
            field: Str;
            field: Str;
            fine: Str;
        }
        ```
        """
    ),
    10: Explanation(
        source="linker",
        level=DiagLevel.ERROR,
        explanation="""
        There were multiple optional fields with the same opt() value in the
        same structure.

        WRONG:
        ```
        compound Example {
            first: opt(0) Str;
            second: opt(0) Str;
            fine: opt(1) Str;
            also_fine: Str;
        }
        ```
        RIGHT:
        ```
        compound Example {
            first: opt(0) Str;
            second: opt(1) Str;
            fine: opt(2) Str;
            also_fine: Str;
        }
        ```
        """
    ),
    11: Explanation(
        source="linker",
        level=DiagLevel.ERROR,
        explanation="""
        A type instantiation error was detected. Mismatches in the number and/or
        types of parameters and validators fall in this category.

        ```
        compound Example {
            a: Int;
            b: Int();
            c: Int(Bool);
            d: Int(1)[len: 3+];

            e: Str(1);
            f: Str[len: /regexp?/i];
            g: Str[match: 10..20];
        }
        ```
        """
    ),
    12: Explanation(
        source="linker",
        level=DiagLevel.ERROR,
        explanation="""
        AMOGUS provides a mechanism to combine declarations of `enum`s and
        `bitfield`s that are split apart, even across files.

        ```
        enum(1) A {
            a(0), b(1), c(2)
        }
        enum(1) A {
            d(3), e(4), f(5)
        }
        # A contains members 'a' through 'f'
        ```
        However, this mechanism only applies to `enum`s and `bitfield`s. Trying
        to use this mechanism for other data types will result in this
        redefinion error.

        ```
        include impostor
        entity A(0) {
            id: Int(8);
            field_a: Str;
        }
        entity A(0) {
            id: Int(8);
            field_b: Str;
        }
        ```
        """
    ),
    13: Explanation(
        source="linker",
        level=DiagLevel.ERROR,
        explanation="""
        AMOGUS provides a mechanism to combine declarations of `enum`s and
        `bitfield`s that are split apart, even across files.

        ```
        enum(1) A {
            a(0), b(1), c(2)
        }
        enum(1) A {
            d(3), e(4), f(5)
        }
        # A contains members 'a' through 'f'
        ```
        However, this mechanism can only work if the declarations have the same
        size.

        ```
        enum(1) A {
            a(0), b(1), c(2)
        }
        enum(2) A {
            d(3), e(4), f(5)
        }
        ```
        """
    ),
    14: Explanation(
        source="linker",
        level=DiagLevel.ERROR,
        explanation="""
        An undefined confirmation was referenced.

        ```
        globalmethod example(0) {
            confirmations { Example }
        }
        ```
        """
    ),
    15: Explanation(
        source="linker",
        level=DiagLevel.WARN,
        explanation="""
        A method tried to reference an error code, but the `ErrorCode` enum was
        not defined anywhere. To fix this, define the `ErrorCode` enum yourself
        or simply `include impostor.sus`.

        Note that you can define your own error codes even if you've included the
        the standard library using the combination feature. Run susc --explain 12
        to see how.

        ```
        globalmethod example(0) {
            errors { invalid_id }
        }
        ```
        """
    ),
    16: Explanation(
        source="linker",
        level=DiagLevel.ERROR,
        explanation="""
        A method tried to reference an error code, and the `ErrorCode` enum was
        found, but it did not have that member.

        ```
        include impostor
        globalmethod example(0) {
            errors { not_a_thing }
        }
        ```
        """
    ),
    17: Explanation(
        source="linker",
        level=DiagLevel.ERROR,
        explanation="""
        Multiple things with matching numeric values were declared. These values
        are used to distinguish between different things when they're sent over
        the wire because textual names are too large.

        WRONG:
        ```
        globalmethod example_a(0) { }
        globalmethod example_b(0) { }
        ```
        RIGHT:
        ```
        globalmethod example_a(0) { }
        globalmethod example_b(1) { }
        ```
        """
    ),
    18: Explanation(
        source="linker",
        level=DiagLevel.WARN,
        explanation="""
        The entity did not have an `id` field or its type was not `Int(8)`.

        WRONG:
        ```
        include impostor.sus
        entity ExampleA(0) { }
        entity ExampleB(1) {
            id: Str;
        }
        ```
        RIGHT:
        ```
        entity Example(0) {
            id: Int(8);
        }
        ```
        """
    ),
}





def compile_code_block(code: str, match_code: int = -1) -> str:
    file = File()
    file.load_from_text(code)
    _, diag = file.parse()

    # map diagnostics to lines
    squiggles = {}
    for d in diag:
        # only match a specific code
        if match_code > 0 and d.code != match_code:
            continue
        # save squiggle locations
        color = {
            DiagLevel.ERROR: Fore.RED,
            DiagLevel.WARN: Fore.YELLOW,
            DiagLevel.INFO: Fore.BLUE
        }[d.level]
        for l in d.locations:
            if l.line - 1 not in squiggles:
                squiggles[l.line - 1] = color, d.message, l.col - 1, l.dur

    result = ""
    lines = code.split("\n")
    n_len = len(str(len(lines) + 1)) # width of line numbers
    for n, line in enumerate(lines):
        highlighted = log.highlight_syntax(line)
        # line itself
        result += f" {Fore.LIGHTBLACK_EX}{str(n + 1).rjust(n_len)} | {Fore.WHITE}{highlighted}\n"
        if n in squiggles:
            color, message, offs, dur = squiggles[n]
            # squiggles and error message
            squiggle = " " * offs + "~" * dur
            result += f" {Fore.LIGHTBLACK_EX}{' ' * n_len} | {color}{squiggle}\n"
            for m_line in message.split("\n"):
                result += f" {Fore.LIGHTBLACK_EX}{' ' * n_len} | {color}{m_line}\n"

    return result + f"{Fore.WHITE}\n"

def explain(n: int):
    if n not in EXPLANATIONS:
        log.error(f"Unknown error code '{n}'")
        return
    exp = EXPLANATIONS[n]

    # print headers

    print(f"{Back.LIGHTBLACK_EX}{Fore.WHITE}   CODE {Back.WHITE}{Fore.BLACK} {str(n).rjust(4, '0')} {Back.RESET}")

    level = ["error", "warning", "info"][exp.level.value - 1]
    level_color = [Back.RED, Back.YELLOW, Back.BLUE][exp.level.value - 1]
    print(f"{Back.LIGHTBLACK_EX}{Fore.WHITE}  LEVEL {level_color}{Fore.BLACK} {level} {Back.RESET}")

    source_color = {"linker": Back.BLUE, "parser": Back.GREEN, "resolver": Back.YELLOW}[exp.source]
    print(f"{Back.LIGHTBLACK_EX}{Fore.WHITE} SOURCE {source_color}{Fore.BLACK} {exp.source} {Back.RESET}")

    print(f"\n{Back.LIGHTBLACK_EX}{Fore.WHITE} EXPLANATION {Back.RESET}:")
    
    text = exp.explanation
    text = text.strip("\n")
    text = dedent(text)

    # syntax-highlight `inline code`
    text = re.sub(r"`([^`\n]+)`", lambda m:
        f"{Fore.LIGHTBLACK_EX}`{log.highlight_syntax(m.group(1))}{Fore.LIGHTBLACK_EX}`{Fore.WHITE}",
        text)

    # compile ```code blocks```
    text = re.sub(r"```([^`]+)```", lambda m: compile_code_block(m.group(1).strip("\n"), n), text)

    # emphasize keywords
    kw = {
        "WRONG": Back.RED,
        "RIGHT": Back.GREEN,
    }
    for k, v in kw.items():
        text = text.replace(k, f"{v}{Fore.BLACK} {k} {Fore.WHITE}{Back.RESET}")

    print(text)

