from sppyte.main import hello


def test_runner():
    expected = 1
    assert expected == 1


def test_hello():
    expected = "world"
    assert hello() == expected
