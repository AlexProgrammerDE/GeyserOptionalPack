import com.google.gson.JsonParser;
import org.cloudburstmc.mojava.MoJava;
import org.cloudburstmc.mojava.compiler.MoScript;
import org.cloudburstmc.mojava.runtime.MoRuntime;

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
            for (String key : new String[]{"lx", "ly", "lz", "lw", "rx", "ry", "rz", "rw"}) {
                if (!Double.isFinite(test.get(key))) throw new AssertionError(key + " is not finite");
            }
            System.out.println("PASS " + file + ": interpolation, interruption, antipodal rotation, delay, zero duration and profile selection");
        }
    }
}
