#!/usr/bin/env python3
"""Export independent native fixtures using a locally supplied game binary and PistonDecompiler."""
import argparse
import json
import math
import struct
import sys
from pathlib import Path

from generate import DEFAULT_SOURCE, bone_channels, compile_profiles
from matrices import identity, multiply, scale

NAME_ADDRESSES = {
    'pumpkin': 0x151dff100, 'carved_pumpkin': 0x151dff130, 'lit_pumpkin': 0x151dff160,
    'small_amethyst_bud': 0x151df9c90, 'medium_amethyst_bud': 0x151df9c60,
    'large_amethyst_bud': 0x151df9c30, 'snow_layer': 0x151dfd330,
}


def matrix_bytes(matrix):
    return struct.pack('<16f', *(matrix[row][column] for column in range(4) for row in range(4)))


def read_matrix(machine, address):
    values = struct.unpack('<16f', machine.uc.mem_read(address, 64))
    return [[values[column * 4 + row] for column in range(4)] for row in range(4)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--piston-native', type=Path, required=True, help='PistonDecompiler scripts/native directory')
    parser.add_argument('--output', type=Path, required=True, help='Directory for derived results only')
    args = parser.parse_args()
    source = json.loads(DEFAULT_SOURCE.read_text())
    sys.path.insert(0, str(args.piston_native.resolve()))
    from piston_native import NativeMachine, PEImage
    from unicorn import UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_XMM0

    image = PEImage(args.binary, source['binary_sha256'])
    float_bits = lambda value: struct.unpack('<I', struct.pack('<f', value))[0]

    def machine():
        native = NativeMachine(image)
        # Only CRT imports are supplied. The renderer and bone instructions execute unchanged.
        for iat, trig in [(0x14f104488, math.cos), (0x14f1045b8, math.sin)]:
            stub = native.allocate(0x20)
            native.write(stub, b'\xc3')
            native.qword(iat, stub)

            def boundary(uc, address, size, context, function=trig, owner=native):
                angle = struct.unpack('<f', struct.pack('<I', uc.reg_read(UC_X86_REG_XMM0) & 0xffffffff))[0]
                uc.reg_write(UC_X86_REG_XMM0, float_bits(function(angle)))
                owner.return_from_boundary()

            native.uc.hook_add(UC_HOOK_CODE, boundary, begin=stub, end=stub)
        return native

    def reference(native):
        dirty, ref, matrix = native.allocate(0x60), native.allocate(0x20), native.allocate(64)
        native.qword(ref, dirty)
        native.qword(ref + 8, matrix)
        native.write(matrix, matrix_bytes(identity()))
        return dirty, ref, matrix

    def slot_transform(native, ref, sprite, in_hand, block=0, shape=0):
        owner, item, render, control = [native.allocate(size) for size in (0x400, 0x30, 0x300, 8)]
        native.qword(item + 8, control)
        native.qword(control, owner)
        native.write(render + 0x280, struct.pack('<f', 1))
        native.write(render + 0x2a8, bytes([sprite]))
        native.call(0x1447bcb70, owner, ref, item, int(in_hand),
                    extra=[block, shape, render, float_bits(1), 0], instruction_limit=10000)

    fixtures, bones = [], []
    for profile, operations, expected in compile_profiles(source):
        native = machine()
        dirty, ref, matrix = reference(native)
        name = profile['name']
        if name == 'ordinary_sprite_head_equivalent':
            frame = native.allocate(0x200)
            native.qword(frame + 0x78, dirty)
            native.qword(frame + 0x80, matrix)
            native.hook_return(0x14558583f)
            native.call(0x14558577d, matrix, registers={'RBP': frame}, instruction_limit=10000)
            slot_transform(native, ref, True, True)
            measured = multiply(read_matrix(native, matrix), scale(16))
        else:
            shape = int(name.removeprefix('block_shape_')) if name.startswith('block_shape_') else 0
            if name not in NAME_ADDRESSES and not name.startswith('block_shape_') and name != 'button_flag_block_path':
                raise ValueError(f'No native probe boundary defined for {name}')
            block = native.allocate(0x200)
            for address in NAME_ADDRESSES.values():
                native.qword(address, address)
            native.qword(block + 0xe0, NAME_ADDRESSES.get(name, 1))
            native.write(block + 0x131, bytes([name == 'button_flag_block_path']))
            native.call(0x145589dc0, ref, block, shape, 1, instruction_limit=10000)
            slot_transform(native, ref, False, True, block, shape)
            measured = read_matrix(native, matrix)
        fixtures.append({'profile': profile['id'], 'matrix': measured})

        native = machine()
        bone, offset, matrix = native.allocate(0x200), native.allocate(16), native.allocate(64)
        native.write(matrix, matrix_bytes(identity()))
        for operation in operations:
            channels = bone_channels(operation)
            native.write(bone, bytes(0x200))
            native.write(bone + 0x78, struct.pack('<9f', *channels['position'], *channels['rotation'], *channels['scale']))
            native.call(0x141bc3d20, bone, offset, matrix, instruction_limit=10000)
        actual = read_matrix(native, matrix)
        for axis in range(3):
            actual[axis][3] /= 16
        error = max(abs(actual[i][j] - expected[i][j]) for i in range(4) for j in range(4))
        if error >= 1e-5:
            raise ValueError(f'Native correction failed for profile {profile["id"]}: {error}')
        bones.append({'profile': profile['id'], 'maximum_matrix_error': error})

    args.output.mkdir(parents=True, exist_ok=True)
    report = {'bedrock_version': source['bedrock_version'], 'binary_sha256': source['binary_sha256'],
              'method': 'Native bone matrix execution with supplied animation-position storage, zero ModelPart offset, identity initial parent and false rotation-relative flag. Geometry loading, animation parsing and rendering are outside this check.',
              'cases': bones, 'in_game_verified': False}
    for filename, result in [('native-fixtures.json', {'bedrock_version': source['bedrock_version'], 'fixtures': fixtures}),
                             ('native-bone-verification.json', report)]:
        (args.output / filename).write_text(json.dumps(result, indent=4) + '\n')
    print(f'PASS: {len(fixtures)} native renderer fixtures and {len(bones)} correction chains')


if __name__ == '__main__':
    main()
