import tomllib
from pathlib import Path


def test_desktop_runtime_dependencies_are_declared_for_both_install_paths():
    root = Path(__file__).resolve().parents[1]
    package = tomllib.loads((root / "pyproject.toml").read_text())
    package_deps = package["project"]["dependencies"]
    requirements = (root / "requirements.txt").read_text().splitlines()
    for module in ("uvicorn", "fastapi", "sqlalchemy", "alembic"):
        assert any(dep.lower().startswith(module) for dep in package_deps)
        assert any(dep.lower().startswith(module) for dep in requirements)
