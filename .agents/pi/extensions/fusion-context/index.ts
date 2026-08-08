import { pathToFileURL } from "node:url";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default async function register(pi: ExtensionAPI): Promise<void> {
  const module = await import(pathToFileURL(path.join(import.meta.dirname, "dist/pi-extension.js")).href) as {
    default?: (pi: ExtensionAPI) => void | Promise<void>;
  };
  if (typeof module.default !== "function") throw new Error("Fusion context extension bundle is missing");
  await module.default(pi);
}
