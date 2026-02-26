"""ClearLedger Cloud — AI-сервер для обработки документов.

Принимает batch от контейнеров клиентов, классифицирует, нормализует.
"""

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

from cloud.config import verify_api_key
from cloud.classifier import classify_document

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cloud")

app = FastAPI(
    title="ClearLedger Cloud",
    version="0.1.0",
    description="AI-обработка документов",
)


class BatchItem(BaseModel):
    raw_entry_id: str
    file_name: str
    mime_type: str
    extracted_text: str
    extracted_fields: dict = {}
    company_id: str = ""


class BatchRequest(BaseModel):
    instance_id: str
    batch: list[BatchItem]


class ProcessResult(BaseModel):
    raw_entry_id: str
    classification: dict
    normalized_metadata: dict
    decision: str
    model_version: str
    rejection_reason: str | None = None


class BatchResponse(BaseModel):
    results: list[ProcessResult]


@app.post("/api/process", response_model=BatchResponse)
async def process_batch(
    request: BatchRequest,
    authorization: str = Header(default=""),
):
    """Обработка пакета документов от instance клиента."""
    # Проверка API-ключа
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    if not verify_api_key(token):
        raise HTTPException(status_code=401, detail="Неверный API-ключ")

    logger.info(
        "Запрос от instance %s: %d документов",
        request.instance_id,
        len(request.batch),
    )

    results = []
    for item in request.batch:
        result = await classify_document(
            file_name=item.file_name,
            mime_type=item.mime_type,
            extracted_text=item.extracted_text,
            extracted_fields=item.extracted_fields,
            company_id=item.company_id,
        )
        results.append(ProcessResult(
            raw_entry_id=item.raw_entry_id,
            classification=result["classification"],
            normalized_metadata=result["normalized_metadata"],
            decision=result["decision"],
            model_version=result["model_version"],
        ))

    logger.info(
        "Обработано: %d accepted, %d needs_review, %d rejected",
        sum(1 for r in results if r.decision == "accepted"),
        sum(1 for r in results if r.decision == "needs_review"),
        sum(1 for r in results if r.decision == "rejected"),
    )

    return BatchResponse(results=results)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0", "service": "cloud"}
