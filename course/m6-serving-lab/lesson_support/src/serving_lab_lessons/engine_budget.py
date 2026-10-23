from dataclasses import dataclass

GB = 1e9


@dataclass(frozen=True)
class Budget:
    weights_gb: float
    kv_gb: float
    kv_tokens: int
    kv_kib_per_token: float

    def sequences(self, context_tokens: int) -> int:
        return self.kv_tokens // context_tokens


def weight_bytes(params: float, bits_per_weight: float) -> float:
    return params * bits_per_weight / 8


def kv_bytes_per_token(
    attention_layers: int, kv_heads: int, head_dim: int, bytes_per_value: float
) -> float:
    return 2 * attention_layers * kv_heads * head_dim * bytes_per_value


def budget(
    *,
    gpu_gb: float,
    utilization: float,
    params: float,
    bits_per_weight: float,
    overhead_gb: float,
    attention_layers: int,
    kv_heads: int,
    head_dim: int,
    kv_bytes_per_value: float,
) -> Budget:
    weights = weight_bytes(params, bits_per_weight)
    kv = gpu_gb * GB * utilization - weights - overhead_gb * GB
    per_token = kv_bytes_per_token(attention_layers, kv_heads, head_dim, kv_bytes_per_value)
    return Budget(
        weights_gb=weights / GB,
        kv_gb=max(kv, 0.0) / GB,
        kv_tokens=int(max(kv, 0.0) // per_token),
        kv_kib_per_token=per_token / 1024,
    )
