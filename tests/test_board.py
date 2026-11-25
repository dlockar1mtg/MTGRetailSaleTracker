from datetime import date
import json

from conftest import event, store, term
from mtg_retail.board import build
from mtg_retail.core import config
from mtg_retail.evaluate import assess_all
from mtg_retail.registry import load

TODAY = date(2026, 11, 23)


def test_board_lists_each_kind_with_links_and_maps(tmp_path, make_registry):
    reg = load(make_registry(stores=[store(), store(store_id="other-store", lat=37.9, lon=-97.1)],
                             events=[event(status="VERIFIED"), event(event_id="lead-sale", store_id="other-store")],
                             terms=[term(pct="35")]))
    a = assess_all(reg, config(), TODAY)
    counts = {"radius": 300, "in_radius": 2, "collectors": "test", "checks": "2 read"}
    out = tmp_path / "board"
    result = build(a, {"test-sale": 12}, counts, "o/r", TODAY, out, list(reg.stores.values()))
    text = (out / "README.md").read_text()
    assert result == {"sales": 2, "stores": 2}
    assert "35% off singles" in text and "[#12](https://github.com/o/r/issues/12)" in text
    assert "## \U0001F4C5 Announced, details unknown (1)" in text and "_None right now._" in text   # no automatic finds
    sales = json.loads((out / "sales.geojson").read_text())
    kinds = sorted(f["properties"]["marker-symbol"] for f in sales["features"])
    assert kinds == ["star", "triangle"] and sales["features"][0]["geometry"]["coordinates"][0] < 0
