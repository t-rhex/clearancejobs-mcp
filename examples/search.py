"""Public search example: no Keychain or account access. Requires service authorization."""

from clearancejobs import search

if __name__ == "__main__":
    result = search("devops", state="FL", limit=5)
    for job in result["data"]:
        print(job["job_name"], job["company_name"], job["job_url"], sep=" | ")
