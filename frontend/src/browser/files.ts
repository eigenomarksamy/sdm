// Which picked files get mounted, and the order a mounted folder lists in.
import type { MountRules } from "./protocol";

/**
 * Whether a picked file is one a command reads: audio by extension (all of
 * them, AppleDouble `._` stubs too, because the catalog export counts those),
 * or anything under the Rekordbox analysis folder. `path` starts with the
 * picked folder's own name, so picking `USBANLZ` itself keeps its contents.
 *
 * On the reference USB this drops 14,728 of 29,593 files — the artwork JPGs
 * under PIONEER/Artwork — and every one dropped is a File the browser no
 * longer has to hand to the worker.
 */
export function keepForMount(path: string, rules: MountRules): boolean {
  const lower = path.toLowerCase();
  if (rules.audio_exts.some((ext) => lower.endsWith(ext))) return true;
  const dir = rules.analysis_dir.toLowerCase();
  const parts = lower.split("/");
  return parts.slice(0, -1).includes(dir);
}

/**
 * Names in the order NTFS lists a directory: each UTF-16 unit uppercased, then
 * compared unit by unit. That is the order a native run's `os.walk` sees, and
 * the catalog export writes rows in walk order, so matching it is what makes
 * the browser's export byte-identical to a run on Windows.
 *
 * Uppercasing is per unit, keeping a character whose full uppercase is longer
 * ("ß" -> "SS") as it is: NTFS's upcase table maps one unit to one unit.
 */
export function ntfsCompare(a: string, b: string): number {
  const ka = ntfsKey(a);
  const kb = ntfsKey(b);
  return ka < kb ? -1 : ka > kb ? 1 : 0;
}

const upper = new Map<number, string>();

function ntfsKey(name: string): string {
  let key = "";
  for (let i = 0; i < name.length; i++) {
    const unit = name.charCodeAt(i);
    let mapped = upper.get(unit);
    if (mapped === undefined) {
      const ch = String.fromCharCode(unit);
      const up = ch.toUpperCase();
      mapped = up.length === 1 ? up : ch;
      upper.set(unit, mapped);
    }
    key += mapped;
  }
  return key;
}

/** A folder's name as a mount point: no separators, no drive colon, never empty. */
export function mountName(name: string): string {
  return name.replace(/[\\/]+$/, "").replace(/[\\/:*?"<>|]/g, "").trim() || "folder";
}
