from stockroom.warehouse import pick_list_payload, send_pick_list

PICKS = [("WGT-2", 2), ("BLT-M6", 4)]


def test_payload_names_the_order() -> None:
    assert pick_list_payload("SO-1001", PICKS)["order"] == "SO-1001"


def test_payload_lists_the_picks_sorted_by_sku() -> None:
    picks = pick_list_payload("SO-1001", PICKS)["picks"]
    assert picks == [{"sku": "BLT-M6", "qty": 4}, {"sku": "WGT-2", "qty": 2}]


def test_payload_of_an_empty_pick_list() -> None:
    assert pick_list_payload("SO-1", [])["picks"] == []


def test_send_pick_list_to_the_wms() -> None:
    # Integration test: needs the WMS host, which resolves only on the office network.
    assert send_pick_list(pick_list_payload("SO-1001", PICKS)) == 202
