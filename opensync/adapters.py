"""Bounded source adapters. Adapters return complete snapshots or raise."""
from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile
import xml.etree.ElementTree as ET

MAX_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 128 * 1024 * 1024
MAX_DOCUMENTS = 10000
TEXT = set(".txt .md .mdx .markdown .rst .adoc .csv .tsv .json .jsonl .xml .yaml .yml .toml .ini .cfg .conf .log .html .htm .py .pyi .js .jsx .ts .tsx .mjs .cjs .go .rs .sql .c .h .cpp .hpp .java .kt .swift .sh .bash .zsh .fish .rb .php .css .scss .svelte .vue .tex .r .ipynb".split())
NAMES = {"README", "LICENSE", "Dockerfile", "Makefile", "Justfile"}
IGNORE = {"node_modules", "__pycache__", "target", "dist", "build", "venv", "vendor"}
SECRET = {".pem", ".key", ".p12", ".pfx", ".sqlite", ".db"}
HIDDEN_TAGS = {"script", "style", "head", "template", "noscript", "svg"}
BLOCK_TAGS = {"p", "div", "article", "section", "br", "li", "tr", "h1", "h2", "h3", "h4", "pre"}


@dataclass(frozen=True)
class Document:
    location: str
    title: str
    body: str


class HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = []
        self.in_title = False
        self.title = []

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag in HIDDEN_TAGS:
            self.hidden.append(tag)
        if tag in BLOCK_TAGS and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in self.hidden:
            # Handle imperfect HTML without permanently hiding the body.
            self.hidden = self.hidden[:self.hidden.index(tag)]
        if tag in BLOCK_TAGS and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        if not self.hidden:
            self.parts.append(data)


def normalize(value: str, base: Path | None = None) -> tuple[str, str]:
    """Stable source identity; local paths may be missing during later refreshes."""
    if not value.strip():
        raise ValueError("Source cannot be empty.")
    if value.startswith("git+"):
        uri = value[4:]
        p = urlsplit(uri)
        if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ValueError("Git sources use git+https://host/owner/repo.git without credentials or query strings.")
        return "git+" + urlunsplit(("https", p.netloc.lower(), p.path.rstrip("/"), "", "")), "git"
    p = urlsplit(value)
    # Windows drive letters and paths containing ':' remain local paths.
    if p.scheme.lower() in {"http", "https"}:
        if not p.hostname or p.username is not None or p.password is not None:
            raise ValueError("Use HTTP(S) URLs without embedded credentials.")
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", p.query, "")), "url"
    if "://" in value:
        raise ValueError("Supported schemes: http://, https://, git+https://; otherwise supply a local path.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    return str(path.resolve()), "local"


def limited(stream) -> bytes:
    data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Document exceeds the 16 MiB limit.")
    return data


def extract(raw: bytes, location: str, suffix: str = "", encoding: str = "utf-8-sig", html: bool = False) -> Document:
    title = Path(urlsplit(location).path).name or location
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("PDF support requires installing opensync-kb[pdf]. Scanned PDFs require external OCR.") from exc
        from io import BytesIO
        reader = PdfReader(BytesIO(raw))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif suffix == ".docx":
        from io import BytesIO
        with zipfile.ZipFile(BytesIO(raw)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_BYTES:
                raise ValueError("Expanded DOCX exceeds the 16 MiB limit.")
            tree = ET.fromstring(z.read(info))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        text = "\n".join("".join(p.itertext()) for p in tree.findall(".//w:p", ns))
    else:
        text = raw.decode(encoding)
        if "\x00" in text:
            raise ValueError(f"Binary content is unsupported: {location}")
        if html or suffix in {".htm", ".html"}:
            parser = HTMLText()
            parser.feed(text)
            parser.close()
            text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
            title = "".join(parser.title).strip() or title
        elif suffix in {".md", ".mdx", ".markdown"}:
            heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
            if heading:
                title = heading[1].strip()
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"Extracted text exceeds the 16 MiB limit: {location}")
    return Document(location, title, text)


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        normalize(newurl)
        if urlsplit(newurl).scheme not in {"http", "https"}:
            raise ValueError("Redirect target must use HTTP(S).")
        if urlsplit(req.full_url).scheme == "https" and urlsplit(newurl).scheme != "https":
            raise ValueError("Refusing an HTTPS to HTTP redirect.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def web_document(uri: str) -> Document:
    request = Request(uri, headers={"User-Agent": "OpenSync/0.1 (+local knowledge base)", "Accept-Encoding": "identity"})
    with build_opener(SafeRedirect()).open(request, timeout=25) as response:
        mime = response.headers.get_content_type().lower()
        suffix = Path(urlsplit(uri).path).suffix.lower()
        supported = mime.startswith("text/") or mime.endswith(("+json", "+xml")) or mime in {
            "application/json", "application/xml", "application/yaml", "application/x-yaml", "application/x-ndjson",
            "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        if not supported:
            raise ValueError(f"Unsupported HTTP content type: {mime}")
        if mime == "application/pdf":
            suffix = ".pdf"
        elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            suffix = ".docx"
        return extract(limited(response), uri, suffix, response.headers.get_content_charset() or "utf-8-sig", mime in {"text/html", "application/xhtml+xml"})


def local_documents(root: Path):
    if root.is_symlink():
        raise ValueError("Choose the real path rather than a symbolic link.")
    if not root.exists():
        raise FileNotFoundError(f"Source is missing; keeping its last good snapshot: {root}")
    patterns = []
    if root.is_dir() and (root / ".opensyncignore").is_file():
        patterns = [s.strip() for s in (root / ".opensyncignore").read_text().splitlines() if s.strip() and not s.lstrip().startswith("#")]

    def ignored(path):
        rel = path.relative_to(root).as_posix()
        return any(fnmatch.fnmatch(rel, pat.rstrip("/")) or fnmatch.fnmatch(path.name, pat.rstrip("/")) for pat in patterns)

    def fail(exc):
        raise exc

    if root.is_file():
        paths = [root]
    elif root.is_dir():
        paths = []
        for base, dirs, files in os.walk(root, onerror=fail, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in IGNORE and not (Path(base) / d).is_symlink() and not ignored(Path(base) / d))
            for name in sorted(files):
                path = Path(base) / name
                if not name.startswith(".") and not path.is_symlink() and not ignored(path) and (path.suffix.lower() in TEXT | {".pdf", ".docx"} or name in NAMES):
                    paths.append(path)
                    if len(paths) > MAX_DOCUMENTS:
                        raise ValueError("Source exceeds the 10,000 document limit; select smaller folders.")
    else:
        raise ValueError("Source must be a regular file or folder.")
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Source entry is not a regular file: {path}")
        if path.suffix.lower() in SECRET or path.name.startswith("."):
            raise ValueError(f"Private or database files are excluded: {path.name}")
        if path.suffix.lower() not in TEXT | {".pdf", ".docx"} and path.name not in NAMES:
            raise ValueError(f"Unsupported file extension: {path.suffix or '(none)'}")
        with path.open("rb") as stream:
            yield extract(limited(stream), str(path), path.suffix.lower())


def git_documents(uri: str, home: Path):
    cache = home / "repos" / hashlib.sha256(uri.encode()).hexdigest()[:24]
    if cache.parent.is_symlink() or cache.is_symlink():
        raise ValueError("Git cache paths must be real directories, not symlinks.")
    cache.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    # No shell, credential prompts, repository hooks, or submodule execution.
    prefix = ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "credential.helper="]
    def run(args):
        proc = subprocess.run(prefix + args, capture_output=True, text=True, timeout=120, env=env)
        if proc.returncode:
            raise RuntimeError("Git synchronization failed: " + proc.stderr.strip()[-1000:])
    if not cache.exists():
        run(["clone", "--depth=1", "--no-tags", "--", uri[4:], str(cache)])
    else:
        run(["-C", str(cache), "fetch", "--depth=1", "origin"])
        run(["-C", str(cache), "reset", "--hard", "FETCH_HEAD"])
        run(["-C", str(cache), "clean", "-fd"])
    for doc in local_documents(cache):
        relative = Path(doc.location).relative_to(cache).as_posix()
        yield Document(uri + "#" + relative, doc.title, doc.body)


def snapshot(uri: str, kind: str, home: Path) -> list[Document]:
    iterator = iter([web_document(uri)]) if kind == "url" else git_documents(uri, home) if kind == "git" else local_documents(Path(uri))
    documents, total = [], 0
    for doc in iterator:
        total += len(doc.body.encode("utf-8"))
        if total > MAX_SNAPSHOT_BYTES or len(documents) >= MAX_DOCUMENTS:
            raise ValueError("Source exceeds snapshot limits (128 MiB / 10,000 documents).")
        documents.append(doc)
    return documents
