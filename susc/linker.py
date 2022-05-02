from .things import *
from . import log
from .exceptions import *

MAGIC_IDENTIFIERS = ["Entity"]

def validate_fields(identifiers: List[str], field_sets: List[List[SusField]]) -> None:
    log.verbose("Validating fields", "linker")
    diag = []

    for fields in field_sets:
        for f1 in fields:
            # optional values mod 256
            if f1.optional != None and f1.optional >= 256:
                diag.append(Diagnostic([f1.location], DiagLevel.WARN, 8,
                    f"Optional value '{f1.optional}' will be taken mod 256 ('{f1.optional % 256}')"))
                f1.optional %= 256

            # the fields within one set shouldn't have matching names
            equal = [f2 for f2 in fields if f2.name == f1.name]
            if len(equal) > 1:
                diag.append(Diagnostic([f.location for f in equal], DiagLevel.ERROR, 9,
                    f"Multiple fields with matching names '{f1.name}'"))
            
            # or values
            equal = [f2 for f2 in fields if f2.optional == f1.optional and f1.optional != None]
            if len(equal) > 1:
                diag.append(Diagnostic([f.location for f in equal], DiagLevel.ERROR, 10,
                    f"Multiple fields with matching opt() values '{f1.optional}'"))

            # validate the type
            type_err = f1.type_.find_errors(identifiers)
            if type_err != None:
                diag.append(Diagnostic([f1.type_.location], DiagLevel.ERROR, 11, type_err))

    return diag

def combine(things: List[SusThing]) -> Tuple[list[SusThing], list[Diagnostic]]:
    log.verbose(f"Combining {len(things)} total definitions", "linker")
    diag = []
    ignore, out = [], []

    for thing1 in things:
        if thing1.name in ignore:
            continue

        # find things with same name
        with_matching_name = [thing2 for thing2 in things if thing2.name == thing1.name]

        if len(with_matching_name) > 1:
            # diagnose redefinitions
            fine = True
            for thing2 in with_matching_name:
                if type(thing1) != type(thing2) or not isinstance(thing1, (SusEnum, SusBitfield)):
                    diag.append(Diagnostic([t.location for t in with_matching_name], DiagLevel.ERROR, 12,
                        f"Redefinition of '{thing1.name}' (only enums and bitfields can be combined)"))
                    fine = False

            if fine:
                # match sizes
                if not all([t.size == thing1.size for t in with_matching_name]):
                    diag.append(Diagnostic([t.location for t in with_matching_name],
                        DiagLevel.ERROR, 13, "Can't combine things of different sizes"))

                # record members of enums and mitfields
                opt_members = []
                for t in with_matching_name:
                    opt_members += t.members

                # finally, combine all members
                constructor = SusEnum if isinstance(thing1, SusEnum) else SusBitfield
                doc = (thing1.docstring or "") + "\n" + (thing2.docstring or "")
                if doc == "\n": doc = None
                new_thing = constructor(thing1.location, doc, thing1.name, thing1.size, opt_members)
                out.append(new_thing)
                log.verbose(f"{Fore.LIGHTBLACK_EX}Combined {constructor.__name__[3:].lower()} {Fore.WHITE}{thing1.name}{Fore.LIGHTBLACK_EX} members across {len(with_matching_name)} definitions: {Fore.WHITE}{new_thing}", "linker")
        else:
            out.append(thing1)
        ignore.append(thing1.name)

        # check numeric values
        if isinstance(thing1, (SusEnum, SusBitfield)):
            maximum = (thing1.size * 8 if isinstance(thing1, SusBitfield) else 256 ** thing1.size) - 1
            for member in thing1.members:
                if member.value > maximum:
                    diag.append(Diagnostic([member.location], DiagLevel.WARN, 8,
                        f"Member value '{member.value}' overflow (max '{maximum}')"))

        if isinstance(thing1, (SusEntity, SusMethod)) and thing1.value > 127:
            diag.append(Diagnostic([thing1.location], DiagLevel.WARN, 8, f"Value '{thing1.value}' overflow (max '127')"))

        if isinstance(thing1, SusConfirmation) and thing1.value > 15:
            diag.append(Diagnostic([thing1.location], DiagLevel.WARN, 8, f"Value '{thing1.value}' overflow (max '15')"))

    log.verbose(f"Combined {len(things)} definitions into {len(out)} things", "linker")
    return out, diag

def validate_method_meta(things: List[SusThing], method_sets: List[List[SusMethod]]) -> None:
    log.verbose("Validating method metdata", "linker")
    diag = []

    errors = [t for t in things if isinstance(t, SusEnum) and t.name == "ErrorCode"]
    confirmations = [t.name for t in things if isinstance(t, SusConfirmation)]

    for m_set in method_sets:
        for method in m_set:
            for conf in method.confirmations:
                if conf not in confirmations:
                    diag.append(Diagnostic([method.location], DiagLevel.ERROR, 14, f"Undefined confirmation '{conf}'"))

            if len(method.errors) > 0 and len(errors) == 0:
                diag.append(Diagnostic([method.location], DiagLevel.WARN, 15,
                    "No 'ErrorCode' enum defined. Include 'impostor.sus' or use a custom definition"))
                continue
            if len(method.errors) == 0:
                continue
            error_names = [m.name for m in errors[0].members]

            for err in method.errors:
                if err not in error_names:
                    diag.append(Diagnostic([method.location], DiagLevel.ERROR, 16, f"Undefined error code '{err}'"))
    
    return diag

def validate_values(entities: List[SusEntity], method_sets: List[List[SusMethod]], confirmations: List[SusConfirmation]) -> None:
    log.verbose("Validating numeric values", "linker")
    diag = []

    for thing in entities:
        matching = [t for t in entities if t.value == thing.value]
        if len(matching) != 1:
            diag.append(Diagnostic([t.location for t in matching], DiagLevel.ERROR, 17,
                f"Multiple entities with matching values '{thing.value}'"))

        # check ID field
        id_field = [f for f in thing.fields if f.name == "id"]
        if not id_field:
            diag.append(Diagnostic([thing.location], DiagLevel.WARN, 18, f"No 'id' field"))
        else:
            id_field = id_field[0]
            t = id_field.type_
            if t.name != "Int" or len(t.args) != 1 or t.args[0] != 8:
                diag.append(Diagnostic([id_field.location], DiagLevel.WARN, 18, f"The 'id' field is not an Int(8)"))

    for m_set in method_sets:
        for method in m_set:
            matching = [t for t in m_set if t.value == method.value]
            if len(matching) != 1:
                diag.append(Diagnostic([t.location for t in matching], DiagLevel.ERROR, 17,
                    f"Multiple methods with matching values '{method.value}'"))

    for thing in confirmations:
        matching = [t for t in confirmations if t.value == thing.value]
        if len(matching) != 1:
            diag.append(Diagnostic([t.location for t in matching], DiagLevel.ERROR, 17,
                f"Multiple confirmations with matching values '{thing.value}'"))
    
    return diag

def strip_docstrings(things: List[SusThing]) -> List[SusThing]:
    for thing in things:
        doc = thing.docstring
        thing.docstring = doc.strip() if doc else None
    return things

def run(things: List[SusThing]) -> List[SusThing]:
    log.verbose("Running linker", "linker")

    # get all identifiers that can be referenced
    identifiers = [t.name for t in things if not isinstance(t, SusMethod)] + MAGIC_IDENTIFIERS
    # get all possible fields: entity fields, method params and method return vals
    entities = [t for t in things if isinstance(t, SusEntity)]
    methods = [t for t in things if isinstance(t, SusMethod)]
    confirmations = [t for t in things if isinstance(t, SusConfirmation)]
    compounds = [t for t in things if isinstance(t, SusCompound)]
    for e in entities: methods += e.methods
    field_sets = [e.fields for e in entities]
    field_sets += [m.parameters for m in methods]
    field_sets += [m.returns for m in methods]
    field_sets += [m.req_parameters for m in confirmations]
    field_sets += [m.resp_parameters for m in confirmations]
    field_sets += [c.fields for c in compounds]
    # get all methods
    method_sets = [[t for t in things if isinstance(t, SusMethod)]]
    for e in entities:
        method_sets.append([m for m in e.methods if m.static])
        method_sets.append([m for m in e.methods if not m.static])

    # run substeps collecting diagnostics
    things, diag = combine(things)
    diag += validate_fields(identifiers, field_sets)
    diag += validate_method_meta(things, method_sets)
    diag += validate_values(entities, method_sets, confirmations)
    things = strip_docstrings(things)

    # sort by severity
    diag = sorted(diag, key=lambda d: d.level.value)

    # remove diagnostics in the same location
    deduplicated = []
    used_locs = set()
    for d in diag:
        for loc in d.locations:
            has_duplicates = True
            if loc not in used_locs:
                has_duplicates = False
                used_locs.add(loc)
        if not has_duplicates:
            deduplicated.append(d)

    return things, deduplicated