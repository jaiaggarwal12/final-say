import os
import random

import numpy as np


def set_seed(seed: int = 42) -> None:
    """Seed every RNG we use so results are reproducible."""
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import torch
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass  # torch not installed yet
