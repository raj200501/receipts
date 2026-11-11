from unitconv.warehouse import send, weight_message


def test_weight_message_has_the_weight_in_grams() -> None:
    assert weight_message("P-20931", 12, "lb")["weight_g"] == 5443


def test_weight_message_keeps_the_entered_weight() -> None:
    assert weight_message("P-20931", 3.5, "kg")["entered"] == "3.5 kg"


def test_weight_message_names_the_parcel() -> None:
    assert weight_message("P-20931", 40, "oz")["parcel"] == "P-20931"


def test_send_parcel_weight_to_wms() -> None:
    # Needs the WMS bridge on /run/wms/bridge.sock, which runs only on the shipping desk PCs.
    assert send(weight_message("P-20931", 12, "lb")) == "ok"
