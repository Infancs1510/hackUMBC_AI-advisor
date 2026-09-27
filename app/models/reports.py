from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Cell = str | int | float | None
ReportCategory = Literal["Advising", "Triage", "Curriculum", "Careers", "Activity"]

REPORT_NOTE = (
    "Reports are built from the HackUMBC synthetic dataset and this app's own records. "
    "Each saved report is a snapshot of the data when it was generated."
)


class ReportMetric(BaseModel):
    label: str
    value: str


class ReportChartBar(BaseModel):
    label: str
    value: int


class ReportInfo(BaseModel):
    key: str
    title: str
    category: ReportCategory
    description: str
    columns: list[str]
    metric: ReportMetric
    chart: list[ReportChartBar] = Field(default_factory=list, description="Optional preview bars (top rows).")


class DataSnapshot(BaseModel):
    records_as_of: str
    current_term: str
    next_term: str
    students: int
    alumni: int
    transcript_rows: int
    employment_rows: int
    appointments: int
    meeting_requests: int
    plans: int
    reviews: int


class ReportCatalog(BaseModel):
    reports: list[ReportInfo]
    snapshot: DataSnapshot
    notice: str = REPORT_NOTE


class ReportRunSummary(BaseModel):
    id: int
    key: str
    title: str
    category: ReportCategory
    row_count: int
    generated_at: datetime
    generated_by: str


class ReportRun(ReportRunSummary):
    columns: list[str]
    rows: list[list[Cell]]


class ReportHistory(BaseModel):
    runs: list[ReportRunSummary]
    kept: int = Field(description="How many recent reports are kept; older ones are removed.")
