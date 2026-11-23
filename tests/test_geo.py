from mtg_retail.geo import miles_between

def test_same_point(): assert miles_between(37.6872,-97.3301,37.6872,-97.3301)==0

def test_known_scale(): assert 100 < miles_between(37.6872,-97.3301,36.154,-95.993) < 150
