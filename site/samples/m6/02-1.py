from serving_lab_lessons.engine_budget import budget

qwen35_27b = {"params": 27e9, "attention_layers": 16, "kv_heads": 4, "head_dim": 256}
h100 = {"gpu_gb": 80, "utilization": 0.92, "overhead_gb": 5}
contexts = [262_144, 32_768, 8_192]

print("weights KV    weights GB  KV GB  KiB/token   KV tokens  sequences at 256K / 32K / 8K")
for weights, bits, kv_dtype, kv_bytes in [
    ("bf16", 16, "bf16", 2),
    ("fp8", 8, "bf16", 2),
    ("fp8", 8, "fp8", 1),
    ("int4", 4, "fp8", 1),
]:
    b = budget(**h100, **qwen35_27b, bits_per_weight=bits, kv_bytes_per_value=kv_bytes)
    fits = " / ".join(str(b.sequences(c)) for c in contexts)
    print(
        f"{weights:<7} {kv_dtype:<5} {b.weights_gb:>10.1f} {b.kv_gb:>6.1f}"
        f" {b.kv_kib_per_token:>10.0f} {b.kv_tokens:>11,}  {fits}"
    )
