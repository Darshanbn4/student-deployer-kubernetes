from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"msg": "Hello from your student pod! 🎓,/health,/info"}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/info")
def info():
    return {
        "app": "Student Web Server",
        "owner": "Deployed by the Student Deployer system",
    }