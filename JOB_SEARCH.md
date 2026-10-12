# Search prompt template

Replace the bracketed fields with your own requirements. Do not include passwords,
verification codes, classified information, or sensitive program details.

> Find my strongest new ClearanceJobs opportunities for [roles and skills].
> My experience is [years and relevant background], my current clearance is
> [clearance], and my preferred locations are [locations]. My work arrangement,
> salary, travel and relocation requirements are [preferences or unknown].
> Read every page of my application history and exclude those job IDs.
> Optionally read saved jobs and label existing leads. Search focused role names,
> deduplicate by job_id, and inspect full descriptions for promising matches.
> Check actual experience, education, clearance, work location, and salary
> requirements. Explain mismatches and unknowns. Return three to five matches
> with links and reasons. Do not apply or message anyone.

Only Florida has a verified state filter in this beta: use `state="FL"` when
requested, or omit it for nationwide search. Other states are not implemented.
Location keywords alone do not guarantee a location match. The Remote/Hybrid
filter includes hybrid jobs; verify the full description.

Read history once per search session and follow all pagination before claiming a
job is new. Site history may omit applications submitted elsewhere. Compare job
IDs, not application record IDs. Published salary ranges are not guaranteed
compensation. Missing salary or location details remain unknown.

Stop on rate limits and unresolved authentication errors. The tools do not submit
applications, save/unsave jobs, or send recruiter messages.
