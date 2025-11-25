import os
import socket
import subprocess
import json
import signal
import time
import shlex
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware

from models import StudentSpec
from db import (
    save_or_update_student,
    list_students,
    delete_student,
    get_student,
    update_student_status,
)
from k8s import (
    create_namespace,
    create_pod,
    get_pod_status,
    delete_pod,
    delete_namespace,
    check_resources_available,
)

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
STUDENT_POD_IMAGE = os.environ.get("STUDENT_POD_IMAGE", "student-web:latest")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# -------------------------------------------------------------------
# App + CORS
# -------------------------------------------------------------------
app = FastAPI(title="Student Deployer Control API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# Admin guard
# -------------------------------------------------------------------
def ensure_admin(x_admin_key: str | None):
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=500, detail="ADMIN_PASSWORD not configured")
    if x_admin_key != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")

# -------------------------------------------------------------------
# Port-forward helpers
# -------------------------------------------------------------------
PF_DIR = Path("/tmp/student_pf")
PF_DIR.mkdir(parents=True, exist_ok=True)

def _pidfile(name: str) -> Path:
    return PF_DIR / f"{name}.json"

def _is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.15)
        return s.connect_ex(("127.0.0.1", port)) != 0

def _next_free_port(start: int = 8001, end: int = 9000) -> int:
    for p in range(start, end + 1):
        if _is_port_free(p):
            return p
    raise RuntimeError("No free local port found in range 8001-9000")

def _save_pf(name: str, pid: int, port: int):
    _pidfile(name).write_text(json.dumps({"name": name, "pid": pid, "port": port}))

def _load_pf(name: str):
    f = _pidfile(name)
    if f.exists():
        return json.loads(f.read_text())
    return None

def _kill_pid(pid: int):
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(10):
        time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

# -------------------------------------------------------------------
# Health
# -------------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True}

@app.get("/")
def root():
    return {
        "ok": True,
        "service": "Student Deployer API",
        "routes": ["/docs", "/health", "/submit", "/deploy", "/deploy-from-db", "/status", "/cleanup"]
    }

# @app.get("/favicon.ico")
# def favicon():
#     return {"ok": True}

# -------------------------------------------------------------------
# Submit: validate resources and persist to MongoDB
# -------------------------------------------------------------------
@app.post("/submit")
def submit(spec: StudentSpec):
    """Validate resources against cluster capacity, then save to MongoDB."""
    # Check if resources are available in cluster
    resource_check = check_resources_available(spec.cpu, spec.memory, spec.storage)# calls k8s for to check resource
    
    if not resource_check["available"]:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Insufficient cluster resources",
                "message": resource_check["message"],
                "requested": resource_check["details"].get("requested", {}),
                "available": resource_check["details"].get("available", {}),
                "suggestion": "Please reduce your CPU, Memory, or Storage request and try again."
            }
        )
    
    # Resources are available, save to MongoDB
    doc = spec.to_persisted_doc()# calls models , coverts the value to db format
    try:
        save_or_update_student(doc, status="pending") #calls db
        return {
            "status": "queued",
            "student": spec.name,
            "message": "Request validated and saved. Resources are available for deployment."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

# -------------------------------------------------------------------
# Deploy: create namespace + pod (also saves to DB)
# -------------------------------------------------------------------
@app.post("/deploy")
def deploy(spec: StudentSpec):
    """Deploy a pod directly from the provided spec."""
    # Check if pod already exists
    existing_phase = get_pod_status(namespace=spec.name, name=spec.name) # call k8s
    if existing_phase != "Not Found":
        raise HTTPException(
            status_code=409,
            detail=f"Pod already exists with status: {existing_phase}. Delete it first or use a different name."
        )

    doc = spec.to_persisted_doc() #calls models
    save_or_update_student(doc, status="pending") #calls db

    r = spec.to_k8s_resources()# calls models
    ns = spec.name
    pod_base = spec.name

    try:
        create_namespace(ns) # calls k8s
        create_pod(
            namespace=ns,
            name=pod_base,
            image=STUDENT_POD_IMAGE,
            cpu_qty=r["cpu"],
            memory_qty=r["memory"],
            storage_qty=spec.storage,
        ) #calls k8s
        phase = get_pod_status(namespace=ns, name=pod_base)# calls k8s
        update_student_status(spec.name, status="deployed") # calls db
    except Exception as e:
        update_student_status(spec.name, status="failed", error=str(e))  #calls db
        raise HTTPException(status_code=500, detail=f"K8s error: {e}")

    return {
        "status": "deploying",
        "namespace": ns,
        "pod": f"{pod_base}-pod",
        "image": STUDENT_POD_IMAGE,
        "requested": r,
        "phase": phase,
    }

# -------------------------------------------------------------------
# Deploy from DB: read spec from MongoDB and deploy
# -------------------------------------------------------------------
@app.post("/deploy-from-db")
def deploy_from_db(name: str = Query(..., description="Student name / namespace")):
    """Deploy a pod using data previously saved in MongoDB. Handles cluster failures gracefully."""
    doc = get_student(name) # calls db
    if not doc:
        raise HTTPException(status_code=404, detail="Student not found in MongoDB")

    k8s = doc.get("k8s_resources") or {}
    cpu = k8s.get("cpu")
    memory = k8s.get("memory")
    storage_str = k8s.get("storage", "1Gi")
    
    # Extract numeric storage value
    storage_gb = int(storage_str.replace("Gi", ""))
    
    if not cpu or not memory:
        raise HTTPException(status_code=500, detail="Stored doc missing k8s_resources.cpu/memory")

    ns = name
    pod_base = name

    # Check if cluster is accessible
    try:
        existing_phase = get_pod_status(namespace=name, name=name) #calls k8s
        if existing_phase != "Not Found":
            raise HTTPException(
                status_code=409,
                detail=f"Pod already exists with status: {existing_phase}. Delete it first or use a different name."
            )
    except RuntimeError as e:
        # Cluster is down or unreachable
        update_student_status(name, status="pending", error=f"Cluster unreachable: {e}") # calls db
        raise HTTPException(
            status_code=503,
            detail=f"Kubernetes cluster is unreachable. Request saved as pending. Error: {e}"
        )

    try:
        create_namespace(ns) # calls k8s
        create_pod(
            namespace=ns,
            name=pod_base,
            image=STUDENT_POD_IMAGE,
            cpu_qty=cpu,
            memory_qty=memory,
            storage_qty=storage_gb,
        )# calls k8s
        phase = get_pod_status(namespace=ns, name=pod_base)  # class k8s
        update_student_status(name, status="deployed")# calls db
    except Exception as e:
        update_student_status(name, status="failed", error=str(e)) # calls db
        raise HTTPException(status_code=500, detail=f"K8s error: {e}")

    return {
        "status": "deploying-from-db",
        "namespace": ns,
        "pod": f"{pod_base}-pod",
        "image": STUDENT_POD_IMAGE,
        "requested": k8s,
        "phase": phase,
    }

# -------------------------------------------------------------------
# Status: get pod phase
# -------------------------------------------------------------------
@app.get("/status")
def status(name: str = Query(..., description="Student name / namespace")):
    """Get the current Kubernetes pod status."""
    try:
        phase = get_pod_status(namespace=name, name=name)   # calls k8s
        return {"student": name, "pod": f"{name}-pod", "status": phase}
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Pod not found or error: {e}")

# -------------------------------------------------------------------
# Admin: list students from MongoDB (with automatic status sync)
# -------------------------------------------------------------------
@app.get("/admin/students")
def admin_students(x_admin_key: str | None = Header(None)):
    """List all students from MongoDB with live Kubernetes status and automatic sync."""
    ensure_admin(x_admin_key)
    out = []
    
    # Check if cluster is accessible
    cluster_accessible = True
    try:
        from k8s import _ensure_k8s
        _ensure_k8s()       #calls k8s
    except Exception:
        cluster_accessible = False
    
    for d in list_students():   #calls db
        nm = d.get("name", "")
        db_status = d.get("status", "unknown")
        
        # Try to get live pod status and auto-sync if needed
        if cluster_accessible:
            try:
                phase = get_pod_status(namespace=nm, name=nm)  # calls k8s
                d["live_phase"] = phase
                
                # Auto-sync mismatched statuses
                if phase == "Running" and db_status == "pending":
                    update_student_status(nm, status="deployed")   # calls db
                    d["status"] = "deployed"  # Update the returned data
                elif phase == "Not Found" and db_status in ("deployed", "pending"):
                    update_student_status(nm, status="failed", error="Pod not found")  # calls db
                    d["status"] = "failed"
                    
            except Exception:
                d["live_phase"] = "Not Found"
                # If pod check fails and status is pending, mark as failed
                if db_status == "pending":
                    update_student_status(nm, status="failed", error="Cannot check pod status") # calls db
                    d["status"] = "failed"
        else:
            d["live_phase"] = "Cluster Down"
        
        # Add current DB status for display
        d["db_status"] = d.get("status", "unknown")
        out.append(d)
    
    return out

# -------------------------------------------------------------------
# Admin: cleanup K8s (pod/namespace) AND remove DB record
# -------------------------------------------------------------------
@app.delete("/cleanup")
def cleanup(name: str = Query(...), x_admin_key: str | None = Header(None)):
    """Delete pod, namespace, and MongoDB record."""
    ensure_admin(x_admin_key)
    try:
        delete_pod(namespace=name, name=name)#this line call kubernetes k8s
    except Exception:
        pass
    try:
        delete_namespace(name)#  call  k8s
    except Exception:
        pass
    deleted = delete_student(name)# call db
    return {"deleted": name, "db_deleted": bool(deleted)}



# -------------------------------------------------------------------
# Port-forward: start
# -------------------------------------------------------------------
@app.post("/pf/start")
def pf_start(name: str = Query(...), target_port: int = 8000, local_port: int | None = None):
    """Start kubectl port-forward for a student pod."""
    if not name.strip():
        raise HTTPException(status_code=400, detail="name required")

    existing = _load_pf(name)
    if existing:
        return {
            "status": "already-forwarding",
            "name": name,
            "local_port": existing["port"],
            "url": f"http://127.0.0.1:{existing['port']}/"
        }

    lp = local_port if local_port else _next_free_port(8001, 9000)

    cmd = [
        "kubectl",
        "port-forward",
        "-n", name,
        f"pod/{name}-pod",
        f"{lp}:{target_port}",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Wait for port to open
    ok = False
    for _ in range(20):
        time.sleep(0.15)
        if proc.poll() is not None:
            break
        if not _is_port_free(lp):
            ok = True
            break

    if not ok:
        try:
            err = (proc.stderr.read().decode("utf-8", "ignore") if proc.stderr else "").strip()
        except Exception:
            err = ""
        try:
            _kill_pid(proc.pid)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to start port-forward (port={lp}). {err}")

    _save_pf(name, proc.pid, lp)
    return {"status": "forwarding", "name": name, "local_port": lp, "url": f"http://127.0.0.1:{lp}/"}


# -------------------------------------------------------------------
# Port-forward: stop all
# -------------------------------------------------------------------
@app.post("/pf/stop_all")
def pf_stop_all():
    """Stop all active port-forwards."""
    stopped = []
    for f in PF_DIR.glob("*.json"):
        try:
            info = json.loads(f.read_text())
            _kill_pid(info.get("pid", 0))
        except Exception:
            pass
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass
        stopped.append(info.get("name", f.stem))
    return {"status": "stopped-all", "names": stopped}

# -------------------------------------------------------------------
# Port-forward: list
# -------------------------------------------------------------------
@app.get("/pf/list")
def pf_list():
    """List all active port-forwards."""
    out = []
    for f in PF_DIR.glob("*.json"):
        try:
            info = json.loads(f.read_text())
            out.append(info)
        except Exception:
            pass
    return out






# -------------------------------------------------------------------
# Port-forward: stop
# -------------------------------------------------------------------
# @app.post("/pf/stop")
# def pf_stop(name: str = Query(...)):
#     """Stop port-forward for a specific student."""
#     info = _load_pf(name)
#     if not info:
#         return {"status": "not-found", "name": name}
#     _kill_pid(info["pid"])
#     try:
#         _pidfile(name).unlink(missing_ok=True)
#     except Exception:
#         pass
#     return {"status": "stopped", "name": name}