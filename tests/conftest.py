from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("GIT_AUTHOR_NAME", "Test")
os.environ.setdefault("GIT_AUTHOR_EMAIL", "test@example.com")
os.environ.setdefault("GIT_COMMITTER_NAME", "Test")
os.environ.setdefault("GIT_COMMITTER_EMAIL", "test@example.com")

FILES = {
    "shop/cart.py": '''
from shop.pricing import apply_discount


class Cart:
    """A shopping cart that totals line items."""

    def __init__(self):
        self.items = []

    def add_item(self, sku, qty, price):
        self.items.append((sku, qty, price))

    def total(self, coupon=None):
        subtotal = sum(q * p for _, q, p in self.items)
        return apply_discount(subtotal, coupon)
''',
    "shop/pricing.py": '''
def apply_discount(amount, coupon):
    """Apply a coupon code to an amount. Percentage coupons end with %."""
    if not coupon:
        return amount
    return amount - percent_off(amount, coupon)


def percent_off(amount, coupon):
    return amount * float(coupon.rstrip("%")) / 100
''',
    "shop/shipping.py": '''
def shipping_cost(weight_kg, express=False):
    """Flat rate plus weight; express doubles it."""
    base = 40 + 10 * weight_kg
    return base * 2 if express else base
''',
    "web/checkout.ts": '''
import { formatMoney } from "./money";

export class CheckoutPage {
  render(total: number): string {
    return formatMoney(total);
  }
}
''',
    "web/money.ts": '''
// Format an amount in rupees.
export function formatMoney(amount: number): string {
  return "Rs " + amount.toFixed(2);
}
''',
    "tests/test_cart.py": '''
from shop.cart import Cart


def test_total_with_coupon():
    c = Cart()
    c.add_item("a", 1, 100)
    assert c.total("10%") == 90
''',
}


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "shop-repo"
    root.mkdir()
    _git(root, "init", "-q")
    for path, body in FILES.items():
        f = root / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body.lstrip("\n"), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "Initial shop")
    # Two commits that change cart and pricing together, one about coupons.
    for i in range(2):
        for path in ("shop/cart.py", "shop/pricing.py"):
            with open(root / path, "a", encoding="utf-8") as fh:
                fh.write(f"\n# change {i}\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", f"Fix coupon rounding bug {i}")
    return root
