def test_package_imports():
    import pound

    assert pound.__doc__


def test_ingest_subpackage_imports():
    from pound import ingest

    assert ingest.__doc__
