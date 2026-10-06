import copy
import json
import math
import unittest

from generate import DEFAULT_SOURCE, ROOT, bone_channels, compile_profiles, correction, factor, outputs
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

    def test_checked_in_assets_are_deterministic_and_current(self):
        for path, content in outputs(self.source, ROOT).items():
            self.assertEqual(json.dumps(content, indent=4, allow_nan=False) + '\n', path.read_text(), path.name)


if __name__ == '__main__':
    unittest.main()
