import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  access,
  mkdtemp,
  mkdir,
  readFile,
  stat,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const cliPath = join(packageRoot, "bin", "create.js");

function runCreate(args, cwd) {
  return spawnSync(process.execPath, [cliPath, ...args], {
    cwd,
    encoding: "utf8",
  });
}

async function tempDir() {
  return mkdtemp(join(tmpdir(), "glasskit-create-"));
}

test("prints help", async () => {
  const result = runCreate(["--help"], await tempDir());

  assert.equal(result.status, 0);
  assert.match(result.stdout, /npm create @glasskit\.ai/);
  assert.equal(result.stderr, "");
});

test("prints package version", async () => {
  const packageJson = JSON.parse(
    await readFile(join(packageRoot, "package.json"), "utf8"),
  );
  const result = runCreate(["--version"], await tempDir());

  assert.equal(result.status, 0);
  assert.equal(result.stdout.trim(), packageJson.version);
  assert.equal(result.stderr, "");
});

test("creates the default Rokid starter project", async () => {
  const cwd = await tempDir();
  const result = runCreate([], cwd);
  const target = join(cwd, "rokid-starter");

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /GlassKit create is WIP/);
  await stat(join(target, "AGENTS.md"));
  await stat(join(target, ".gitignore"));
  await assert.rejects(access(join(target, "gitignore")), { code: "ENOENT" });
  await stat(join(target, "app", "src", "main", "AndroidManifest.xml"));
  await stat(join(target, "gradle", "wrapper", "gradle-wrapper.jar"));

  const gradlew = await stat(join(target, "gradlew"));
  assert.notEqual(gradlew.mode & 0o111, 0);
});

test("creates a custom target directory", async () => {
  const cwd = await tempDir();
  const result = runCreate(["my-rokid-app"], cwd);

  assert.equal(result.status, 0, result.stderr);
  await stat(join(cwd, "my-rokid-app", "settings.gradle.kts"));
});

test("refuses to overwrite a non-empty directory", async () => {
  const cwd = await tempDir();
  const target = join(cwd, "existing");
  await mkdir(target);
  await writeFile(join(target, "keep.txt"), "do not overwrite\n");

  const result = runCreate(["existing"], cwd);

  assert.equal(result.status, 1);
  assert.match(result.stderr, /Target directory is not empty/);
});
