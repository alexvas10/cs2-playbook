from pathlib import Path

import pytest

from csanalysis.config import Paths
from csanalysis.synthetic import generate


@pytest.fixture(scope="session")
def synth_paths(tmp_path_factory) -> Paths:
    paths = Paths(Path(tmp_path_factory.mktemp("synth")))
    generate(paths, n_matches=6, seed=1)
    return paths
