"""Bind retained native-capture evidence to a declared prediction file set.

This checks identity and the scope of recorded manual review. It does not read
engine memory, infer a currently running version, or prove dependency closure.
"""
from pathlib import Path
import re

from core.contracts import ContractError, digest, read_json

SCOPE = 'RECORDED_NATIVE_CAPTURE_DECLARED_FILES'
ROLES = {'binary', 'preflight', 'version_frame', 'native_frame',
         'fixture', 'capture_receipt', 'source_audit'}


def require(value, code):
    if not value:
        raise ContractError(code)


def inspect_record(bundle, record_file, expected_sha256=None):
    path = Path(record_file).resolve()
    require(path.is_file(), 'RUNTIME_RECORD_MISSING')
    record_sha = digest(path)
    require(expected_sha256 is None or record_sha == expected_sha256, 'RUNTIME_RECORD_HASH_MISMATCH')
    record = read_json(path)
    require(record.get('schema_version') == '1.0' and record.get('scope') == SCOPE, 'RUNTIME_RECORD_SCOPE')
    require(isinstance(record.get('game_version'), str) and record['game_version'].strip(), 'RUNTIME_VERSION_MISSING')
    require(isinstance(record.get('reviewer'), str) and record['reviewer'].strip(), 'RUNTIME_REVIEWER_MISSING')
    review = record.get('manual_review', {})
    require(all(review.get(k) is True for k in ('version_frame_identified', 'native_window_identified',
                                               'declared_file_overrides_reviewed')), 'RUNTIME_MANUAL_REVIEW_MISSING')
    refs = record.get('references', {})
    require(ROLES <= set(refs), 'RUNTIME_REFERENCE_ROLES_MISSING')
    for role, ref in refs.items():
        require(isinstance(ref, dict) and isinstance(ref.get('file'), str), 'RUNTIME_REFERENCE_INVALID:' + role)
        require(re.fullmatch('[0-9a-f]{64}', str(ref.get('sha256', ''))) is not None,
                'RUNTIME_REFERENCE_HASH_INVALID:' + role)
        source = Path(ref['file'])
        require(source.is_file() and digest(source) == ref['sha256'], 'RUNTIME_REFERENCE_CHANGED:' + role)
    fixture = read_json(refs['fixture']['file'])
    receipt = read_json(refs['capture_receipt']['file'])
    audit = read_json(refs['source_audit']['file'])
    preflight = read_json(refs['preflight']['file'])
    require(fixture.get('state_origin') == 'OBSERVED' and bundle['state']['state_origin'] == 'OBSERVED',
            'RUNTIME_STATE_NOT_OBSERVED')
    for key in ('scenario_id', 'window', 'tab', 'scroll', 'animation'):
        require(bundle['state'][key] == fixture[key], 'RUNTIME_STATE_MISMATCH:' + key)
    require(receipt.get('window') == fixture['window'] and receipt.get('state') == fixture['tab'],
            'RUNTIME_CAPTURE_STATE_MISMATCH')
    for key in ('resolution_px', 'ui_scale', 'locale'):
        require(bundle['environment'][key] == fixture['planned_environment'][key] == record['environment'][key],
                'RUNTIME_ENVIRONMENT_MISMATCH:' + key)
    # Extra modeled assumptions remain distinguishable from observed bindings.
    observed = dict(fixture['fixture_bindings'])
    for claim in record.get('additional_binding_claims', []):
        require(claim.get('basis') == 'VANILLA_BRANCH_AND_RECORDED_VISIBLE_STATE'
                and claim.get('evidence_roles') and set(claim['evidence_roles']) <= set(refs),
                'RUNTIME_BINDING_CLAIM_UNSUPPORTED')
        require(claim['key'] not in observed or observed[claim['key']] == claim['value'],
                'RUNTIME_BINDING_CLAIM_CONFLICT')
        observed[claim['key']] = claim['value']
    for key, value in observed.items():
        require(bundle['state']['fixture_bindings'].get(key, object()) == value, 'RUNTIME_BINDING_MISMATCH:' + key)
    require(receipt.get('sha256', '').lower() == refs['native_frame']['sha256'], 'RUNTIME_CAPTURE_FRAME_MISMATCH')
    require(receipt.get('fixture_sha256', '').lower() == refs['fixture']['sha256'], 'RUNTIME_CAPTURE_FIXTURE_MISMATCH')
    require(preflight.get('game_exe_sha256', '').lower() == refs['binary']['sha256'], 'RUNTIME_BINARY_MISMATCH')
    from PIL import Image
    for role in ('native_frame', 'version_frame'):
        with Image.open(refs[role]['file']) as im:
            require(im.format == 'PNG', 'RUNTIME_FRAME_NOT_PNG:' + role)
            if role == 'native_frame':
                require(list(im.size) == bundle['environment']['resolution_px'] == receipt.get('source_png_size'),
                        'RUNTIME_CAPTURE_DIMENSION_MISMATCH')
            im.verify()
    require(audit.get('status') == 'NO_MOD_MOUNTS_AND_NO_AUDITED_RESOURCE_COLLISIONS', 'RUNTIME_AUDIT_NOT_CLEAR')
    require(audit.get('dlc_load', {}).get('enabled_mods') == [] and audit.get('collisions') == [],
            'RUNTIME_AUDIT_MODS_OR_COLLISIONS')
    inventory = audit.get('checked_files', [])
    require(len({r['path'] for r in inventory}) == len(inventory), 'RUNTIME_AUDIT_DUPLICATE_FILE')
    audited = {r['path']: r for r in inventory}
    require(len(bundle['roots']) == 1 and bundle['roots'][0]['id'] == 'vanilla'
            and bundle['roots'][0]['role'] == 'vanilla', 'RUNTIME_ONLY_NATIVE_ROOT_SUPPORTED')
    for item in bundle['files']:
        row = audited.get(item['path'])
        require(item['root'] == 'vanilla' and row is not None, 'RUNTIME_FILE_NOT_AUDITED:' + item['path'])
        require(row['sha256'].lower() == item['sha256'] and row['size'] == item['size'],
                'RUNTIME_AUDITED_SOURCE_MISMATCH:' + item['path'])
    return {'record_sha256': record_sha, 'version': record['game_version'],
            'native_frame_sha256': refs['native_frame']['sha256'], 'covered_files': len(bundle['files']),
            'reviewer': record['reviewer'], 'scope': SCOPE,
            'notice': 'Recorded capture and manual source review only; not current-process or complete-engine proof.'}


def apply_runtime_evidence(bundle, record_file):
    proof = inspect_record(bundle, record_file)
    bundle['game_identity'] = {'status': 'RECORDED_CAPTURE_VERIFIED', 'version': proof['version'],
                               'basis': 'HASH_BOUND_RETAINED_CAPTURE_AND_MANUAL_VERSION_REVIEW'}
    bundle['load_order'].update(status='VERIFIED_FOR_DECLARED_FILES',
        effective_override_status='VERIFIED_FOR_DECLARED_FILES', scope='BUNDLE_FILE_SET_ONLY')
    bundle['runtime_evidence'] = dict(proof, record_file=str(Path(record_file).resolve()))
    return proof


def validate_runtime_binding(bundle):
    evidence = bundle.get('runtime_evidence')
    require(isinstance(evidence, dict), 'RUNTIME_BINDING_RECORD_MISSING')
    proof = inspect_record(bundle, evidence['record_file'], evidence['record_sha256'])
    require(all(evidence.get(k) == v for k,v in proof.items()), 'RUNTIME_BINDING_SUMMARY_MISMATCH')
    require(bundle['game_identity'].get('status') == 'RECORDED_CAPTURE_VERIFIED'
            and bundle['game_identity'].get('version') == proof['version'], 'RUNTIME_BOUND_VERSION_MISMATCH')
    require(bundle['load_order'].get('status') == 'VERIFIED_FOR_DECLARED_FILES'
            and bundle['load_order'].get('effective_override_status') == 'VERIFIED_FOR_DECLARED_FILES'
            and bundle['load_order'].get('scope') == 'BUNDLE_FILE_SET_ONLY', 'RUNTIME_BOUND_LOAD_SCOPE_MISMATCH')
    return proof
