#!/usr/bin/env node

import { access, chmod, copyFile, cp, mkdir, rm } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(packageRoot, "..");
const sourceTemplate = join(
  repoRoot,
  "skills",
  "glasskit",
  "assets",
  "rokid-hello-world",
);
const outputRoot = join(packageRoot, "dist", "template");
const outputTemplate = join(outputRoot, "rokid-hello-world");

try {
  await access(join(sourceTemplate, "settings.gradle.kts"));
} catch {
  console.error(`Missing starter template: ${sourceTemplate}`);
  process.exit(1);
}

await rm(outputTemplate, { recursive: true, force: true });
await mkdir(outputRoot, { recursive: true });
await cp(sourceTemplate, outputTemplate, { recursive: true });
await copyFile(join(outputTemplate, ".gitignore"), join(outputTemplate, "gitignore"));
await chmod(join(outputTemplate, "gradlew"), 0o755);

console.log(`Copied template to ${relative(packageRoot, outputTemplate)}`);
