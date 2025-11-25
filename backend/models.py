from pydantic import BaseModel, Field, field_validator

# Kubernetes DNS-1123 label (lowercase, digits, hyphen; 1–63 chars)
DNS_LABEL = r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"

class StudentSpec(BaseModel):
    # NOTE: name becomes the Kubernetes namespace, so it must be DNS-1123 compliant
    name: str = Field(min_length=1, max_length=63, pattern=DNS_LABEL)

    # 👉 Numeric inputs from the UI / Swagger:
    # cpu = number of cores (e.g., 0.25, 0.5, 1, 2, ...)
    # memory = megabytes (e.g., 256, 512, 1024)
    # storage = gigabytes (e.g., 1, 5, 10)
    cpu: float
    memory: int
    storage: int

    @field_validator("cpu")
    @classmethod
    def _cpu_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("cpu must be > 0 (cores, e.g., 0.5 or 1)")
        return v

    @field_validator("memory", "storage")
    @classmethod
    def _pos_int(cls, v: int, info) -> int:
        if v <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return v

    def to_k8s_resources(self) -> dict:
        """
        Convert numeric inputs into Kubernetes resource strings:
          - cpu: 0.5 cores -> "500m", 1.0 -> "1"
          - memory: MB -> "Mi"
          - storage: GB -> "Gi"
        """
        # CPU: <1 core => millicores, else integer cores
        if self.cpu < 1:
            cpu_str = f"{int(round(self.cpu * 1000))}m"
        else:
            # allow values like 1.0 or 2.0 → "1", "2"
            cpu_str = str(int(round(self.cpu)))

        mem_str = f"{int(self.memory)}Mi"       # MB → Mi
        storage_str = f"{int(self.storage)}Gi"  # GB → Gi

        return {"cpu": cpu_str, "memory": mem_str, "storage": storage_str}

    def to_persisted_doc(self) -> dict:
        """
        What we store to MongoDB: both the numeric inputs and the
        computed Kubernetes strings (handy for auditing/demo).
        """
        k = self.to_k8s_resources()
        return {
            "name": self.name,
            "input_numeric": {
                "cpu": self.cpu,
                "memory_mb": self.memory,
                "storage_gb": self.storage,
            },
            "k8s_resources": k,
        }
