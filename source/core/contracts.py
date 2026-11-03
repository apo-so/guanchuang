"""V1 identity and file contracts. No CK3 execution or layout approximation."""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

SCHEMA = '1.0'


class ContractError(ValueError):
    pass


def canonical(value):
    """UTF-8, sorted object keys, preserved array order; no NaN or normalization."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    def reject(value):
        raise ContractError('NON_FINITE_JSON: ' + value)
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ContractError('DUPLICATE_JSON_KEY: ' + key)
            out[key] = value
        return out
    return json.loads(Path(path).read_text(encoding='utf-8-sig'),
                      parse_constant=reject, object_pairs_hook=unique)


def write_json(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    read_json(tmp)
    tmp.replace(target)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def vector(value, length):
    return isinstance(value, list) and len(value) == length and all(number(x) for x in value)


def rect(value):
    if not vector(value, 4) or value[2] <= 0 or value[3] <= 0:
        raise ContractError('RECT_INVALID')
    return value


@lru_cache(maxsize=1)
def schema_document():
    return read_json(Path(__file__).resolve().parents[1] / 'contracts/v1.schema.json')


def schema_errors(value, kind):
    from jsonschema import Draft202012Validator
    schema = {'$schema': schema_document()['$schema'], '$defs': schema_document()['$defs'],
              '$ref': '#/$defs/' + kind}
    errors = Draft202012Validator(schema).iter_errors(value)
    return ['SCHEMA_' + kind + ':' + '/'.join(str(p) for p in error.absolute_path) + ':' + error.message
            for error in errors]


def content_id(value, field):
    copy = {key: val for key, val in value.items() if key != field}
    return fingerprint(copy)


def bundle_id(bundle):
    copy = {key: val for key, val in bundle.items() if key != 'bundle_id'}
    # Root location is a machine mapping, not input semantics. Root order and
    # file order are retained; moving identical files alone keeps the identity.
    copy['roots'] = [{k: v for k, v in root.items() if k != 'path'} for root in bundle['roots']]
    if 'runtime_evidence' in bundle:
        copy['runtime_evidence'] = {k:v for k,v in bundle['runtime_evidence'].items() if k != 'record_file'}
    return fingerprint(copy)


def build_id(prediction):
    return content_id(prediction, 'build_id')


def resolve_file(bundle, item):
    roots = {entry['id']: Path(entry['path']).resolve() for entry in bundle['roots']}
    if item['root'] not in roots:
        raise ContractError('FILE_ROOT_UNKNOWN')
    root = roots[item['root']]
    target = (root / item['path']).resolve()
    if not target.is_relative_to(root):
        raise ContractError('FILE_OUTSIDE_DECLARED_ROOT')
    return target


def check_bundle(bundle, check_disk=True):
    errors = schema_errors(bundle, 'InputBundle')
    if errors:
        return errors
    try:
        if bundle['schema_version'] != SCHEMA:
            errors.append('BUNDLE_SCHEMA')
        if bundle['bundle_id'] != bundle_id(bundle):
            errors.append('BUNDLE_ID_MISMATCH')
        if bundle['scope'] != 'NATIVE_REFERENCE':
            errors.append('BUNDLE_NOT_NATIVE')
        if not bundle['files']:
            errors.append('BUNDLE_FILES_EMPTY')
        if len({r['id'] for r in bundle['roots']}) != len(bundle['roots']):
            errors.append('ROOT_ID_DUPLICATE')
        keys = [(x['root'], x['path']) for x in bundle['files']]
        if len(set(keys)) != len(keys):
            errors.append('BUNDLE_FILE_DUPLICATE')
        env = bundle['environment']
        if not vector(env['resolution_px'], 2) or min(env['resolution_px']) <= 0:
            errors.append('RESOLUTION_INVALID')
        if not number(env['ui_scale']) or env['ui_scale'] <= 0:
            errors.append('UI_SCALE_INVALID')
        if not bundle['state']['scenario_id'] or not bundle['state']['window']:
            errors.append('STATE_IDENTITY_MISSING')
        if bundle['dependencies']['status'] not in ('COMPLETE', 'DECLARED_PARTIAL', 'UNKNOWN'):
            errors.append('DEPENDENCY_STATUS_INVALID')
        if bundle['dependencies']['status'] == 'COMPLETE' and bundle['dependencies']['unresolved']:
            errors.append('COMPLETE_DEPENDENCIES_HAVE_UNRESOLVED_ITEMS')
        order = bundle['load_order']
        if set(order['declared_roots']) != {r['id'] for r in bundle['roots']}:
            errors.append('LOAD_ORDER_ROOT_SET_MISMATCH')
        if order['status'] == 'VERIFIED' and order['effective_override_status'] != 'VERIFIED':
            errors.append('VERIFIED_LOAD_ORDER_WITHOUT_OVERRIDE_VERIFICATION')
        recorded = bundle['game_identity'].get('status') == 'RECORDED_CAPTURE_VERIFIED' or order['status'] == 'VERIFIED_FOR_DECLARED_FILES'
        if recorded and not bundle.get('runtime_evidence'):
            errors.append('RECORDED_RUNTIME_WITHOUT_EVIDENCE_BINDING')
        if bundle.get('runtime_evidence') and check_disk:
            from adapters.runtime import validate_runtime_binding
            validate_runtime_binding(bundle)
        for item in bundle['files']:
            if not isinstance(item['sha256'], str) or len(item['sha256']) != 64:
                errors.append('SOURCE_HASH_INVALID')
                continue
            target = resolve_file(bundle, item)
            if Path(item['path']).is_absolute() or '..' in Path(item['path']).parts:
                errors.append('FILE_PATH_MUST_BE_RELATIVE_AND_NORMALIZED')
            if check_disk and (not target.is_file() or digest(target) != item['sha256']):
                errors.append('SOURCE_MISSING_OR_CHANGED:' + item['path'])
            elif check_disk and target.stat().st_size != item['size']:
                errors.append('SOURCE_SIZE_MISMATCH:' + item['path'])
    except (KeyError, TypeError, ValueError, OSError) as exc:
        errors.append('BUNDLE_MALFORMED:' + str(exc))
    return errors


def identity(bundle, registry):
    return {'bundle_id': bundle['bundle_id'], 'registry_id': registry['registry_id'],
            'scenario_id': bundle['state']['scenario_id'], 'window': bundle['state']['window'],
            'state_id': fingerprint(bundle['state'])}


def validate_registry(registry):
    structural = schema_errors(registry, 'TargetRegistry')
    if structural:
        raise ContractError(';'.join(structural))
    if registry.get('schema_version') != SCHEMA:
        raise ContractError('REGISTRY_SCHEMA')
    if registry.get('registry_id') != content_id(registry, 'registry_id'):
        raise ContractError('REGISTRY_ID_MISMATCH')
    targets = registry.get('targets', [])
    if not targets or not any(t.get('required') is True for t in targets):
        raise ContractError('REQUIRED_TARGETS_EMPTY')
    ids = [t['id'] for t in targets]
    if len(ids) != len(set(ids)):
        raise ContractError('TARGET_ID_DUPLICATE')
    if registry.get('box_semantics') not in (None, 'EXPLICIT_RECT_KIND_V1'):
        raise ContractError('BOX_SEMANTICS_UNKNOWN')
    for target in targets:
        if not target['id'] or type(target['required']) is not bool:
            raise ContractError('TARGET_DEFINITION_INVALID')
        if not number(target['tolerance_ui']) or target['tolerance_ui'] < 0:
            raise ContractError('TOLERANCE_INVALID')
        if registry.get('box_semantics') == 'EXPLICIT_RECT_KIND_V1':
            if target.get('measurement_contract', {}).get('rect_kind') != target['box_kind']:
                raise ContractError('TARGET_RECT_KIND_UNDECLARED:' + target['id'])
    return {t['id']: t for t in targets}
