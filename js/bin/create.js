#!/usr/bin/env node

import { accessSync, constants, readFileSync } from "node:fs";
import {
  chmod,
  copyFile,
  cp,
  mkdir,
  readdir,
  rm,
  stat,
} from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const templateRoot = join(packageRoot, "dist", "template", "rokid-hello-world");
const defaultTarget = "rokid-starter";

function readVersion() {
  const packageJson = JSON.parse(
    readFileSync(join(packageRoot, "package.json"), "utf8"),
  );
  return packageJson.version;
}

function usage() {
  return `Usage: npm create @glasskit.ai [target-dir]

Creates a WIP Rokid Glasses starter app.

Arguments:
  target-dir  Directory to create. Defaults to ${defaultTarget}.

Options:
  --help     Show this help message.
  --version  Show the package version.
`;
}

function parseArgs(args) {
  let targetDir = null;

  for (const arg of args) {
    if (arg === "--help" || arg === "-h") {
      return { help: true };
    }

    if (arg === "--version" || arg === "-v") {
      return { version: true };
    }

    if (arg.startsWith("-")) {
      throw new Error(`Unknown option: ${arg}`);
    }

    if (targetDir !== null) {
      throw new Error(`Unexpected argument: ${arg}`);
    }

    targetDir = arg;
  }

  return { targetDir: targetDir ?? defaultTarget };
}

function ensureTemplateExists() {
  try {
    accessSync(join(templateRoot, "settings.gradle.kts"), constants.R_OK);
  } catch {
    throw new Error(
      "Template files are missing. If you are running from source, run `npm run build` in the js package first.",
    );
  }
}

async function ensureWritableTarget(targetPath) {
  try {
    const targetStat = await stat(targetPath);

    if (!targetStat.isDirectory()) {
      throw new Error(`Target exists and is not a directory: ${targetPath}`);
    }

    const entries = await readdir(targetPath);
    if (entries.length > 0) {
      throw new Error(`Target directory is not empty: ${targetPath}`);
    }
  } catch (error) {
    if (error && error.code === "ENOENT") {
      await mkdir(targetPath, { recursive: true });
      return;
    }

    throw error;
  }
}

async function restoreTemplateGitignore(targetPath) {
  const portableGitignore = join(targetPath, "gitignore");

  try {
    await stat(portableGitignore);
  } catch (error) {
    if (error && error.code === "ENOENT") {
      return;
    }

    throw error;
  }

  await copyFile(portableGitignore, join(targetPath, ".gitignore"));
  await rm(portableGitignore);
}

function displayPath(targetPath) {
  const relativePath = relative(process.cwd(), targetPath);
  if (relativePath === "") {
    return ".";
  }

  return isAbsolute(relativePath) ? targetPath : relativePath;
}

async function createProject(targetDir) {
  ensureTemplateExists();

  const targetPath = resolve(process.cwd(), targetDir);
  await ensureWritableTarget(targetPath);
  await cp(templateRoot, targetPath, { recursive: true });
  await restoreTemplateGitignore(targetPath);
  await chmod(join(targetPath, "gradlew"), 0o755);

  const shownPath = displayPath(targetPath);
  console.log("GlassKit create is WIP.");
  console.log(`Created Rokid starter app at ${shownPath}`);
  console.log("");
  console.log("Next:");
  console.log(`  cd ${shownPath}`);
  console.log("  ./gradlew :app:assembleDebug");
  console.log("  adb install -r app/build/outputs/apk/debug/app-debug.apk");
  console.log("  adb shell am start -n com.example.rokidhello/.MainActivity");
}

async function main() {
  const parsed = parseArgs(process.argv.slice(2));

  if (parsed.help) {
    console.log(usage());
    return;
  }

  if (parsed.version) {
    console.log(readVersion());
    return;
  }

  await createProject(parsed.targetDir);
}

main().catch((error) => {
  console.error(`Error: ${error.message}`);
  process.exitCode = 1;
});
