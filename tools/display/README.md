# Display transform generator

This draft targets Bedrock **1.26.51.1** and Kastle's `feature/display-entities` branch.
Use it with the matching Geyser display implementation. Neither draft has human in-game validation yet.

The generator replaces the debug transform with versioned correction profiles. Ordinary sprites use the measured head-slot reference transform. Block profiles cancel the measured hand transform and retain the block mesh's own origin. These are different reference frames, not a claim of complete Java display-model parity.

## Generate and test

Python 3.10 or later is enough to generate the pack:

```sh
python3 tools/display/generate.py
python3 tools/display/generate.py --check
python3 -m unittest discover -s tools/display -v
```

The script tests require Java 17 or later and `curl`:

```sh
python3 tools/display/test_molang.py
```

That command downloads checksum-pinned MoJava, ASM and Gson test dependencies into a temporary directory. It executes the generated scripts for both entity types. It checks interrupted interpolation, shortest-path quaternion interpolation, antipodal rotations, delays, zero duration and profile selection. No library is required by the pack at runtime.

`--require-complete` fails while the manifest lists unresolved renderer paths. The checked-in manifest deliberately fails that gate.

## Correction profiles

Edit `profiles-1.26.51.json`, then run the generator. Each profile has a stable positive ID, item identifiers, renderer factors, target factors and evidence. IDs must be unique and no greater than 1000000.

Factors use block units and degrees. Matrices use column vectors, with factors applied from right to left. Supported operations are `translate`, `scale`, `rotate_x`, `rotate_y` and `rotate_z`.

For renderer transform `F` and target transform `D`, the generated parent correction is:

```text
C = D * inverse(F)
C * F = D
```

The generator preserves each factor in a separate bone. This also represents corrections with shear, reflections and non-uniform scale. Source scales must be invertible. Target scales may include zero. The hierarchy uses zero pivots so geometry pivots cannot introduce another offset.

The ordinary-sprite profile normalizes the native pixel frame. Its correction restores the head-slot reference while retaining texture-size scaling. Its native measurements use renderer scale 1, vanilla definitions and the branch without authored JSON transforms.

Automatic selection uses an explicit item allowlist. An attachable skips automatic correction because its resource pack can supply another transform. Set `geyser:render_profile` to a generated ID to select a measured custom profile. Zero enables automatic selection. Unknown IDs and unlisted items retain native rendering without correction.

Profiles marked `automatic: false` are available through explicit selection. The button-flag block path and amethyst offsets have native matrix measurements, but their live item renderer routing remains unverified.

For Java item-display contexts, a profile can supply `context_targets`. Keys are strings from `"0"` to `"8"`: none, third-person left, third-person right, first-person left, first-person right, head, GUI, ground and fixed. Each value is a target factor list. The default `target` applies to contexts without an override. The manifest does not yet contain a complete set of Java model-context transforms.

## Geyser property contract

| Property | Meaning |
| --- | --- |
| `geyser:tx`, `ty`, `tz` | Translation in block units, already converted into the pack frame |
| `geyser:sx`, `sy`, `sz` | Independent scale axes, including zero and negative values |
| `geyser:lx`, `ly`, `lz`, `lw` | Normalized left quaternion in the pack frame |
| `geyser:rx`, `ry`, `rz`, `rw` | Normalized right quaternion in the pack frame |
| `geyser:revision` | Bounded revision counter for a batch of transform updates |
| `geyser:delay` | Interpolation delay in Java ticks |
| `geyser:duration` | Interpolation duration in seconds |
| `geyser:display_context` | Java item-display context, 0 through 8 |
| `geyser:render_profile` | Explicit correction ID, or zero for automatic selection |

The animation keeps `left rotation * scale * right rotation` separate. It interpolates each quaternion along the shortest path, then converts it into its own Z-Y-X bone chain. It snapshots the current pose when a new revision interrupts interpolation. A non-positive duration applies the target when the delay expires.

## Evidence and limits

`native-fixtures.json` records matrices obtained by executing the native renderer instructions. The generator tests compare its factors with those independent fixtures.

`native-bone-verification.json` records a second check: executing the native bone-transform routine for every generated correction factor. The probe supplies position, rotation and scale storage directly, a zero ModelPart offset and an identity initial parent. This checks the bone matrix math. It does not check geometry loading, animation parsing, attachable inheritance or camera rendering.

`coverage.json` is generated. It records profile IDs, matrices, automatic selection and unresolved cases. The source manifest records the binary checksum. No game binary or decompiled game code is included.

Remaining work includes hand-equipped definitions, maps, dedicated item renderers, arbitrary custom attachables, complete Java model contexts, billboards and live classification of unlisted items. The Geyser draft also needs position/rotation interpolation, brightness, view-range, shadow, display-bounds and glow handling. This draft does not implement those features.

Use the [Geyser test procedure](https://github.com/AlexProgrammerDE/Geyser/blob/feature/display-entities/docs/display-entities.md) for human validation. Record the client version, profile ID and active resource packs with each result.

Primary references:

- [Kastle's original geometry](https://github.com/Kas-tle/GeyserOptionalPack/blob/feature/display-entities/models/entity/display.geo.json)
- [Held-item research and matrix reference](https://gist.github.com/AlexProgrammerDE/6a08ba617179c3f9a21bd479d2c936a8)
- [Official Molang query reference](https://github.com/MicrosoftDocs/minecraft-creator/blob/main/creator/Reference/Content/MolangReference/Examples/MolangConcepts/QueryFunctions.md)
- [Bedrock geometry schemas](https://mojang.github.io/bedrock-samples/Schemas.html)
- [MoJava runtime](https://github.com/CloudburstMC/MoJava)
