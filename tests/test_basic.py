import json
import os


def test_config_json_exists_and_valid():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    config_path = os.path.join(repo_root, "config.json")
    assert os.path.exists(config_path)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    assert "defaults" in config
    assert "agents" in config
