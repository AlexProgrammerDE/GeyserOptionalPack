import copy
import json
import math
import unittest
import tempfile
import zipfile
from pathlib import Path

from generate import DEFAULT_SOURCE, ROOT, build_pack, bone_channels, compile_profiles, correction, factor, outputs
from matrices import compose, identity, multiply


class GeneratorTest(unittest.TestCase):
    def setUp(self):
        self.source = json.loads(DEFAULT_SOURCE.read_text())

    def assertMatrix(self, actual, expected, tolerance=1e-6):
        error = max(abs(actual[i][j] - expected[i][j]) for i in range(4) for j in range(4))
        self.assertLess(error, tolerance)

    def test_profiles_reproduce_independent_native_fixtures(self):
        fixtures = json.loads(DEFAULT_SOURCE.with_name('native-fixtures.json').read_text())['fixtures']
        profiles = {p['id']: p for p in self.source['profiles']}
        for fixture in fixtures:
            with self.subTest(profile=fixture['profile']):
                profile = profiles[fixture['profile']]
                renderer = compose(*(factor(op) for op in profile['renderer']))
                self.assertMatrix(renderer, fixture['matrix'])
                _, matrix = correction(profile['renderer'], profile['target'])
                self.assertMatrix(multiply(matrix, fixture['matrix']), compose(*(factor(op) for op in profile['target'])))

    def test_non_uniform_scale_reflections_and_shear_remain_exact(self):
        renderer = [{'rotate_y': 47}, {'scale': [-2, 3, .125]}, {'rotate_x': -39}, {'translate': [8, -3, .5]}]
        target = [{'translate': [-2, 5, 1]}, {'rotate_z': 71}, {'scale': [1, .4, 2]}]
        _, matrix = correction(renderer, target)
        self.assertMatrix(multiply(matrix, compose(*(factor(op) for op in renderer))), compose(*(factor(op) for op in target)))

    def test_zero_display_scale_is_valid_but_singular_renderer_is_not(self):
        _, matrix = correction([{'scale': [1, 2, 3]}], [{'scale': [0, -1, 0]}])
        self.assertMatrix(matrix, factor({'scale': [0, -.5, 0]}))
        with self.assertRaises(ValueError):
            correction([{'scale': [1, 0, 1]}], [])

    def test_invalid_numbers_identifiers_and_duplicate_profiles_fail(self):
        for operation in [{'rotate_x': math.nan}, {'scale': [1, math.inf, 1]}, {'translate': [True, 0, 0]}]:
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                correction([operation], [])
        for mutate in [lambda s: s['profiles'].append(s['profiles'][0]),
                       lambda s: s['profiles'][0].update(items=[]),
                       lambda s: s['profiles'][0].update(id=1000001),
                       lambda s: s['profiles'][0].update(items=["minecraft:apple'); v.foo=1;"])]:
            source = copy.deepcopy(self.source)
            mutate(source)
            with self.assertRaises(ValueError):
                compile_profiles(source)

    def test_bone_position_converts_model_pixels_to_native_upward_y(self):
        self.assertEqual([32, -48, -64], bone_channels({'translate': [2, 3, -4]})['position'])

    def test_generated_bone_chain_reproduces_each_correction(self):
        generated = outputs(self.source, ROOT)
        animations = generated[ROOT / 'animations/display.animation.json']['animations']
        for profile, _, expected in compile_profiles(self.source):
            channels = animations[f"animation.display.correction.{profile['id']}"]['bones']
            actual = identity()
            for bone in channels.values():
                x, y, z = bone['position']
                rotation = bone['rotation']
                matrix = compose(factor({'translate': [x / 16, -y / 16, z / 16]}),
                                 factor({'rotate_z': rotation[2]}), factor({'rotate_y': rotation[1]}),
                                 factor({'rotate_x': rotation[0]}), factor({'scale': bone['scale']}))
                actual = multiply(actual, matrix)
            self.assertMatrix(actual, expected)

    def test_display_hierarchy_keeps_rotations_on_opposite_sides_of_scale(self):
        generated = outputs(self.source, ROOT)
        geometry = generated[ROOT / 'models/entity/display.geo.json']['minecraft:geometry'][0]
        animation = generated[ROOT / 'animations/display.animation.json']['animations']['animation.display.transform']['bones']
        parents = {bone['name']: bone.get('parent') for bone in geometry['bones']}
        values = dict(zip(['tx', 'ty', 'tz', 'sx', 'sy', 'sz', 'lex', 'ley', 'lez', 'rex', 'rey', 'rez', 'lqs', 'rqs'],
                          [1, -2, 3, -2, .5, 3, 21, -44, 76, -33, 63, 14, 4, 9]))

        def channel(value):
            if not isinstance(value, str):
                return value
            parts = value.split(' * ')
            return values[parts[0].removeprefix('v.')] * (float(parts[1]) if len(parts) == 2 else 1)

        chain, name = [], 'rightitem'
        while name is not None:
            chain.append(name)
            name = parents[name]
        actual = identity()
        for name in reversed(chain):
            pose = animation.get(name, {})
            position = [channel(v) for v in pose.get('position', [0, 0, 0])]
            rotation = [channel(v) for v in pose.get('rotation', [0, 0, 0])]
            sizes = [channel(v) for v in pose.get('scale', [1, 1, 1])]
            actual = multiply(actual, compose(factor({'translate': [position[0] / 16, -position[1] / 16, position[2] / 16]}),
                              factor({'rotate_z': rotation[2]}), factor({'rotate_y': rotation[1]}),
                              factor({'rotate_x': rotation[0]}), factor({'scale': sizes})))
        expected = compose(factor({'translate': [1, 2, 3]}), factor({'rotate_z': 76}), factor({'rotate_y': -44}),
                           factor({'rotate_x': 21}), factor({'scale': [-72, 18, 108]}), factor({'rotate_z': 14}),
                           factor({'rotate_y': 63}), factor({'rotate_x': -33}))
        self.assertMatrix(actual, expected)

    def test_context_overrides_and_explicit_only_profiles_generate_valid_variants(self):
        source = copy.deepcopy(self.source)
        source['profiles'][0]['context_targets'] = {'6': [{'scale': [0, 1, 2]}]}
        generated = outputs(source, ROOT)
        animations = generated[ROOT / 'animations/display.animation.json']['animations']
        channels = animations['animation.display.correction.1.context.6']['bones']
        actual = identity()
        for bone in channels.values():
            x, y, z = bone['position']
            rotation = bone['rotation']
            actual = multiply(actual, compose(factor({'translate': [x / 16, -y / 16, z / 16]}),
                              factor({'rotate_z': rotation[2]}), factor({'rotate_y': rotation[1]}),
                              factor({'rotate_x': rotation[0]}), factor({'scale': bone['scale']})))
        renderer = compose(*(factor(op) for op in source['profiles'][0]['renderer']))
        self.assertMatrix(multiply(actual, renderer), factor({'scale': [0, 1, 2]}))

    def test_pack_build_is_deterministic_and_coexists_with_integrated_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'first.mcpack', Path(directory) / 'second.mcpack'
            build_pack(ROOT, first)
            build_pack(ROOT, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                self.assertNotEqual(manifest['header']['uuid'], json.loads((ROOT / 'manifest.json').read_text())['header']['uuid'])
                self.assertEqual(7, len(archive.namelist()))
                for name in ['animations/display.animation.json', 'entity/item_display.entity.json', 'entity/block_display.entity.json']:
                    self.assertEqual((ROOT / name).read_bytes(), archive.read(name))

    def test_checked_in_assets_are_deterministic_and_current(self):
        for path, content in outputs(self.source, ROOT).items():
            self.assertEqual(json.dumps(content, indent=4, allow_nan=False) + '\n', path.read_text(), path.name)


if __name__ == '__main__':
    unittest.main()
