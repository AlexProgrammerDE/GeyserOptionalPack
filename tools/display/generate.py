#!/usr/bin/env python3
"""Generate display corrections from explicit, versioned renderer factor chains."""
import argparse
import json
import math
from pathlib import Path

from matrices import compose, identity, inverse, multiply, rotate, translate

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = Path(__file__).with_name('profiles-1.26.51.json')


def vector(value, label):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f'{label} must contain three finite numbers')
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value):
        raise ValueError(f'{label} must contain three finite numbers')
    return value


def factor(operation):
    if len(operation) != 1:
        raise ValueError('Each factor must contain exactly one operation')
    kind, value = next(iter(operation.items()))
    if kind == 'translate':
        return translate(*vector(value, kind))
    if kind == 'scale':
        values = vector(value, kind)
        matrix = identity()
        for axis in range(3):
            matrix[axis][axis] = values[axis]
        return matrix
    if kind in ('rotate_x', 'rotate_y', 'rotate_z'):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Rotation must be finite')
        return rotate(kind[-1], value)
    raise ValueError(f'Unknown factor: {kind}')


def invert_factor(operation):
    factor(operation)
    kind, value = next(iter(operation.items()))
    if kind == 'scale':
        if any(abs(x) < 1e-12 for x in value):
            raise ValueError('Cannot correct a singular renderer scale')
        return {kind: [1 / x for x in value]}
    if kind == 'translate':
        return {kind: [-x for x in value]}
    return {kind: -value}


def correction(renderer, target):
    # Keep individual factors. A single TRS cannot represent every inverse with shear.
    operations = target + [invert_factor(op) for op in reversed(renderer)]
    actual = compose(*(factor(op) for op in operations))
    expected = multiply(compose(*(factor(op) for op in target)), inverse(compose(*(factor(op) for op in renderer))))
    if max(abs(actual[i][j] - expected[i][j]) for i in range(4) for j in range(4)) > 1e-7:
        raise ValueError('Correction factorization did not reproduce the matrix')
    return operations, actual


def bone_channels(operation):
    kind, value = next(iter(operation.items()))
    channels = {'position': [0, 0, 0], 'rotation': [0, 0, 0], 'scale': [1, 1, 1]}
    if kind == 'translate':
        channels['position'] = [16 * value[0], -16 * value[1], 16 * value[2]]
    elif kind == 'scale':
        channels['scale'] = value
    else:
        channels['rotation']['xyz'.index(kind[-1])] = value
    return channels


def compile_profiles(source):
    if source.get('bedrock_version') != '1.26.51.1':
        raise ValueError('This generator requires a 1.26.51.1 profile manifest')
    profiles = source['profiles']
    ids, names = set(), set()
    compiled = []
    for profile in profiles:
        profile_id = profile['id']
        if not isinstance(profile_id, int) or isinstance(profile_id, bool) or not 1 <= profile_id <= 1000000 or profile_id in ids:
            raise ValueError('Profile IDs must be unique positive integers')
        ids.add(profile_id)
        if not isinstance(profile.get('automatic', True), bool):
            raise ValueError('Automatic selection must be a boolean')
        if not profile.get('name') or not profile.get('evidence'):
            raise ValueError('Profiles need a name and source evidence')
        if not profile['items']:
            raise ValueError('A profile needs at least one item identifier')
        for name in profile['items']:
            if not isinstance(name, str) or ':' not in name or not all(c.isalnum() or c in ':_./-' for c in name) or name in names:
                raise ValueError(f'Duplicate or invalid item identifier: {name}')
            names.add(name)
        operations, matrix = correction(profile['renderer'], profile.get('target', []))
        for context, target in profile.get('context_targets', {}).items():
            if context not in [str(i) for i in range(9)]:
                raise ValueError('Display context must be a string integer from 0 to 8')
            correction(profile['renderer'], target)
        compiled.append((profile, operations, matrix))
    unsupported = source.get('unsupported', {})
    if names.intersection(unsupported):
        raise ValueError('An item cannot be supported and unsupported simultaneously')
    return sorted(compiled, key=lambda entry: entry[0]['id'])


def interpolation_scripts():
    channels = ['tx', 'ty', 'tz', 'sx', 'sy', 'sz', 'lx', 'ly', 'lz', 'lw', 'rx', 'ry', 'rz', 'rw']
    initialize = ["v.state = q.property('geyser:revision');", 'v.elapsed = 0;', 'v.blend = 1;']
    for key in channels:
        initialize += [f"v.{key} = q.property('geyser:{key}');", f'v.from_{key} = v.{key};']
    snapshot = ' '.join(f'v.from_{key} = v.{key};' for key in channels)
    pre = [f"q.property('geyser:revision') != v.state ? {{ {snapshot} v.elapsed = -q.property('geyser:delay') / 20; v.state = q.property('geyser:revision'); }};",
           'v.elapsed = v.elapsed + q.delta_time;',
           "v.blend = v.elapsed < 0 ? 0 : (q.property('geyser:duration') <= 0 ? 1 : math.clamp(v.elapsed / q.property('geyser:duration'), 0, 1));"]
    for key in channels[:6]:
        pre.append(f"v.{key} = math.lerp(v.from_{key}, q.property('geyser:{key}'), v.blend);")
    for side in ('l', 'r'):
        # Slerp the two rotations independently, including antipodal and nearly equal inputs.
        dot = ' + '.join(f"v.from_{side}{axis} * q.property('geyser:{side}{axis}')" for axis in 'xyzw')
        pre += [f'v.dot = math.clamp({dot}, -1, 1);',
                'v.sign = v.dot < 0 ? -1 : 1;',
                'v.angle = math.acos(math.abs(v.dot));',
                'v.denominator = math.sin(v.angle);',
                'v.a = v.denominator < 0.0001 ? 1 - v.blend : math.sin((1 - v.blend) * v.angle) / v.denominator;',
                'v.b = v.sign * (v.denominator < 0.0001 ? v.blend : math.sin(v.blend * v.angle) / v.denominator);']
        for axis in 'xyzw':
            pre.append(f"v.{side}{axis} = v.a * v.from_{side}{axis} + v.b * q.property('geyser:{side}{axis}');")
        pre.append(f"v.length = math.sqrt({' + '.join(f'v.{side}{a} * v.{side}{a}' for a in 'xyzw')});")
        for axis in 'xyzw':
            fallback = 1 if axis == 'w' else 0
            pre.append(f'v.{side}{axis} = v.length < 0.000001 ? {fallback} : v.{side}{axis} / v.length;')
        pre += [f'v.r20 = 2 * (v.{side}x * v.{side}z - v.{side}y * v.{side}w);',
                f'v.{side}ey = math.asin(math.clamp(-v.r20, -1, 1));',
                f'v.{side}ex = math.abs(v.r20) < 0.9999999 ? math.atan2(2 * (v.{side}y * v.{side}z + v.{side}x * v.{side}w), 1 - 2 * (v.{side}x * v.{side}x + v.{side}y * v.{side}y)) : 0;',
                f'v.{side}ez = math.abs(v.r20) < 0.9999999 ? math.atan2(2 * (v.{side}x * v.{side}y + v.{side}z * v.{side}w), 1 - 2 * (v.{side}y * v.{side}y + v.{side}z * v.{side}z)) : math.atan2(-2 * (v.{side}x * v.{side}y - v.{side}z * v.{side}w), 1 - 2 * (v.{side}x * v.{side}x + v.{side}z * v.{side}z));']
    return initialize, pre


def outputs(source, root):
    compiled = compile_profiles(source)
    count = max((len(ops) for _, ops, _ in compiled), default=0)
    for profile, _, _ in compiled:
        for target in profile.get('context_targets', {}).values():
            count = max(count, len(correction(profile['renderer'], target)[0]))
    if count > 64:
        raise ValueError('Renderer factor chains must contain at most 64 correction bones')
    bones = [{'name': 'geyser', 'pivot': [0, 0, 0]}]
    parent = 'geyser'
    for name in ['left_z', 'left_y', 'left_x', 'display_scale', 'right_z', 'right_y', 'right_x'] + [f'correction_{i}' for i in range(count)] + ['rightarm', 'rightitem']:
        bones.append({'name': name, 'parent': parent, 'pivot': [0, 0, 0]})
        parent = name
    geometry_path = root / 'models/entity/display.geo.json'
    geometry = json.loads(geometry_path.read_text())
    geometry['minecraft:geometry'][0]['bones'] = bones
    display = {'loop': True, 'bones': {'geyser': {'position': ['v.tx * 16', 'v.ty * 16', 'v.tz * 16']},
                                     'display_scale': {'scale': ['v.sx', 'v.sy', 'v.sz']}}}
    for side in ('left', 'right'):
        for axis, component in zip('xyz', 'xyz'):
            rotation = [0, 0, 0]
            rotation['xyz'.index(axis)] = f'v.{side[0]}e{component}'
            display['bones'][f'{side}_{axis}'] = {'rotation': rotation}
    animations = {'animation.display.transform': display}
    aliases = {'transform': 'animation.display.transform'}
    animate = ['transform']
    expressions = []
    report = {'bedrock_version': source['bedrock_version'], 'profiles': [], 'unsupported': source.get('unsupported', {}),
              'unknown_item_behavior': 'No correction. Native item rendering remains visible.', 'in_game_verified': False}
    for profile, operations, matrix in compiled:
        profile_id = profile['id']
        alias = f'correction_{profile_id}'
        name = f'animation.display.correction.{profile_id}'
        channels = {f'correction_{i}': bone_channels(op) for i, op in enumerate(operations)}
        # Write all slots so switching profiles cannot leave an old factor active.
        for i in range(len(operations), count):
            channels[f'correction_{i}'] = {'position': [0, 0, 0], 'rotation': [0, 0, 0], 'scale': [1, 1, 1]}
        animations[name] = {'loop': True, 'bones': channels}
        aliases[alias] = name
        contexts = profile.get('context_targets', {})
        exclusions = ''.join(f" && q.property('geyser:display_context') != {context}" for context in sorted(contexts))
        animate.append({alias: f'v.render_profile == {profile_id}' + exclusions})
        for context, target in sorted(contexts.items()):
            context_ops, _ = correction(profile['renderer'], target)
            context_channels = {f'correction_{i}': bone_channels(op) for i, op in enumerate(context_ops)}
            for i in range(len(context_ops), count):
                context_channels[f'correction_{i}'] = {'position': [0, 0, 0], 'rotation': [0, 0, 0], 'scale': [1, 1, 1]}
            context_alias = f'{alias}_context_{context}'
            context_name = f'{name}.context.{context}'
            aliases[context_alias] = context_name
            animations[context_name] = {'loop': True, 'bones': context_channels}
            animate.append({context_alias: f"v.render_profile == {profile_id} && q.property('geyser:display_context') == {context}"})
        items = ', '.join(f"'{item}'" for item in sorted(profile['items']))
        if profile.get('automatic', True):
            expressions.append(f"q.is_item_name_any('slot.weapon.mainhand', 0, {items}) ? {profile_id}")
        report['profiles'].append({'id': profile_id, 'name': profile['name'], 'items': sorted(profile['items']), 'automatic': profile.get('automatic', True),
                                   'correction_matrix': matrix, 'evidence': profile['evidence']})
    selection = ' : '.join(expressions + ['0'])
    initialize, pre = interpolation_scripts()
    # A pack-defined attachable has an independent transform. Explicit profile override is required.
    pre.append(f"v.render_profile = q.property('geyser:render_profile') > 0 ? q.property('geyser:render_profile') : (q.equipped_item_is_attachable('main_hand') ? 0 : ({selection}));")
    generated = {geometry_path: geometry,
                 root / 'animations/display.animation.json': {'format_version': '1.8.0', 'animations': animations},
                 root / 'tools/display/coverage.json': report}
    for entity in ('item', 'block'):
        path = root / f'entity/{entity}_display.entity.json'
        data = json.loads(path.read_text())
        description = data['minecraft:client_entity']['description']
        description['animations'] = aliases
        description['scripts'] = {'initialize': initialize, 'pre_animation': pre, 'animate': animate}
        generated[path] = data
    return generated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--require-complete', action='store_true', help='Reject profiles that still list unresolved rendering paths')
    args = parser.parse_args()
    source = json.loads(args.source.read_text())
    if args.require_complete and source.get('unsupported'):
        parser.error('Coverage is incomplete; provide renderer profiles for the unsupported entries')
    generated = outputs(source, ROOT)
    stale = []
    for path, data in generated.items():
        content = json.dumps(data, indent=4, allow_nan=False) + '\n'
        if args.check:
            if not path.exists() or path.read_text() != content:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if stale:
        parser.exit(1, 'Generated files differ: ' + ', '.join(stale) + '\n')


if __name__ == '__main__':
    main()
