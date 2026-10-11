// Offline contract tests compile only the metric client into a unique OS temp directory.
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const frontend = fileURLToPath(new URL("../", import.meta.url));
const buildDir = await mkdtemp(join(tmpdir(), "metricsleuth-metric-client-"));
let exitCode = 1;
try {
  const compiled = spawnSync(process.execPath, [
    join(frontend, "node_modules/typescript/bin/tsc"),
    "--ignoreConfig",
    "--target", "ES2023", "--module", "ESNext", "--moduleResolution", "bundler",
    "--lib", "ES2023,DOM", "--strict", "--skipLibCheck", "--rootDir", "src", "--outDir", buildDir,
    "src/metrics/contracts.ts", "src/metrics/client.ts",
  ], { cwd: frontend, stdio: "inherit" });
  if (compiled.error) throw compiled.error;
  if (compiled.status !== 0) {
    exitCode = compiled.status ?? 1;
  } else {
    const tested = spawnSync(process.execPath, ["--test", "tests/metric-client.test.mjs"], {
      cwd: frontend,
      stdio: "inherit",
      env: { ...process.env, METRICSLEUTH_METRIC_CLIENT_BUILD_DIR: buildDir },
    });
    if (tested.error) throw tested.error;
    exitCode = tested.status ?? 1;
  }
} finally {
  const expectedParent = resolve(tmpdir());
  if (resolve(buildDir).startsWith(expectedParent + (process.platform === "win32" ? "\\" : "/"))) {
    await rm(buildDir, { recursive: true, force: true });
  }
}
process.exitCode = exitCode;
