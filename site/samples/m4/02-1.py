from retrieval_lab_lessons import toy_chunk

doc = """# Runbook

Restart the worker when the queue backs up.

## Deploy

Tag the release first.

~~~bash
./deploy.sh --env prod

# rollback if the error rate rises
./deploy.sh --rollback
~~~

Watch the error rate.

Page the on-call engineer.

Write the incident note.
"""
for c in toy_chunk("runbook", doc, max_chars=60, overlap=1):
    body = c.text.replace("\n", "\\n")
    print(f"{c.chunk_id} [{c.start_char}:{c.end_char}] {c.heading_path!r}")
    print(f"  {len(c.text):>3} chars  {body[:58]}")
