// Offline contract tests: compile only the task client into a unique OS temp directory.
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const buildDir = await mkdtemp(join(tmpdir(), 'metricsleuth-task-client-'))
let exitCode = 1
try {
  const compiled = spawnSync(process.execPath, [
    join(frontend, 'node_modules/typescript/bin/tsc'),
    '--ignoreConfig',
    '--target', 'ES2023', '--module', 'ESNext', '--moduleResolution', 'bundler',
    '--lib', 'ES2023,DOM', '--strict', '--skipLibCheck', '--rootDir', 'src', '--outDir', buildDir,
    'src/tasks/contracts.ts', 'src/tasks/client.ts',
  ], { cwd: frontend, stdio: 'inherit' })
  if (compiled.error) throw compiled.error
  if (compiled.status !== 0) {
    exitCode = compiled.status ?? 1
  } else {
    const tested = spawnSync(process.execPath, ['--test', 'tests/task-client.test.mjs'], {
      cwd: frontend, stdio: 'inherit',
      env: { ...process.env, METRICSLEUTH_TASK_CLIENT_BUILD_DIR: buildDir },
    })
    if (tested.error) throw tested.error
    exitCode = tested.status ?? 1
  }
} finally {
  // Delete only the exact unique directory allocated above, never a project/user path.
  const expectedParent = resolve(tmpdir())
  if (resolve(buildDir).startsWith(expectedParent + (process.platform === 'win32' ? '\\' : '/'))) {
    await rm(buildDir, { recursive: true, force: true })
  }
}
process.exitCode = exitCode
