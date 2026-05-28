from __future__ import annotations

import skrf as rf


DEFAULT_SMITH_REF_IMPEDANCE = 50.0


def draw_smith_chart_background(
    ax,
    title: str | None = None,
    *,
    draw_labels: bool = False,
    ref_imm: float = DEFAULT_SMITH_REF_IMPEDANCE,
) -> None:
    """Draw a scikit-rf Smith chart background on an existing axis."""
    rf.plotting.smith(
        ax=ax,
        chart_type="z",
        draw_labels=draw_labels,
        ref_imm=ref_imm,
    )
    ax.set_aspect("equal", adjustable="box")
    if title is not None:
        ax.set_title(title)
