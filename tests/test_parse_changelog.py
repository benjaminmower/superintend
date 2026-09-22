from tests.fixtures.demo_sheet import make_demo_client
from tracker_agent.parse.changelog import index_by_item, normalize_key, parse_changelog_tab


def test_parse_changelog_reads_all_rows():
    client = make_demo_client()

    changes = parse_changelog_tab(client, "Change log")

    assert len(changes) == 2
    assert changes[0].column_name == "STATUS"
    assert changes[0].old_value == "Not started"
    assert changes[0].new_value == "In progress"


def test_index_by_item_groups_by_normalized_sub_and_item():
    client = make_demo_client()
    changes = parse_changelog_tab(client, "Change log")

    index = index_by_item(changes)

    key = normalize_key("Framer", "Rough framing")
    assert key in index
    assert len(index[key]) == 1
    assert index[key][0].new_value == "In progress"


def test_normalize_key_is_case_and_whitespace_insensitive():
    assert normalize_key("Framer", "Rough framing") == normalize_key(" framer ", "ROUGH FRAMING")


def test_index_by_item_sorts_oldest_first():
    client = make_demo_client()
    changes = parse_changelog_tab(client, "Change log")
    index = index_by_item(changes)

    key = normalize_key("Plumber", "Rough plumbing")
    group = index[key]
    timestamps = [c.timestamp for c in group]
    assert timestamps == sorted(timestamps)
