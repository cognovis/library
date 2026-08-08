import {
  lstat,
  mkdir,
  readdir,
  realpath,
  stat,
  symlink,
  unlink,
} from "node:fs/promises";
import path from "node:path";

import { findOnPath } from "./providers.ts";

/**
 * Vendored Pi assets keep bare imports of the Pi runtime packages. The provider
 * bundle needs `@earendil-works/pi-ai` because `build:extensions` marks it
 * external so the workbench shares one runtime instance with the Pi process
 * that loads it, and the Fusion extension additionally imports
 * `@earendil-works/pi-coding-agent` and `@earendil-works/pi-tui` as values.
 * Both are loaded through a plain `import(file://...)`, so those specifiers
 * resolve against each file's own location.
 *
 * In a consuming repository the assets live under `.agents/pi/`, where nothing
 * along the path carries a `node_modules` tree, and the launch fails with
 * "Cannot find module '@earendil-works/pi-ai'". The Pi installation that is
 * about to load them already ships the packages, so the launcher links them
 * onto the resolution path instead of requiring the consuming repository to
 * install a JavaScript toolchain of its own.
 */
const RUNTIME_SCOPE = "@earendil-works";
/** Imported by the provider bundle and the Fusion extension respectively. */
const REQUIRED_PACKAGES = ["pi-ai", "pi-coding-agent", "pi-tui"] as const;
const PROJECT_NATIVE_PI_ROOT = path.join(".agents", "pi");

async function isDirectory(target: string): Promise<boolean> {
  try {
    return (await stat(target)).isDirectory();
  } catch {
    return false;
  }
}

/** Walk the node_modules chain above a file, newest ancestor first. */
function* scopeCandidates(fromFile: string): Generator<string> {
  let directory = path.dirname(path.resolve(fromFile));
  for (;;) {
    yield path.join(directory, "node_modules", RUNTIME_SCOPE);
    const parent = path.dirname(directory);
    if (parent === directory) return;
    directory = parent;
  }
}

/** Report whether every runtime package resolves from a file's location. */
export async function providerRuntimeResolves(providerPath: string): Promise<boolean> {
  const missing = new Set<string>(REQUIRED_PACKAGES);
  for (const scope of scopeCandidates(providerPath)) {
    for (const name of [...missing]) {
      if (await isDirectory(path.join(scope, name))) missing.delete(name);
    }
    if (missing.size === 0) return true;
  }
  return false;
}

/**
 * Collect the runtime packages of the Pi installation that is about to be
 * spawned, mapping package name to its directory.
 *
 * A Pi install splits them across two levels: the top-level scope holds
 * `pi-coding-agent`, and its own nested tree holds `pi-ai` and `pi-tui`.
 * Neither level alone satisfies every import, so both are merged.
 */
export async function piRuntimePackages(
  piCommand: string,
  environment: NodeJS.ProcessEnv = process.env,
): Promise<Map<string, string>> {
  const packages = new Map<string, string>();
  // The launcher falls back to the bare name "pi" when the repository has no
  // local install, so resolve through PATH before touching the filesystem.
  const located = piCommand.includes(path.sep)
    ? piCommand
    : await findOnPath(piCommand, environment);
  if (!located) return packages;
  let entry: string;
  try {
    entry = await realpath(located);
  } catch {
    return packages;
  }

  const scopes: string[] = [];
  let directory = path.dirname(entry);
  for (;;) {
    if (path.basename(directory) === RUNTIME_SCOPE) scopes.push(directory);
    scopes.push(path.join(directory, "node_modules", RUNTIME_SCOPE));
    const parent = path.dirname(directory);
    if (parent === directory) break;
    directory = parent;
  }

  for (const scope of scopes) {
    let names: string[];
    try {
      names = await readdir(scope);
    } catch {
      continue;
    }
    for (const name of names) {
      if (packages.has(name)) continue;
      const candidate = path.join(scope, name);
      if (await isDirectory(candidate)) packages.set(name, candidate);
    }
  }
  return packages;
}

async function link(target: string, linkPath: string): Promise<void> {
  try {
    await unlink(linkPath);
  } catch {
    // Nothing to replace.
  }
  await symlink(target, linkPath, "dir");
}

/**
 * Make the Pi runtime resolvable for vendored Pi assets.
 *
 * Returns the scope directory that was populated, or null when nothing was
 * needed. It is placed under `.agents/pi/node_modules`, which is on the
 * resolution path but outside the Library-vendored extension directories, so
 * the recorded bundle checksums do not register as drift.
 */
export async function ensureProviderRuntimeResolution(
  repositoryRoot: string,
  providerPath: string,
  piCommand: string,
  environment: NodeJS.ProcessEnv = process.env,
): Promise<string | null> {
  const root = path.resolve(repositoryRoot);
  const provider = path.resolve(providerPath);
  const projectNativeRoot = path.join(root, PROJECT_NATIVE_PI_ROOT);
  if (!provider.startsWith(projectNativeRoot + path.sep)) return null;
  if (await providerRuntimeResolves(provider)) return null;

  const packages = await piRuntimePackages(piCommand, environment);
  const missing = REQUIRED_PACKAGES.filter((name) => !packages.has(name));
  if (missing.length > 0) {
    throw new Error(
      `Cannot make the Pi runtime resolvable for ${provider}: ` +
        `${piCommand} ships no ${missing.map((name) => `${RUNTIME_SCOPE}/${name}`).join(", ")}`,
    );
  }

  const scope = path.join(projectNativeRoot, "node_modules", RUNTIME_SCOPE);
  // A symlinked scope directory would make the loop below write into the real
  // Pi installation, so replace it with a directory we own.
  try {
    if ((await lstat(scope)).isSymbolicLink()) await unlink(scope);
  } catch {
    // Nothing there yet.
  }
  await mkdir(scope, { recursive: true });
  for (const [name, directory] of packages) {
    await link(directory, path.join(scope, name));
  }
  return scope;
}
