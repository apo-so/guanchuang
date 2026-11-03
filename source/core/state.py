"""Small explicit expression subset. Unknown is never silently true."""
import re


def split_args(text):
    rows, start, depth, quoted, escaped = [], 0, 0, False, False
    for i, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if ch == '\\' and quoted:
            escaped = True
        elif ch == "'":
            quoted = not quoted
        elif not quoted:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == ',' and depth == 0:
                rows.append(text[start:i].strip()); start = i + 1
    if text[start:].strip():
        rows.append(text[start:].strip())
    return rows


def evaluate(expression, bindings):
    if expression is None:
        return {'status': 'KNOWN', 'value': True, 'basis': 'NO_CONDITION'}
    expr = str(expression).strip()
    if expr.startswith('[') and expr.endswith(']'):
        expr = expr[1:-1].strip()
    if expr in bindings:
        return {'status': 'KNOWN', 'value': bindings[expr], 'basis': 'EXPLICIT_FIXTURE'}
    literals = {'yes': True, 'no': False, "'(bool)yes'": True, "'(bool)no'": False, 'true': True, 'false': False}
    if expr in literals:
        return {'status': 'KNOWN', 'value': literals[expr], 'basis': 'LITERAL'}
    match = re.fullmatch(r'StringIsEmpty\s*\((.*)\)', expr, re.S)
    if match:
        args = split_args(match[1])
        if len(args) != 1:
            return {'status': 'INVALID', 'value': None, 'basis': 'STRING_FUNCTION_ARITY'}
        value = evaluate(args[0], bindings)
        if value['status'] != 'KNOWN':
            return value
        if not isinstance(value['value'], str):
            return {'status': 'INVALID', 'value': None, 'basis': 'STRING_VALUE_REQUIRED'}
        return {'status': 'KNOWN', 'value': value['value'] == '', 'basis': 'MODELED_STRING_EMPTY'}
    match = re.fullmatch(r'(And|Or|Not)\s*\((.*)\)', expr, re.S)
    if match:
        op, raw = match.groups()
        args = split_args(raw)
        if len(args) != (1 if op == 'Not' else 2):
            return {'status': 'INVALID', 'value': None, 'basis': 'VERSIONED_BINARY_LOGIC_ARITY'}
        values = [evaluate(arg, bindings) for arg in args]
        if any(row['status'] == 'INVALID' for row in values):
            return {'status': 'INVALID', 'value': None, 'basis': 'INVALID_ARGUMENT'}
        known = [row['value'] if row['status'] == 'KNOWN' else None for row in values]
        if op == 'Not' and known[0] is not None:
            answer = not known[0]
        elif op == 'And' and False in known:
            answer = False
        elif op == 'Or' and True in known:
            answer = True
        elif None in known:
            return {'status': 'UNKNOWN', 'value': None, 'basis': 'UNKNOWN_ARGUMENT'}
        else:
            answer = all(known) if op == 'And' else any(known)
        return {'status': 'KNOWN', 'value': answer, 'basis': 'MODELED_LOGIC'}
    match = re.fullmatch(r"GetVariableSystem\.(HasValue|Exists)\s*\((.*)\)", expr, re.S)
    if match:
        name, raw = match.groups()
        args = split_args(raw)
        if len(args) != (2 if name == 'HasValue' else 1):
            return {'status': 'INVALID', 'value': None, 'basis': 'VARIABLE_FUNCTION_ARITY'}
        key = 'GetVariableSystem.' + args[0].strip("'")
        if key in bindings:
            answer = bindings[key] == args[1].strip("'") if name == 'HasValue' else bindings[key] is not None
            return {'status': 'KNOWN', 'value': answer, 'basis': 'EXPLICIT_FIXTURE'}
    return {'status': 'UNKNOWN', 'value': None, 'basis': 'UNIMPLEMENTED_BINDING_OR_MISSING_STATE', 'expression': expr}
