from fastapi import APIRouter, Depends

from app.ai.backboard import BackboardMemory
from app.ai.gemini import GeminiClient
from app.api.deps import get_gemini, get_memory, get_store
from app.data.loader import DataStore

router = APIRouter(tags=["health"])


@router.get("/health")
def health(
    store: DataStore = Depends(get_store),
    gemini: GeminiClient = Depends(get_gemini),
    memory: BackboardMemory = Depends(get_memory),
) -> dict:
    return {
        "status": "ok",
        "data": {
            "students": len(store.students),
            "alumni": len(store.alumni),
            "transcript_rows": len(store.transcripts),
            "courses": len(store.catalog),
            "experience_rows": len(store.experiences),
            "employment_rows": len(store.employment),
        },
        "services": {
            "gemini": {
                "configured": gemini.configured,
                "model": gemini.model,
                "fallback_model": getattr(gemini, "fallback_model", None),
            },
            "backboard": {"configured": memory.configured},
        },
    }
