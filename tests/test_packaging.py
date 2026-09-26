import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_railpack_requirements_match_project_dependencies() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    expected = set(project["project"]["dependencies"])

    requirements_path = ROOT / "requirements.txt"
    assert requirements_path.exists(), "Railpack pip builds require requirements.txt"
    actual = {
        line.strip()
        for line in requirements_path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert actual == expected
