"""Salary statistics from employment_history.csv.

Salaries are nominal dollars of each spell's start year. Nothing here inflation-adjusts them.
"""

import pandas as pd

from app.models.career import CareerSalary, SalaryStats, YearlySalary

SENIORITY_ORDER = ["Entry", "Mid", "Senior", "Lead", "Manager", "Director"]


def salary_stats(salaries: pd.Series, start_dates: pd.Series | None = None) -> SalaryStats | None:
    values = pd.to_numeric(salaries, errors="coerce").dropna()
    if values.empty:
        return None
    years = None
    if start_dates is not None:
        years = pd.to_datetime(start_dates.loc[values.index]).dt.year
    return SalaryStats(
        sample_size=int(values.size),
        median=round(float(values.median())),
        p25=round(float(values.quantile(0.25))),
        p75=round(float(values.quantile(0.75))),
        min=int(values.min()),
        max=int(values.max()),
        start_year_min=int(years.min()) if years is not None else None,
        start_year_max=int(years.max()) if years is not None else None,
    )


def career_salary(employment: pd.DataFrame, career: str) -> CareerSalary:
    spells = employment[employment["job_family"] == career]
    entry = spells[spells["seniority_level"] == "Entry"]

    by_seniority: dict[str, SalaryStats] = {}
    for level in SENIORITY_ORDER:
        level_spells = spells[spells["seniority_level"] == level]
        stats = salary_stats(level_spells["annual_salary_usd"], level_spells["start_date"])
        if stats is not None:
            by_seniority[level] = stats

    by_year: list[YearlySalary] = []
    if not entry.empty:
        years = pd.to_datetime(entry["start_date"]).dt.year
        for year, group in entry.groupby(years):
            by_year.append(
                YearlySalary(
                    start_year=int(year),
                    sample_size=len(group),
                    median=round(float(group["annual_salary_usd"].median())),
                )
            )

    return CareerSalary(
        career=career,
        entry_level=salary_stats(entry["annual_salary_usd"], entry["start_date"]),
        all_levels=salary_stats(spells["annual_salary_usd"], spells["start_date"]),
        by_seniority=by_seniority,
        entry_level_by_start_year=by_year,
    )
