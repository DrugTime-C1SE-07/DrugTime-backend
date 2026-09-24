# ponytail: split into domain routers under app/routers; main entrypoint exposes app.
try:
    from app.main import app
except ImportError:
    from fastapi import FastAPI
    app = FastAPI(title="DrugTime API", version="1.0.0")

def health_check():
    return {"status": "ok", "service": "drugtime-api"}

if __name__ == "__main__":
    res = health_check()
    assert res["status"] == "ok", "Health check failed"
    print("Health check sanity passed.")
    if app:
        import uvicorn
        uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
    else:
        print("FastAPI not installed yet. Run: pip install -r requirements.txt")

