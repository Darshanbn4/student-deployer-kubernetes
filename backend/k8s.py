"""Kubernetes helpers with lazy client/config initialization."""

from threading import Lock

# These globals are set when _ensure_k8s() successfully runs.
client = None
ApiException = None
_k8s_v1 = None
_k8s_lock = Lock()


def _ensure_k8s():
    """Initialize the kubernetes client (lazy)."""
    global client, ApiException, _k8s_v1
    if _k8s_v1 is not None:
        return

    try:
        from kubernetes import client as _client, config as _config
        from kubernetes.client.exceptions import ApiException as _ApiException
    except Exception as e:
        raise RuntimeError(f"kubernetes package not available: {e}")

    # Try user's kubeconfig, fall back to in-cluster (when running inside a pod)
    try:
        _config.load_kube_config()
    except Exception:
        try:
            _config.load_incluster_config()
        except Exception as e:
            raise RuntimeError(f"could not load kube config: {e}")

    client = _client
    ApiException = _ApiException
    _k8s_v1 = client.CoreV1Api()


def create_namespace(namespace_name: str):
    """Create the namespace if it doesn't exist."""
    _ensure_k8s()
    ns_body = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace_name))
    try:
        _k8s_v1.create_namespace(ns_body)   # CoreV1Api method
        print(f"✅ Namespace '{namespace_name}' created.")
    except ApiException as e:
        if e.status == 409:
            print(f"⚠️ Namespace '{namespace_name}' already exists.")
        else:
            raise


def create_pod(namespace: str, name: str, image: str, cpu_qty: str, memory_qty: str, storage_qty: int):
    """
    Create a pod with resource requests/limits.
    cpu_qty: e.g. '500m' (millicores)
    memory_qty: e.g. '512Mi'
    storage_qty: e.g. 1 (GB)
    """
    _ensure_k8s()
    resources = client.V1ResourceRequirements(
        requests={
            "cpu": cpu_qty,
            "memory": memory_qty,
            "ephemeral-storage": f"{storage_qty}Gi"
        },
        limits={
            "cpu": cpu_qty,
            "memory": memory_qty,
            "ephemeral-storage": f"{storage_qty}Gi"
        },
    )

    pod_manifest = client.V1Pod(
        metadata=client.V1ObjectMeta(name=f"{name}-pod"),
        spec=client.V1PodSpec(
            containers=[
                client.V1Container(
                    name="student-container",
                    image=image,
                    image_pull_policy="IfNotPresent",
                    ports=[client.V1ContainerPort(container_port=8000)],
                    resources=resources,
                )
            ]
        ),
    )

    try:
        _k8s_v1.create_namespaced_pod(namespace=namespace, body=pod_manifest)
        print(f"🚀 Pod '{name}-pod' created in namespace '{namespace}'.")
    except ApiException as e:
        if e.status == 409:
            print(f"⚠️ Pod '{name}-pod' already exists.")
        else:
            raise


def get_pod_status(namespace: str, name: str):
    """Return Pod phase (Pending, Running, etc.)."""
    _ensure_k8s()
    try:
        pod = _k8s_v1.read_namespaced_pod(name=f"{name}-pod", namespace=namespace)
        return pod.status.phase
    except ApiException as e:
        if e.status == 404:
            return "Not Found"
        raise


def delete_pod(namespace: str, name: str):
    """Delete a pod."""
    _ensure_k8s()
    try:
        _k8s_v1.delete_namespaced_pod(name=f"{name}-pod", namespace=namespace)
        print(f"🗑️  Pod '{name}-pod' deleted from '{namespace}'.")
    except ApiException as e:
        if getattr(e, "status", None) == 404:
            print("Pod not found (already gone).")
        else:
            raise


def delete_namespace(namespace: str):
    """Delete a namespace."""
    _ensure_k8s()
    try:
        _k8s_v1.delete_namespace(name=namespace)
        print(f"🗑️  Namespace '{namespace}' deletion requested.")
    except ApiException as e:
        if getattr(e, "status", None) == 404:
            print("Namespace not found (already gone).")
        else:
            raise



def get_cluster_resources():
    """Get total allocatable and currently available cluster resources."""
    _ensure_k8s()
    
    # Get node allocatable resources (total capacity)
    nodes = _k8s_v1.list_node().items
    if not nodes:
        raise RuntimeError("No nodes found in cluster")
    
    node = nodes[0]  # Single node minikube cluster
    allocatable = node.status.allocatable
    
    # Parse allocatable resources
    total_cpu_m = _parse_cpu_to_millicores(allocatable.get("cpu", "0"))
    total_memory_mi = _parse_memory_to_mi(allocatable.get("memory", "0"))
    total_storage_gi = _parse_storage_to_gi(allocatable.get("ephemeral-storage", "0"))
    
    # Calculate used resources from all pods (excluding system namespaces)
    used_cpu_m = 0
    used_memory_mi = 0
    used_storage_gi = 0
    
    skip_namespaces = {"kube-system", "kube-public", "kube-node-lease"}
    pods = _k8s_v1.list_pod_for_all_namespaces().items
    
    for pod in pods:
        if pod.metadata.namespace in skip_namespaces:
            continue
        if pod.status.phase not in ("Running", "Pending"):
            continue
            
        for container in pod.spec.containers:
            if container.resources and container.resources.requests:
                requests = container.resources.requests
                used_cpu_m += _parse_cpu_to_millicores(requests.get("cpu", "0"))
                used_memory_mi += _parse_memory_to_mi(requests.get("memory", "0"))
                used_storage_gi += _parse_storage_to_gi(requests.get("ephemeral-storage", "0"))
    
    # Calculate available
    available_cpu_m = total_cpu_m - used_cpu_m
    available_memory_mi = total_memory_mi - used_memory_mi
    available_storage_gi = total_storage_gi - used_storage_gi
    
    return {
        "total": {
            "cpu_millicores": total_cpu_m,
            "memory_mi": total_memory_mi,
            "storage_gi": total_storage_gi,
        },
        "used": {
            "cpu_millicores": used_cpu_m,
            "memory_mi": used_memory_mi,
            "storage_gi": used_storage_gi,
        },
        "available": {
            "cpu_millicores": available_cpu_m,
            "memory_mi": available_memory_mi,
            "storage_gi": available_storage_gi,
        }
    }


def _parse_cpu_to_millicores(cpu_str: str) -> int:
    """Convert CPU string to millicores. E.g., '2' -> 2000, '500m' -> 500"""
    if not cpu_str or cpu_str == "0":
        return 0
    if cpu_str.endswith("m"):
        return int(cpu_str[:-1])
    return int(float(cpu_str) * 1000)


def _parse_memory_to_mi(memory_str: str) -> int:
    """Convert memory string to MiB. E.g., '2Gi' -> 2048, '512Mi' -> 512, '1000Ki' -> ~1"""
    if not memory_str or memory_str == "0":
        return 0
    
    memory_str = memory_str.strip()
    if memory_str.endswith("Ki"):
        return int(int(memory_str[:-2]) / 1024)
    elif memory_str.endswith("Mi"):
        return int(memory_str[:-2])
    elif memory_str.endswith("Gi"):
        return int(memory_str[:-2]) * 1024
    elif memory_str.endswith("Ti"):
        return int(memory_str[:-2]) * 1024 * 1024
    else:
        # Assume bytes
        return int(int(memory_str) / (1024 * 1024))


def _parse_storage_to_gi(storage_str: str) -> int:
    """Convert storage string to GiB. E.g., '10Gi' -> 10, '1024Mi' -> 1"""
    if not storage_str or storage_str == "0":
        return 0
    
    storage_str = storage_str.strip()
    if storage_str.endswith("Ki"):
        return int(int(storage_str[:-2]) / (1024 * 1024))
    elif storage_str.endswith("Mi"):
        return int(int(storage_str[:-2]) / 1024)
    elif storage_str.endswith("Gi"):
        return int(storage_str[:-2])
    elif storage_str.endswith("Ti"):
        return int(storage_str[:-2]) * 1024
    else:
        # Assume bytes
        return int(int(storage_str) / (1024 * 1024 * 1024))


def check_resources_available(cpu_cores: float, memory_mi: int, storage_gi: int) -> dict:
    """
    Check if requested resources are available in the cluster.
    Returns dict with 'available' (bool) and 'message' (str).
    """
    try:
        resources = get_cluster_resources()
        available = resources["available"]
        
        # Convert requested CPU to millicores
        requested_cpu_m = int(cpu_cores * 1000)
        requested_memory_mi = memory_mi
        requested_storage_gi = storage_gi
        
        issues = []
        
        if requested_cpu_m > available["cpu_millicores"]:
            issues.append(
                f"CPU: requested {cpu_cores} cores ({requested_cpu_m}m), "
                f"available {available['cpu_millicores']/1000:.2f} cores ({available['cpu_millicores']}m)"
            )
        
        if requested_memory_mi > available["memory_mi"]:
            issues.append(
                f"Memory: requested {requested_memory_mi}Mi, "
                f"available {available['memory_mi']}Mi"
            )
        
        if requested_storage_gi > available["storage_gi"]:
            issues.append(
                f"Storage: requested {requested_storage_gi}Gi, "
                f"available {available['storage_gi']}Gi"
            )
        
        if issues:
            return {
                "available": False,
                "message": "Insufficient cluster resources. " + "; ".join(issues),
                "details": {
                    "requested": {
                        "cpu_cores": cpu_cores,
                        "memory_mi": requested_memory_mi,
                        "storage_gi": requested_storage_gi,
                    },
                    "available": available,
                }
            }
        
        return {
            "available": True,
            "message": "Resources available",
            "details": {
                "requested": {
                    "cpu_cores": cpu_cores,
                    "memory_mi": requested_memory_mi,
                    "storage_gi": requested_storage_gi,
                },
                "available": available,
            }
        }
    
    except Exception as e:
        return {
            "available": False,
            "message": f"Failed to check cluster resources: {e}",
            "details": {}
        }







# def list_pods_all():
#     """List all pods across namespaces (excluding system namespaces)."""
#     _ensure_k8s()
#     pods = _k8s_v1.list_pod_for_all_namespaces().items
#     out = []
#     skip = {"kube-system", "kube-public", "kube-node-lease"}
#     for p in pods:
#         ns = p.metadata.namespace or ""
#         if ns in skip:
#             continue
#         out.append({
#             "namespace": ns,
#             "pod": p.metadata.name,
#             "status": (p.status.phase or "Unknown")
#         })
#     return out