"""Classification metrics with explicit masks and zero-division handling."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np


def _ratio(numerator: float, denominator: float, zero_division: float) -> float:
    return numerator / denominator if denominator else zero_division


def classification_scores(
    truth: np.ndarray,
    predicted: np.ndarray,
    labels: Sequence[int],
    class_names: Mapping[int, str],
    *,
    ignore_values: Sequence[int] = (0,),
    abstain_values: Sequence[int] = (0,),
    zero_division: float = 0.0,
) -> dict[str, Any]:
    """Score predictions, counting abstentions as misses.

    Pixels whose truth value is in ignore_values are excluded from every
    denominator. Macro averages use only classes present in the truth.
    """
    scored = ~np.isin(truth, list(ignore_values))
    reference = truth[scored]
    guess = predicted[scored]
    abstained = np.isin(guess, list(abstain_values))
    evaluated = int(reference.size)
    result: dict[str, Any] = {
        "evaluated_pixels": evaluated,
        "ignored_pixels": int(truth.size - evaluated),
        "abstained_pixels": int(abstained.sum()),
        "abstain_fraction": _ratio(float(abstained.sum()), evaluated, zero_division),
        "overall_accuracy": _ratio(float(np.count_nonzero(reference == guess)), evaluated, zero_division),
    }
    f1_scores: list[float] = []
    iou_scores: list[float] = []
    matrix = []
    for label in labels:
        name = class_names[label]
        true_positive = int(np.count_nonzero((reference == label) & (guess == label)))
        false_positive = int(np.count_nonzero((reference != label) & (guess == label)))
        false_negative = int(np.count_nonzero((reference == label) & (guess != label)))
        precision = _ratio(true_positive, true_positive + false_positive, zero_division)
        recall = _ratio(true_positive, true_positive + false_negative, zero_division)
        f1 = _ratio(2 * precision * recall, precision + recall, zero_division)
        iou = _ratio(true_positive, true_positive + false_positive + false_negative, zero_division)
        result[f"precision.{name}"] = precision
        result[f"recall.{name}"] = recall
        result[f"f1.{name}"] = f1
        result[f"iou.{name}"] = iou
        result[f"support.{name}"] = int(np.count_nonzero(reference == label))
        if result[f"support.{name}"]:
            f1_scores.append(f1)
            iou_scores.append(iou)
        matrix.append([int(np.count_nonzero((reference == label) & (guess == other))) for other in labels])
    result["macro_f1"] = float(np.mean(f1_scores)) if f1_scores else zero_division
    result["mean_iou"] = float(np.mean(iou_scores)) if iou_scores else zero_division
    result["confusion_matrix"] = matrix
    return result
