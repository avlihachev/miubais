from serving_lab_lessons.finetune import adapter_share, effective_batch, optimizer_steps

d, ff = 4096, 14336
layer = [(d, d)] * 4 + [(d, ff), (d, ff), (ff, d)]
for rank in (8, 16, 64):
    a = adapter_share(layer, rank)
    print(
        f"rank {rank:>2}: {a['lora']:>9,} trainable of {a['full']:,} per layer ({a['share']:.2%})"
    )

batch = effective_batch(per_device=2, accumulation=4)
print(f"effective batch {batch}; max_steps = 60 sees {60 * batch} examples")
for epochs in (1, 3):
    print(f"1,000 examples, {epochs} epoch(s): {optimizer_steps(1000, batch, epochs)} steps")
