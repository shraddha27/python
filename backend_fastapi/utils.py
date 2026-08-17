"""Shared helper utilities for backend_fastapi."""

import math
from typing import List, Union

import numpy as np


def format_pgvector_literal(values: List[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"


def cosine_similarity(left: Union[List[float], np.ndarray], right: Union[List[float], np.ndarray]) -> float:
    left_arr = np.asarray(left, dtype=np.float32)
    right_arr = np.asarray(right, dtype=np.float32)
    if left_arr.size == 0 or right_arr.size == 0 or left_arr.shape != right_arr.shape:
        return 0.0
    left_norm = float(np.linalg.norm(left_arr))
    right_norm = float(np.linalg.norm(right_arr))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return float(np.dot(left_arr, right_arr) / (left_norm * right_norm))
