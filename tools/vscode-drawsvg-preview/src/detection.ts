/**
 * Cheap first-stage check that runs on every editor switch without starting
 * Python. The helper script repeats the check precisely with the `ast` module.
 */
const HEADER_LINES = 40;
const IMPORT = /^(?:import\s+drawsvg\b|from\s+drawsvg\s+import\b)/m;
const MAIN_GUARD =
  /^if\s+\(?\s*(?:__name__\s*==\s*['"]__main__['"]|['"]__main__['"]\s*==\s*__name__)/m;

export function looksLikeDrawsvg(text: string): boolean {
  const header = text.split(/\r?\n/, HEADER_LINES).join("\n");
  return IMPORT.test(header) && MAIN_GUARD.test(text);
}
