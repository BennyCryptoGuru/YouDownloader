from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from backend.core.security import verify_header_token
from backend.domain.models import JobCreateRequest

router = APIRouter(prefix="/api/v1", tags=["jobs"])


@router.get("/jobs")
async def list_jobs(request: Request) -> dict:
    verify_header_token(request.app.state.config.session_token, request.headers.get("X-Session-Token"))
    return {"jobs": await request.app.state.downloads.list_jobs()}


@router.post("/jobs")
async def create_job(payload: JobCreateRequest, request: Request) -> dict:
    verify_header_token(request.app.state.config.session_token, request.headers.get("X-Session-Token"))
    return {"job": await request.app.state.downloads.create_job(payload)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict:
    verify_header_token(request.app.state.config.session_token, request.headers.get("X-Session-Token"))
    return {"job": await request.app.state.downloads.get_job(job_id)}


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str, request: Request) -> dict:
    verify_header_token(request.app.state.config.session_token, request.headers.get("X-Session-Token"))
    return {"job": await request.app.state.downloads.pause_job(job_id)}


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str, request: Request) -> dict:
    verify_header_token(request.app.state.config.session_token, request.headers.get("X-Session-Token"))
    return {"job": await request.app.state.downloads.resume_job(job_id)}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request) -> dict:
    verify_header_token(request.app.state.config.session_token, request.headers.get("X-Session-Token"))
    return {"job": await request.app.state.downloads.cancel_job(job_id)}


@router.post("/jobs/{job_id}/retry-failed")
async def retry_failed(job_id: str, request: Request) -> dict:
    verify_header_token(request.app.state.config.session_token, request.headers.get("X-Session-Token"))
    return {"job": await request.app.state.downloads.retry_failed(job_id)}


@router.delete("/jobs/{job_id}", status_code=204)
async def remove_job(job_id: str, request: Request) -> Response:
    verify_header_token(request.app.state.config.session_token, request.headers.get("X-Session-Token"))
    await request.app.state.downloads.remove_job(job_id)
    return Response(status_code=204)
