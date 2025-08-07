from sppyte.main import hello


def test_runner():
    assert 1 == 1


def test_hello():
    assert hello() == "world"
