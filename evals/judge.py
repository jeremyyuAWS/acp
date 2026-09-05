"""The optional model judge — for the one dimension with no ground truth, and nothing else.

Alt text quality is a matter of taste; "did the criterion clear" is not. Everything a
deterministic grader can answer is answered there, and this file exists only for the residue:
is the proposed value one a reviewer would have accepted.

IT IS OFF BY DEFAULT AND IT REPORTS ITS OWN AGREEMENT. A judge that has not been calibrated
against human labels is a second opinion presented as a measurement. `calibrate()` takes the
labelled pairs a reviewer has already produced and reports the judge's agreement rate; the
report prints that number next to any judged score, so a 0.82 quality figure is always read
beside "judge agrees with humans 0.61 of the time" — which is the number that decides whether
the first one means anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass
class JudgeVerdict:
    accept: bool
    reason: str = ""


@dataclass
class Calibration:
    n: int
    agreement: float
    false_accept: float
    false_reject: float

    @property
    def usable(self) -> bool:
        """Below 0.8 agreement the judge is measuring itself. The threshold is a convention,
        chosen once and stated, so a run cannot pick a friendlier one after seeing the result."""
        return self.n >= 20 and self.agreement >= 0.8


def calibrate(judge: Callable[[str, str], JudgeVerdict],
              labelled: Sequence[tuple[str, str, bool]]) -> Calibration:
    """`labelled` is (case prompt, candidate value, human accepted?)."""
    if not labelled:
        return Calibration(0, 0.0, 0.0, 0.0)
    agree = fa = fr = 0
    for prompt, value, human in labelled:
        v = judge(prompt, value).accept
        agree += int(v == human)
        fa += int(v and not human)
        fr += int(human and not v)
    n = len(labelled)
    return Calibration(n, agree / n, fa / n, fr / n)
