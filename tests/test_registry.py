from mtg_retail.core import stable_id, config

def test_stable_id(): assert stable_id('A','B')==stable_id('a','b')
def test_radius(): assert config()['radius_miles']==300
