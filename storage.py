"""Azure Blob and optional Cosmos logging helpers."""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from azure.storage.blob import BlobServiceClient  # type: ignore
    from azure.cosmos import CosmosClient  # type: ignore

from dotenv import load_dotenv
from fastapi import UploadFile

load_dotenv()


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name


def _get_blob_client() -> BlobServiceClient:
    from azure.storage.blob import BlobServiceClient  # type: ignore

    conn = os.getenv("BLOB_CONNECTION_STRING")
    if not conn:
        raise RuntimeError("BLOB_CONNECTION_STRING not configured")
    return BlobServiceClient.from_connection_string(conn)


def _ensure_container(client: BlobServiceClient, name: str):
    container = client.get_container_client(name)
    if not container.exists():
        container.create_container()
    return container


def _cosmos_client() -> Optional[CosmosClient]:
    try:
        from azure.cosmos import CosmosClient  # type: ignore
    except ImportError:
        return None
    endpoint = os.getenv("COSMOS_ENDPOINT")
    key = os.getenv("COSMOS_KEY")
    if not endpoint or not key:
        return None
    return CosmosClient(endpoint, credential=key)


async def upload_patient_document(patient_id: str, file: UploadFile) -> str:
    blob_client = _get_blob_client()
    container = _ensure_container(blob_client, "patient-docs")
    fname = _safe_filename(file.filename or "upload")
    blob_name = f"patient-docs/{patient_id}/{uuid.uuid4()}_{fname}"
    blob = container.get_blob_client(blob_name)
    content = await file.read()
    blob.upload_blob(content, overwrite=True)
    _log_cosmos(patient_id, blob_name, fname)
    return blob_name


async def upload_family_photo(patient_id: str, family_id: str, file: UploadFile) -> str:
    blob_client = _get_blob_client()
    container = _ensure_container(blob_client, "patient-photos")
    blob_name = f"patient-photos/{patient_id}/{family_id}/{uuid.uuid4()}.jpg"
    content = await file.read()
    container.upload_blob(name=blob_name, data=content, overwrite=True)
    return blob_name


def _log_cosmos(patient_id: str, blob_path: str, filename: str):
    client = _cosmos_client()
    if not client:
        return
    from azure.cosmos import PartitionKey  # type: ignore

    database = client.create_database_if_not_exists(id="reinforce_db")
    container = database.create_container_if_not_exists(
        id="ingestion_logs", partition_key=PartitionKey(path="/patient_id")
    )
    container.upsert_item(
        {
            "id": str(uuid.uuid4()),
            "patient_id": patient_id,
            "blob_path": blob_path,
            "filename": filename,
            "uploaded_at": datetime.utcnow().isoformat(),
        }
    )
