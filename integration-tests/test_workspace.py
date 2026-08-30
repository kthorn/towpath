from importlib.metadata import distribution


def test_core_distribution_owns_pound_namespace():
    assert distribution("pound-core").metadata["Name"] == "pound-core"
    import pound

    assert pound.__name__ == "pound"
