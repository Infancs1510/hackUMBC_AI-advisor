from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import require_advisor
from app.models.reports import ReportCatalog, ReportHistory, ReportRun
from app.services.reports import KEEP_RUNS, SPECS, ReportContext, ReportError, ReportStore, build_report, report_catalog

router = APIRouter(tags=["reports"], dependencies=[Depends(require_advisor)])


def _context(request: Request) -> ReportContext:
    state = request.app.state
    return ReportContext(
        store=state.store, caseload=state.caseload.get(), appointments=state.appointments,
        advising=state.advising, plans=state.plans,
    )


def get_reports(request: Request) -> ReportStore:
    return request.app.state.reports


@router.get("/reports", response_model=ReportCatalog)
def catalog(request: Request) -> ReportCatalog:
    """Available reports with a headline figure each, plus what the data covers."""
    return report_catalog(_context(request))


@router.post("/reports/{key}/runs", response_model=ReportRun, status_code=201)
def generate(key: str, request: Request, reports: ReportStore = Depends(get_reports)) -> ReportRun:
    """Build a report from current data and save it as a snapshot."""
    if key not in SPECS:
        raise ReportError(f"Unknown report: {key}", 404)
    return reports.save(key, build_report(_context(request), key), request.app.state.advising.advisor)


@router.get("/report-runs", response_model=ReportHistory)
def history(reports: ReportStore = Depends(get_reports)) -> ReportHistory:
    return ReportHistory(runs=reports.history(), kept=KEEP_RUNS)


@router.get("/report-runs/{run_id}", response_model=ReportRun)
def get_run(run_id: int, reports: ReportStore = Depends(get_reports)) -> ReportRun:
    return reports.get(run_id)


@router.delete("/report-runs/{run_id}", status_code=204)
def delete_run(run_id: int, reports: ReportStore = Depends(get_reports)) -> Response:
    reports.delete(run_id)
    return Response(status_code=204)
