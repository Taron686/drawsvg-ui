import * as esbuild from "esbuild";

const args = process.argv.slice(2);
const common = { bundle: true, platform: "node", target: "node18", format: "cjs", logLevel: "info" };

if (args.includes("--test")) {
  await esbuild.build({ ...common, entryPoints: ["src/detection.test.ts"], outdir: "dist-test" });
} else {
  const options = {
    ...common,
    entryPoints: ["src/extension.ts"],
    outfile: "dist/extension.js",
    external: ["vscode"],
    sourcemap: true,
  };
  if (args.includes("--watch")) {
    await (await esbuild.context(options)).watch();
  } else {
    await esbuild.build(options);
  }
}
