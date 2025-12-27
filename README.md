# Cognitive Reinforcement Backend

Minimal FastAPI backend for adaptive cognitive reinforcement workflows.

## Features
- Patient, family, and knowledge management backed by Azure SQL (SQLAlchemy).
- Blob uploads for documents and photos with optional Cosmos ingestion logging.
- Azure OpenAI-powered quiz generation with adaptive scheduling and mastery tracking.
- API-key authentication via `X-API-KEY` header.

## Setup
1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Copy environment template:
   ```bash
   cp env.example .env
   ```
3. Fill in `.env` with your secrets. **Do not commit `.env`.**
4. Run the server:
   ```bash
   uvicorn main:app --reload
   ```

## Environment Variables
See `env.example` for all required values. Ensure `AZURE_OPENAI_DEPLOYMENT_NAME` is set to your deployment/model name.

## Curl Examples
Replace `YOUR_API_KEY` with `APP_API_KEY`.

Health:
```bash
curl http://localhost:8000/health
```

Create patient:
```bash
curl -X POST http://localhost:8000/patients \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: YOUR_API_KEY" \
  -d '{"full_name":"Jane Doe","dob":"1950-01-01","phone":"123","address":"Somewhere"}'
```

List patients:
```bash
curl -H "X-API-KEY: YOUR_API_KEY" http://localhost:8000/patients
```

Generate quiz:
```bash
curl -X POST "http://localhost:8000/patients/{patient_id}/quiz/generate?n=3" \
  -H "X-API-KEY: YOUR_API_KEY"
```

Submit quiz:
```bash
curl -X POST http://localhost:8000/quiz/{session_id}/submit \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: YOUR_API_KEY" \
  -d '[{"question_id":"...","user_answer":"answer","response_time_ms":1200}]'
```

## Testing
Run pytest:
```bash
pytest
```
