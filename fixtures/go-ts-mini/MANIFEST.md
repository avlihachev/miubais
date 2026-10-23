# MANIFEST

provenance: original
as_of: 2026-10-17

Every file in this fixture was written for the course; nothing is copied from another code base.
Each pull request is a unified diff against the fixture root plus a `meta.json`.

| pr | title | author | created_at | approvals | touches |
| --- | --- | --- | --- | --- | --- |
| pr-01 | Show the due date in the web client | aino | 2026-10-15 | 1 | web, changelog |
| pr-02 | Add a turnaround priority to jobs | bruno | 2026-10-14 | 2 | proto, Go, changelog |
| pr-03 | Drop the unused pagination fields from ListJobs | chen | 2026-10-13 | 1 | proto, changelog |
| pr-04 | Find overdue jobs | dara | 2026-10-14 | 2 | migrations, Go |
| pr-05 | Give new jobs a default due date | emil | 2026-10-15 | 2 | migrations, Go, changelog |
| pr-06 | Change the translator of a pending job | aino | 2026-10-16 | 1 | Go |
| pr-07 | Accept estimated hours from the CSV import in formatHours | bruno | 2026-10-16 | 1 | web, changelog |
| pr-08 | Authenticate the web client and add create() | chen | 2026-10-16 | 1 | web, changelog |
| pr-09 | Make cancel idempotent | dara | 2026-10-15 | 1 | Go, changelog |
| pr-10 | Mark error responses as not cacheable | emil | 2026-10-12 | 1 | Go, changelog |
| pr-11 | Extract status filtering and saving in the service | aino | 2026-09-20 | 0 | Go |
| pr-12 | Use camelCase for createdAt in job responses | bruno | 2026-10-16 | 2 | Go, web, changelog |
