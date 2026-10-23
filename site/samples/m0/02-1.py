from dataclasses import dataclass

GB = 1e9


@dataclass(frozen=True)
class Model:
    name: str
    layers: int
    kv_heads: int
    head_dim: int
    bytes_per_value: float

    @property
    def kv_bytes_per_token(self) -> float:
        return 2 * self.layers * self.kv_heads * self.head_dim * self.bytes_per_value


WEIGHTS_BYTES = 70e9 * 2
KV_BUDGET_BYTES = 400 * GB
MODELS = [
    Model("70B GQA, bf16 KV", 80, 8, 128, 2),
    Model("70B GQA, fp8 KV", 80, 8, 128, 1),
    Model("70B if MHA, bf16 KV", 80, 64, 128, 2),
]
CONTEXTS = [8_192, 32_768, 131_072, 1_000_000]


def bytes_read_per_token(model: Model, batch: int, context: int) -> float:
    # one decode step streams the weights once for the whole batch plus every sequence's own KV cache
    return WEIGHTS_BYTES / batch + context * model.kv_bytes_per_token


for m in MODELS:
    print(f"{m.name}: {m.kv_bytes_per_token / 1024:.0f} KiB per token")
    for ctx in CONTEXTS:
        per_seq = ctx * m.kv_bytes_per_token
        fits = int(KV_BUDGET_BYTES // per_seq)
        print(f"  {ctx:>9,} tokens: {per_seq / GB:7.1f} GB per sequence, {fits:4d} fit in 400 GB")

base = MODELS[0]
print("bytes read per generated token, 70B GQA bf16:")
for batch, ctx in [(1, 8_192), (64, 8_192), (9, 131_072)]:
    print(
        f"  batch {batch:>3}, context {ctx:>7,}: {bytes_read_per_token(base, batch, ctx) / GB:6.1f} GB"
    )
