import pytest
from g15_common.db.query_loader import load_query


def test_sql_file_is_loaded(tmp_path):
    (tmp_path / 'health.sql').write_text('SELECT 1;')
    assert load_query(tmp_path, 'health.sql') == 'SELECT 1;'


@pytest.mark.parametrize('name', ['health.txt', '../outside.sql', 'linked.sql'])
def test_query_rejects_invalid_names_and_escaped_files(tmp_path, name):
    directory = tmp_path / 'sql'
    directory.mkdir()
    outside = tmp_path / 'outside.sql'
    outside.write_text('SELECT 1;')
    (directory / 'linked.sql').symlink_to(outside)
    with pytest.raises(ValueError):
        load_query(directory, name)


def test_missing_query_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_query(tmp_path, 'missing.sql')
