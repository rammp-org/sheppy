import sheppy


def test_package_has_version():
    assert isinstance(sheppy.__version__, str)
    assert sheppy.__version__
