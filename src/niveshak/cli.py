"""`niveshak` command-line interface.

The Day-2 gate: `niveshak score "<paste a real tip>"` prints a 0-100 manipulation-risk
score, a band, and the top reasons. Runs the full pipeline (parse -> resolve -> blend).
"""

from __future__ import annotations

import typer

from niveshak.score.assemble import RiskScore, Scorer

app = typer.Typer(add_completion=False, help="Niveshak — manipulation-risk scoring for stock tips.")


@app.callback()
def main() -> None:
    """Niveshak CLI. Keeps `score` as an explicit subcommand (`niveshak score "<tip>"`)."""


def _render(rs: RiskScore) -> str:
    lines = [
        "Niveshak — manipulation-risk score",
        f"  Score : {rs.value}/100    Band: {rs.band.upper()}    Confidence: {rs.confidence:.2f}",
        f"  Ticker: {rs.ticker or '(unresolved)'}    "
        f"(model susceptibility {rs.model_susceptibility:.2f} · "
        f"message red-flags {rs.message_red_flag_score:.2f})",
    ]
    if rs.contributions:
        lines.append("  Top reasons:")
        for i, c in enumerate(rs.contributions, 1):
            lines.append(f"    {i}. {c.reason}  (+{c.impact:.0f})")
    if rs.notes:
        lines.append("  Notes:")
        lines.extend(f"    - {n}" for n in rs.notes)
    lines.append(f"  {rs.disclaimer}")
    return "\n".join(lines)


@app.command()
def score(
    text: str = typer.Argument(..., help="The tip message to score."),
    source: str = typer.Option("manual", help="telegram|youtube|x|whatsapp|manual"),
) -> None:
    """Score a single tip message for manipulation risk."""
    scorer = Scorer.from_paths()
    rs = scorer.score_text(text, source=source)
    typer.echo(_render(rs))


if __name__ == "__main__":
    app()
