import collections
import gzip
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path

root = Path.cwd()
problems = []
tracked = subprocess.check_output(
    ["git", "ls-files", "--cached", "--others", "--exclude-standard"], text=True
).splitlines()
paths = [Path(p) for p in sorted(set(tracked)) if Path(p).is_file()]
links = 0
for p in paths:
    if p.suffix != ".md" or "09-19-console-readiness/evidence" in str(p):
        continue
    code = False
    for n, line in enumerate(p.read_text().splitlines(), 1):
        if line.lstrip().startswith(chr(96) * 3):
            code = not code
            continue
        if code:
            continue
        for m in re.finditer(r"\]\(([^)]+)\)", line):
            target = m.group(1).split(" ")[0].strip("<>")
            file, _, anchor = target.partition("#")
            if re.match(r"^[a-zA-Z][\w+.-]*:", target) or target.startswith("/"):
                continue
            links += 1
            q = (p.parent / file).resolve() if file else p.resolve()
            if not q.exists():
                problems.append(f"{p}:{n}: missing {target}")
            elif anchor and q.suffix == ".md":
                body = q.read_text()
                ids = set(re.findall(r'<a id="([^"]+)"', body))
                for heading in body.splitlines():
                    if heading.startswith("#"):
                        h = re.sub(r"[^\w\-\s]", "", heading.lstrip("# ").lower()).replace(" ", "-")
                        ids.add(h)
                if anchor not in ids:
                    problems.append(f"{p}:{n}: unknown anchor {target}")
tasks = list(Path(".trellis/tasks").glob("*/task.json"))
ids = collections.Counter()
for p in tasks:
    d = json.loads(p.read_text())
    ids[d["id"]] += 1
    if not d.get("status"):
        problems.append(f"{p}: missing status")
for id, count in ids.items():
    if count > 1:
        problems.append(f"duplicate task ID {id}")
for p in Path(".trellis/tasks").iterdir():
    if p.is_dir() and not (p / "task.json").is_file():
        problems.append(f"missing metadata: {p}")
manifest = json.loads(Path("docs/archive/document-migrations.json").read_text())
for item in manifest["entries"]:
    before = subprocess.check_output(
        ["git", "show", item["source_revision"] + ":" + item["old_path"]]
    )
    if hashlib.sha256(before).hexdigest() != item["source_sha256"]:
        problems.append("source hash: " + item["old_path"])
    if "archived_path" in item:
        p = Path(item["archived_path"])
        data = p.read_bytes()
        if hashlib.sha256(data).hexdigest() != item["archived_sha256"]:
            problems.append("archive hash: " + str(p))
        body = data.decode().split("\n\n", 1)[1]

        def normalize(text: str) -> str:
            return re.sub(r"\]\([^)]+\)", "](TARGET)", text)

        if normalize(body) != normalize(before.decode()):
            problems.append("archive body drift: " + str(p))
index = Path("docs/archive/README.md").read_text()
for p in Path("docs/archive").glob("*.md"):
    if p.name != "README.md" and p.name not in index:
        problems.append("archive index omission: " + str(p))
index = Path("docs/README.md").read_text()
for p in Path("docs").glob("*.md"):
    if p.name != "README.md" and p.name not in index:
        problems.append("docs index omission: " + str(p))
base = Path(".trellis/tasks/09-19-console-readiness/evidence")
evidence = json.loads((base / "manifest.json").read_text())
for item in evidence["files"]:
    stored = (base / item["path"]).read_bytes()
    if item.get("encoding") == "gzip":
        if hashlib.sha256(stored).hexdigest() != item["stored_sha256"]:
            problems.append("stored evidence hash: " + item["path"])
        original = gzip.decompress(stored)
    else:
        original = stored
    if hashlib.sha256(original).hexdigest() != item["sha256"]:
        problems.append("evidence hash: " + item["path"])
packed = evidence["reproductions"]
data = (base / packed["path"]).read_bytes()
if hashlib.sha256(data).hexdigest() != packed["sha256"]:
    problems.append("reproduction archive hash")
with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as bundle:
    if {p["member"] for p in packed["members"]} != {m.name for m in bundle.getmembers()}:
        problems.append("reproduction members")
    for item in packed["members"]:
        if hashlib.sha256(bundle.extractfile(item["member"]).read()).hexdigest() != item["sha256"]:
            problems.append("reproduction hash: " + item["member"])
candidate = subprocess.check_output(
    ["git", "show", evidence["integration_revision"] + ":src/ai_software_engineer/team_view/app.js"]
)
if hashlib.sha256(candidate).hexdigest() != evidence["candidate_app_sha256"]:
    problems.append("candidate hash")
subprocess.run(["git", "diff", "--check"], check=True)
result = {
    "markdown_links_checked": links,
    "task_metadata_checked": len(tasks),
    "archive_snapshots_checked": 3,
    "source_documents_checked": len(manifest["entries"]),
    "immutable_reports_and_logs_checked": len(evidence["files"]),
    "reproduction_scripts_checked": len(packed["members"]),
    "problems": problems,
}
print(json.dumps(result, ensure_ascii=False, indent=2))
Path(".trellis/tasks/09-19-documentation-cleanup/verification.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n"
)
if problems:
    raise SystemExit(1)
