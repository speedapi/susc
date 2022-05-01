from .things import *
from . import log
from .exceptions import *

MAGIC_IDENTIFIERS = ["Entity"]

def validate_fields(identifiers: List[str], field_sets: List[List[SusField]]) -> None:
    log.verbose("Validating fields")

    for fields in field_sets:
        for f1 in fields:
            # optional values mod 256
            if f1.optional != None and f1.optional >= 256:
                SusSourceError([f1.location], f"Optional value '{f1.optional}' will be taken mod 256 ('{f1.optional % 256}')").print_warn()
                f1.optional %= 256

            # the fields within one set shouldn't have matching name or values
            equal = [f2 for f2 in fields if f2.name == f1.name]
            if len(equal) > 1:
                raise SusSourceError([f.location for f in equal], f"Multiple fields with matching names '{f1.name}'")
            equal = [f2 for f2 in fields if f2.optional == f1.optional and f1.optional != None]
            if len(equal) > 1:
                raise SusSourceError([f.location for f in equal], f"Multiple fields with matching optional values '{f1.optional}'")

            # validate the type
            type_err = f1.type_.find_errors(identifiers)
            if type_err != None:
                raise SusSourceError([f1.type_.location], type_err)

def combine(things: List[SusThing]) -> List[SusThing]:
    log.verbose(f"Combining {len(things)} total definitions")
    ignore, out = [], []
    for thing1 in things:
        if thing1.name in ignore:
            continue
        # find things with same name
        with_matching_name = [thing2 for thing2 in things if thing2.name == thing1.name]
        if len(with_matching_name) > 1:
            # throw redefinition errors
            for thing2 in with_matching_name:
                if type(thing1) is not type(thing2):
                    raise SusSourceError([t.location for t in with_matching_name],
                        f"Multiple things of different types with matching name '{thing1.name}'")
                elif not isinstance(thing1, (SusEnum, SusBitfield)):
                    raise SusSourceError([t.location for t in with_matching_name],
                        f"Redefinition of '{thing1.name}' (only enums and bitfields can be combined)")

            # match sizes
            if not all([t.size == thing1.size for t in with_matching_name]):
                raise SusSourceError([t.location for t in with_matching_name],
                    "Can't combine things of different sizes")

            # record members of enums and mitfields
            opt_members = []
            for t in with_matching_name:
                opt_members += t.members

            # find clashes
            for m1 in opt_members:
                for m2 in opt_members:
                    if m1 is not m2 and m1.name == m2.name:
                        raise SusSourceError([m1.location, m2.location], f"Multiple members with matching names '{m1.name}'")
                    if m1 is not m2 and m1.value == m2.value:
                        raise SusSourceError([m1.location, m2.location], f"Multiple members with matching values '{m1.value}'")

            # finally, combine all members
            constructor = SusEnum if isinstance(thing1, SusEnum) else SusBitfield
            doc = (thing1.docstring or "") + "\n" + (thing2.docstring or "")
            if doc == "\n": doc = None
            new_thing = constructor(thing1.location, doc, thing1.name, thing1.size, opt_members)
            out.append(new_thing)
            log.verbose(f"{Fore.LIGHTBLACK_EX}Combined {constructor.__name__[3:].lower()} {Fore.WHITE}{thing1.name}{Fore.LIGHTBLACK_EX} members across {len(with_matching_name)} definitions: {Fore.WHITE}{new_thing}")
        else:
            out.append(thing1)
        ignore.append(thing1.name)

        # check numeric values
        if isinstance(thing1, (SusEnum, SusBitfield)):
            maximum = (thing1.size * 8 if isinstance(thing1, SusBitfield) else 256 ** thing1.size) - 1
            for member in thing1.members:
                if member.value > maximum:
                    SusSourceError([member.location], f"Member value '{member.value}' overflow (max '{maximum}')").print_warn()
        if isinstance(thing1, (SusEntity, SusMethod)) and thing1.value > 127:
            SusSourceError([thing1.location], f"Value '{thing1.value}' overflow (max '127')").print_warn()
        if isinstance(thing1, SusConfirmation) and thing1.value > 15:
            SusSourceError([thing1.location], f"Value '{thing1.value}' overflow (max '15')").print_warn()

    log.verbose(f"Combined {len(things)} definitions into {len(out)} things")
    return out

def validate_method_meta(things: List[SusThing], method_sets: List[List[SusMethod]]) -> None:
    log.verbose("Validating method metdata")

    errors = [t for t in things if isinstance(t, SusEnum) and t.name == "ErrorCode"]
    confirmations = [t.name for t in things if isinstance(t, SusConfirmation)]
    error_names = []
    
    for m_set in method_sets:
        for method in m_set:
            if len(method.errors) > 0 and len(errors) == 0:
                raise SusSourceError([], "No 'ErrorCode' enum defined. Include 'impostor.sus' or use a custom definition")
            errors_names = [m.name for m in errors[0].members]

            for err in method.errors:
                if err not in errors_names:
                    raise SusSourceError([method.location], f"Undefined error code '{err}'")
            for conf in method.confirmations:
                if conf not in confirmations:
                    raise SusSourceError([method.location], f"Undefined confirmation '{conf}'")

def validate_values(entities: List[SusEntity], method_sets: List[List[SusMethod]]) -> None:
    log.verbose("Validating numeric values")

    for thing in entities:
        matching = [t for t in entities if t.value == thing.value]
        if len(matching) != 1:
            raise SusSourceError([t.location for t in matching], f"Multiple entities with matching values '{thing.value}'")
        # check ID field
        id_field = [f for f in thing.fields if f.name == "id"]
        if not id_field:
            SusSourceError([thing.location], f"No 'id' field").print_warn()
        else:
            id_field = id_field[0]
            if id_field.type_.name != "Int" or id_field.type_.args[0] != 8:
                SusSourceError([id_field.location], f"The 'id' field is not an Int(8)").print_warn()

    for m_set in method_sets:
        for method in m_set:
            matching = [t for t in m_set if t.value == method.value]
            if len(matching) != 1:
                raise SusSourceError([t.location for t in matching], f"Multiple methods with matching values '{method.value}'")

def strip_docstrings(things: List[SusThing]) -> List[SusThing]:
    for thing in things:
        doc = thing.docstring
        thing.docstring = doc.strip() if doc else None
    return things

def run(things: List[SusThing]) -> List[SusThing]:
    log.verbose("Running linker")

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
    
    # run substeps
    validate_fields(identifiers, field_sets)
    things = combine(things)
    validate_method_meta(things, method_sets)
    validate_values(entities, method_sets)
    things = strip_docstrings(things)
    
    return things