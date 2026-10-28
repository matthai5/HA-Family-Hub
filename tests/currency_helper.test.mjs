// jordan fork: tests for the cards' shared per-person currency helper.
// The helper is copied into every card that shows stars; these load the
// copy out of each card's source, so a card whose copy drifts fails too.
//
//     node --test tests/currency_helper.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const CARDS = ["family-hub-chores-card.js", "family-hub-rewards-card.js", "family-hub-goals-card.js"];
const START = "// ---- Family Hub per-person currency helper (jordan fork)";
const END = "var __fhUseHass = function (hass) {";

function loadHelper(card) {
  const src = readFileSync(new URL(`../custom_components/family_hub/card/${card}`, import.meta.url), "utf8");
  const escStart = src.indexOf("var __fhEsc = function");
  const escEnd = src.indexOf("};", escStart) + 2;
  const helper = src.slice(src.indexOf(START), src.indexOf(END));
  assert.ok(helper.length > 0, `${card} has no currency helper`);
  const ctx = { window: {} };
  vm.createContext(ctx);
  vm.runInContext(src.slice(escStart, escEnd) + "\n" + helper, ctx);
  ctx.__fhCurSet({ currencyUserIds: ["H"] });
  return { ctx, helper };
}

for (const card of CARDS) {
  test(`${card}: formats money and stars by person`, () => {
    const { ctx } = loadHelper(card);
    assert.equal(ctx.__fhPts(50, "H"), "$0.50");
    assert.equal(ctx.__fhPts(1250, "H"), "$12.50");
    assert.equal(ctx.__fhPts(-300, "H"), "&minus;$3.00");
    assert.equal(ctx.__fhPts(50, "H", { signed: true }), "+$0.50");
    assert.equal(ctx.__fhPts(50, "A"), "&#11088; 50");
    assert.equal(ctx.__fhPts(5, "A", { signed: true, suffix: true }), "+5&#11088;");
  });

  test(`${card}: catalog items use their own flag`, () => {
    const { ctx } = loadHelper(card);
    assert.equal(ctx.__fhPts(500, true), "$5.00");
    assert.equal(ctx.__fhPts(20, false, { suffix: true }), "20&#11088;");
  });

  test(`${card}: number inputs round-trip cents`, () => {
    const { ctx } = loadHelper(card);
    assert.equal(ctx.__fhPtsIn(50, "H"), "0.50");
    assert.equal(ctx.__fhPtsIn(5, "A"), "5");
    assert.equal(ctx.__fhPtsOut("0.5", "H"), 50);
    assert.equal(ctx.__fhPtsOut("0.29", "H"), 29);
    assert.equal(ctx.__fhPtsOut("12.345", "H"), 1235);
    assert.equal(ctx.__fhPtsOut("3", "A"), 3);
    assert.equal(ctx.__fhPtsOut("", "H"), 0);
  });
}

test("every card carries the same helper", () => {
  const copies = CARDS.map((card) => loadHelper(card).helper);
  for (const copy of copies.slice(1)) assert.equal(copy, copies[0]);
});
