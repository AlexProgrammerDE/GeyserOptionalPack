import com.google.gson.JsonParser;
import org.cloudburstmc.mojava.MoJava;
import org.cloudburstmc.mojava.compiler.MoScript;
import org.cloudburstmc.mojava.runtime.MoRuntime;
import org.joml.Matrix4f;
import org.joml.Quaternionf;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

/** Executes the generated scripts in MoJava rather than reimplementing their interpolation. */
public final class InterpolationTest {
    private final Map<String, Double> properties = new HashMap<>();
    private final MoRuntime runtime = MoJava.createRuntime();
    private final MoScript initialize;
    private final MoScript preAnimation;
    private double delta;
    private boolean attachable;
    private String item = "minecraft:apple";

    InterpolationTest(Path entity) throws Exception {
        var scripts = JsonParser.parseString(Files.readString(entity)).getAsJsonObject()
            .getAsJsonObject("minecraft:client_entity").getAsJsonObject("description").getAsJsonObject("scripts");
        initialize = runtime.compile(MoJava.parse(join(scripts.getAsJsonArray("initialize"))));
        preAnimation = runtime.compile(MoJava.parse(join(scripts.getAsJsonArray("pre_animation"))));
        var query = runtime.getEnvironment().query;
        query.addDoubleFunction("property", params -> properties.getOrDefault(params.getString(0), 0d));
        query.addDoubleFunction("delta_time", params -> delta);
        query.addDoubleFunction("equipped_item_is_attachable", params -> attachable ? 1 : 0);
        query.addDoubleFunction("is_item_name_any", params -> {
            for (int i = 2; i < params.getParams().size(); i++) {
                if (item.equals(params.getString(i))) return 1;
            }
            return 0;
        });
        for (String key : new String[]{"sx", "sy", "sz", "lw", "rw"}) set(key, 1);
        runtime.executeDouble(initialize);
    }

    private static String join(com.google.gson.JsonArray statements) {
        var result = new StringBuilder();
        statements.forEach(s -> result.append(s.getAsString()).append('\n'));
        return result.toString();
    }

    private void set(String key, double value) { properties.put("geyser:" + key, value); }
    private double get(String key) { return runtime.execute(MoJava.parse("return v." + key + ";")).asDouble(); }
    private void frame(double seconds) { delta = seconds; runtime.executeDouble(preAnimation); }
    private void zRotation(double degrees) {
        set("lz", Math.sin(Math.toRadians(degrees / 2)));
        set("lw", Math.cos(Math.toRadians(degrees / 2)));
    }
    private void leftQuaternion(Quaternionf quaternion) {
        set("lx", quaternion.x); set("ly", quaternion.y); set("lz", quaternion.z); set("lw", quaternion.w);
    }

    private void rotationBasis(Quaternionf quaternion) {
        var actual = new Matrix4f().rotationZ((float) Math.toRadians(get("lez")))
            .rotateY((float) Math.toRadians(get("ley")))
            .rotateX((float) Math.toRadians(get("lex")))
            .scale((float) get("lqs"));
        var expected = new Matrix4f().rotation(quaternion);
        for (int column = 0; column < 4; column++) {
            for (int row = 0; row < 4; row++) {
                if (Math.abs(expected.get(column, row) - actual.get(column, row)) > 1e-4) {
                    throw new AssertionError("Quaternion basis mismatch at " + column + "," + row);
                }
            }
        }
    }

    private static void near(double expected, double actual) {
        if (!Double.isFinite(actual) || Math.abs(expected - actual) > 1e-5) {
            throw new AssertionError("Expected " + expected + " but got " + actual);
        }
    }

    public static void main(String[] args) throws Exception {
        for (String file : args) {
            var test = new InterpolationTest(Path.of(file));
            test.set("tx", 2); test.set("sy", 0); test.set("revision", 1);
            test.frame(0);
            near(2, test.get("tx")); near(0, test.get("sy")); near(1, test.get("render_profile"));
            test.item = "minecraft:unknown"; test.frame(0); near(0, test.get("render_profile"));
            test.item = "minecraft:apple"; test.attachable = true; test.frame(0); near(0, test.get("render_profile"));
            test.set("render_profile", 3); test.frame(0); near(3, test.get("render_profile"));

            test.set("duration", 1); test.set("revision", 2); test.zRotation(170);
            test.frame(.5); near(85, test.get("lez"));
            // Interrupt halfway through, then cross the +/-180 degree boundary by the shortest path.
            test.set("revision", 3); test.zRotation(-170); test.frame(0); near(85, test.get("lez"));
            test.frame(.5); near(137.5, test.get("lez"));
            test.frame(.5); near(-170, test.get("lez"));
            // Antipodal quaternion representations must keep the same orientation.
            test.set("revision", 4);
            test.set("lz", -test.properties.get("geyser:lz"));
            test.set("lw", -test.properties.get("geyser:lw"));
            test.frame(.5); near(-170, test.get("lez"));
            test.frame(.5); near(-170, test.get("lez"));

            test.set("delay", 4); test.set("revision", 5); test.set("tx", 10);
            test.frame(.1); near(2, test.get("tx"));
            test.frame(.1); near(2, test.get("tx"));
            test.frame(.5); near(6, test.get("tx"));
            // A zero-duration update with negative delay takes effect immediately.
            test.set("duration", 0); test.set("delay", -1); test.set("revision", 6); test.set("tx", -8);
            test.frame(0); near(-8, test.get("tx"));
            // Exact gimbal lock must still produce the equivalent matrix basis.
            test.set("revision", 7);
            test.set("lx", .5); test.set("ly", .5); test.set("lz", -.5); test.set("lw", .5);
            test.frame(0);
            near(0, test.get("lex")); near(90, test.get("ley")); near(-90, test.get("lez"));
            // Nearly identical rotations use the guarded interpolation branch.
            test.set("revision", 8); test.set("duration", 1); test.set("lw", .50000001);
            test.frame(.5);
            near(1, Math.sqrt(test.get("lx") * test.get("lx") + test.get("ly") * test.get("ly") + test.get("lz") * test.get("lz") + test.get("lw") * test.get("lw")));
            for (String key : new String[]{"lx", "ly", "lz", "lw", "rx", "ry", "rz", "rw"}) {
                if (!Double.isFinite(test.get(key))) throw new AssertionError(key + " is not finite");
            }
            // JOML's matrix retains quaternion magnitude instead of normalizing it away.
            var source = new Quaternionf(1, 2, 3, 4);
            var target = new Quaternionf(2, -4, 1, 1);
            test.set("duration", 0); test.set("delay", 0); test.set("revision", 9);
            test.leftQuaternion(source); test.frame(0); test.rotationBasis(source);
            test.set("duration", 1); test.set("revision", 10); test.leftQuaternion(target);
            test.frame(0); test.frame(.5);
            test.rotationBasis(new Quaternionf(source).slerp(target, .5f));
            near(13.5, test.get("lqs"));
            // Zero quaternions collapse the basis, including when reached through interpolation.
            var identity = new Quaternionf();
            var zero = new Quaternionf(0, 0, 0, 0);
            test.set("duration", 0); test.set("revision", 11); test.leftQuaternion(identity); test.frame(0);
            test.set("duration", 1); test.set("revision", 12); test.leftQuaternion(zero);
            test.frame(0); test.frame(.5); test.rotationBasis(new Quaternionf(identity).slerp(zero, .5f));
            near(.5, test.get("lqs"));
            test.set("duration", 0); test.set("revision", 13); test.frame(0); test.rotationBasis(zero);
            near(0, test.get("lqs")); near(0, test.get("lex")); near(0, test.get("ley")); near(0, test.get("lez"));
            // Small non-unit quaternions use angular interpolation with an antipodal target.
            source = new Quaternionf(.2f, -.3f, .4f, .1f);
            target = new Quaternionf(-.1f, .25f, -.3f, .2f);
            test.set("duration", 0); test.set("revision", 14); test.leftQuaternion(source); test.frame(0);
            test.set("duration", 1); test.set("revision", 15); test.leftQuaternion(target); test.frame(0);
            test.frame(.25); test.rotationBasis(new Quaternionf(source).slerp(target, .25f));
            test.frame(.25); test.rotationBasis(new Quaternionf(source).slerp(target, .5f));
            // An interruption must retain the current raw quaternion, including its magnitude.
            var intermediate = new Quaternionf(source).slerp(target, .5f);
            var next = new Quaternionf(.7f, .1f, -.2f, .3f);
            test.set("revision", 16); test.leftQuaternion(next); test.frame(0); test.frame(.5);
            test.rotationBasis(intermediate.slerp(next, .5f));
            System.out.println("PASS " + file + ": interpolation, interruption, antipodal rotation, gimbal lock, delay, zero duration, profile selection and JOML quaternion magnitude");
        }
    }
}
