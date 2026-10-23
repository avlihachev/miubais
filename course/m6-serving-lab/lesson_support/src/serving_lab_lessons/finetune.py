def lora_params(d_in: int, d_out: int, rank: int) -> int:
    return rank * (d_in + d_out)


def adapter_share(shapes: list[tuple[int, int]], rank: int) -> dict:
    full = sum(d_in * d_out for d_in, d_out in shapes)
    lora = sum(lora_params(d_in, d_out, rank) for d_in, d_out in shapes)
    return {"full": full, "lora": lora, "share": lora / full}


def effective_batch(per_device: int, accumulation: int, devices: int = 1) -> int:
    return per_device * accumulation * devices


def optimizer_steps(examples: int, batch: int, epochs: int) -> int:
    return -(-examples // batch) * epochs
