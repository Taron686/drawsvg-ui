import assert from "node:assert/strict";
import { test } from "node:test";
import { looksLikeDrawsvg } from "./detection";

const main = 'if __name__ == "__main__":\n    build_drawing()\n';
const body = "def build_drawing():\n    return draw.Drawing(1, 1)\n\n";

test("accepts exporter style files", () => {
  assert.equal(looksLikeDrawsvg("# Auto-generated\nimport drawsvg as draw\n\n" + body + main), true);
});

test("accepts single quotes, CRLF and from-imports", () => {
  const text = ("from drawsvg import Drawing\n\n" + body + main)
    .replace(/"/g, "'")
    .replace(/\n/g, "\r\n");
  assert.equal(looksLikeDrawsvg(text), true);
});

test("accepts reversed main guard", () => {
  const text = "import drawsvg\n\n" + body + 'if "__main__" == __name__:\n    pass\n';
  assert.equal(looksLikeDrawsvg(text), true);
});

test("rejects plain python", () => {
  assert.equal(looksLikeDrawsvg("import math\n\n" + main), false);
});

test("rejects missing main guard", () => {
  assert.equal(looksLikeDrawsvg("import drawsvg as draw\n\n" + body), false);
});

test("rejects commented or indented imports and similar module names", () => {
  assert.equal(looksLikeDrawsvg("# import drawsvg\n" + main), false);
  assert.equal(looksLikeDrawsvg("def f():\n    import drawsvg\n" + main), false);
  assert.equal(looksLikeDrawsvg("import drawsvg_tools\n" + main), false);
});

test("rejects imports far below the header", () => {
  assert.equal(looksLikeDrawsvg("\n".repeat(60) + "import drawsvg\n" + main), false);
});
