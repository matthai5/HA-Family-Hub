"""jordan fork: tests for the per-person currency mode and IOU balance
helpers in reward_engine.py.

reward_engine is hass-free apart from homeassistant.util.dt, so these run
with the standard library alone - no Home Assistant install needed:

    python -m unittest discover -s tests

The package's own __init__.py imports all of Home Assistant, so the
family_hub package is registered here without running it, and a minimal
stand-in for homeassistant.util.dt is provided.
"""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "family_hub"


def _load_reward_engine():
    if "homeassistant.util.dt" not in sys.modules:
        ha = types.ModuleType("homeassistant")
        ha_util = types.ModuleType("homeassistant.util")
        ha_dt = types.ModuleType("homeassistant.util.dt")
        ha_dt.utcnow = lambda: datetime.now(timezone.utc)
        ha_util.dt = ha_dt
        ha.util = ha_util
        sys.modules.update({"homeassistant": ha, "homeassistant.util": ha_util, "homeassistant.util.dt": ha_dt})
    for name, path in (("custom_components", PKG_DIR.parent), ("custom_components.family_hub", PKG_DIR)):
        if name not in sys.modules:
            pkg = types.ModuleType(name)
            pkg.__path__ = [str(path)]
            sys.modules[name] = pkg
    return importlib.import_module("custom_components.family_hub.reward_engine")


re = _load_reward_engine()

HENRY = "henry-id"
AGNES = "agnes-id"
SETTINGS = {"currencyUserIds": [HENRY]}
EST = timezone(timedelta(hours=-5))


def _ledger_entry(user_id, delta, source, at):
    return {"user_id": user_id, "delta": delta, "source": source, "at": at.astimezone(timezone.utc).isoformat()}


class FormatAmountTests(unittest.TestCase):
    def test_currency_user_gets_dollars(self):
        self.assertEqual(re.format_amount(SETTINGS, HENRY, 50), "$0.50")
        self.assertEqual(re.format_amount(SETTINGS, HENRY, 1250), "$12.50")
        self.assertEqual(re.format_amount(SETTINGS, HENRY, -300), "-$3.00")

    def test_everyone_else_gets_stars(self):
        self.assertEqual(re.format_amount(SETTINGS, AGNES, 5), "5 stars")
        self.assertEqual(re.format_amount(SETTINGS, AGNES, 1), "1 star")
        self.assertEqual(re.format_amount({}, HENRY, 50), "50 stars")

    def test_custom_symbol(self):
        self.assertEqual(re.format_amount({**SETTINGS, "currencySymbol": "€"}, HENRY, 199), "€1.99")

    def test_is_currency_user_handles_bad_settings(self):
        self.assertFalse(re.is_currency_user(None, HENRY))
        self.assertFalse(re.is_currency_user({"currencyUserIds": "henry-id"}, HENRY))
        self.assertFalse(re.is_currency_user(SETTINGS, None))


class CarryForwardTests(unittest.TestCase):
    def test_missing_keys_are_kept_from_existing(self):
        new = {"theme": "x"}
        re.carry_forward_currency_settings(new, {"currencyUserIds": [HENRY], "currencySymbol": "$"})
        self.assertEqual(new["currencyUserIds"], [HENRY])
        self.assertEqual(new["currencySymbol"], "$")

    def test_explicit_empty_list_turns_currency_off(self):
        new = {"currencyUserIds": []}
        re.carry_forward_currency_settings(new, {"currencyUserIds": [HENRY]})
        self.assertEqual(new["currencyUserIds"], [])

    def test_nothing_to_carry(self):
        new = {}
        re.carry_forward_currency_settings(new, {})
        self.assertNotIn("currencyUserIds", new)


class CatalogUnitTests(unittest.TestCase):
    def test_money_items_only_for_money_people(self):
        money_item = {"currency": True}
        star_item = {}
        self.assertFalse(re.currency_mismatch(SETTINGS, HENRY, money_item))
        self.assertTrue(re.currency_mismatch(SETTINGS, AGNES, money_item))
        self.assertTrue(re.currency_mismatch(SETTINGS, HENRY, star_item))
        self.assertFalse(re.currency_mismatch(SETTINGS, AGNES, star_item))

    def test_add_and_update_carry_the_flag(self):
        rewards = {}
        item = re.add_catalog_item(rewards, "Robux", 500, currency=True)
        self.assertTrue(item["currency"])
        re.update_catalog_item(rewards, item["id"], currency=False)
        self.assertFalse(rewards["catalog"][0]["currency"])
        self.assertFalse(re.add_catalog_item(rewards, "Movie night", 20)["currency"])


class PayOutTests(unittest.TestCase):
    def test_pays_whole_balance_by_default(self):
        rewards = {"balances": {HENRY: 650}}
        result = re.pay_out(rewards, HENRY)
        self.assertEqual(result, {"amount": 650, "balance": 0})
        entry = rewards["ledger"][-1]
        self.assertEqual((entry["delta"], entry["source"], entry["reason"]), (-650, "payout", "Paid out"))

    def test_partial_payout_with_reason(self):
        rewards = {"balances": {HENRY: 650}}
        self.assertEqual(re.pay_out(rewards, HENRY, 500, "FamZoo")["balance"], 150)
        self.assertEqual(rewards["ledger"][-1]["reason"], "FamZoo")

    def test_refuses_nothing_owed_or_overpaying(self):
        with self.assertRaises(re.RewardError):
            re.pay_out({"balances": {HENRY: 0}}, HENRY)
        with self.assertRaises(re.RewardError):
            re.pay_out({"balances": {HENRY: 100}}, HENRY, 101)


class LedgerSummaryTests(unittest.TestCase):
    # Wednesday 2026-10-28 15:00 local; week starts Monday 10-26.
    NOW = datetime(2026, 10, 28, 15, 0, tzinfo=EST)

    def _summary(self, entries):
        return re.ledger_summary({"ledger": entries}, HENRY, self.NOW)

    def test_buckets_earned_paid_and_penalties(self):
        entries = [
            _ledger_entry(HENRY, 50, "chore_approved", datetime(2026, 10, 27, 9, tzinfo=EST)),     # this week
            _ledger_entry(HENRY, 300, "chore_approved", datetime(2026, 10, 20, 9, tzinfo=EST)),    # earlier this month
            _ledger_entry(HENRY, 100, "manual_adjustment", datetime(2026, 10, 28, 8, tzinfo=EST)), # bonus, this week
            _ledger_entry(HENRY, 500, "goal_achieved", datetime(2026, 9, 15, 9, tzinfo=EST)),      # last month
            _ledger_entry(HENRY, -400, "payout", datetime(2026, 10, 25, 9, tzinfo=EST)),
            _ledger_entry(HENRY, -200, "manual_adjustment", datetime(2026, 9, 30, 9, tzinfo=EST)), # paid last month
            _ledger_entry(HENRY, -50, "chore_overdue", datetime(2026, 10, 10, 9, tzinfo=EST)),
            _ledger_entry(HENRY, -100, "redeemed", datetime(2026, 10, 26, 9, tzinfo=EST)),         # neither
            _ledger_entry(AGNES, 999, "chore_approved", datetime(2026, 10, 27, 9, tzinfo=EST)),    # someone else
        ]
        s = self._summary(entries)
        self.assertEqual(s["earned_this_week"], 150)
        self.assertEqual(s["earned_this_month"], 450)
        self.assertEqual(s["earned_last_month"], 500)
        self.assertEqual(s["paid_this_month"], 400)
        self.assertEqual(s["paid_last_month"], 200)
        self.assertEqual(s["penalties_this_month"], 50)
        self.assertEqual(s["last_payout_amount"], 400)
        self.assertTrue(s["last_payout_at"].startswith("2026-10-25T09:00"))

    def test_month_boundary_uses_local_time(self):
        # 23:30 local on Sept 30 is already Oct 1 in UTC, and must still
        # count as last month.
        late_sept = datetime(2026, 9, 30, 23, 30, tzinfo=EST)
        s = self._summary([_ledger_entry(HENRY, 75, "chore_approved", late_sept)])
        self.assertEqual((s["earned_this_month"], s["earned_last_month"]), (0, 75))

    def test_empty_ledger(self):
        s = self._summary([])
        self.assertEqual(s["earned_this_week"], 0)
        self.assertIsNone(s["last_payout_at"])


if __name__ == "__main__":
    unittest.main()
