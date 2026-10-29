import pytest


@pytest.mark.core
def test_smoke_test(tmp_path) -> None:
    from r2x_core import DataFile, DataReader, DataStore

    test_file = tmp_path / "test_data.csv"
    test_file.write_text("")
    _ = DataStore()
    _ = DataReader()
    _ = DataFile(name="test", fpath=test_file)
