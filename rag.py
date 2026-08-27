import glob
import http.client
import json
import logging
import os
import re

logger = logging.getLogger(__name__)


def split_markdown_headers(text, skip_prefixes, skip_headers):
    """Split markdown text on headers and return list of contents with metadata."""
    headers = [("###", "H3"), ("##", "H2"), ("#", "H1")]
    sections = []
    hierarchy = {}
    current_lines = []
    current_metadata = {}
    skip_section = None
    for line in text.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(p) for p in skip_prefixes):
            continue
        prefix, name = next(((prefix, name) for prefix, name in headers if line.startswith(prefix + " ")), (None, None))
        if name:
            level = len(prefix)
            title = line[level:].strip()
            if skip_section is not None:
                if level <= skip_section:
                    skip_section = None
                else:
                    continue
            if title in skip_headers or stripped in skip_headers:
                current_lines = []
                skip_section = level
                continue
            if current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    sections.append([content, current_metadata])
            hierarchy = {k: v for k, v in hierarchy.items() if k < level}
            hierarchy[level] = title
            current_metadata = {name: hierarchy[len(prefix)] for prefix, name in headers if len(prefix) in hierarchy}
            current_lines = [line]
        elif skip_section is None:
            current_lines.append(line)
    if current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append([content, current_metadata])

    return sections


def extract_list_entries(text):
    """Extract list entries from markdown text"""
    items = []
    current_item = []
    for line in text.splitlines():
        if line.strip().startswith("- "):
            if current_item:
                items.append("\n".join(current_item).strip())
                current_item = []
            current_item.append(line)
        elif current_item:
            current_item.append(line)
    if current_item:
        items.append("\n".join(current_item).strip())
    return items


def split_chunks(data, size=1200, overlap=150):
    """Split text to chunks with overlap"""
    result = []
    for text, metadata in data:
        if len(text) <= size:
            result.append([text, metadata.copy()])
            continue
        parts = re.split(r"(\n\n|\n| )", text)
        chunks = []
        current = ""
        for part in parts:
            if len(current) + len(part) <= size:
                current += part
            else:
                if current:
                    chunks.append(current.strip())
                while len(part) > size:
                    chunks.append(part[:size])
                    part = part[size - overlap:]   # noqa
                current = part
        if current.strip():
            chunks.append(current.strip())
        for i, chunk in enumerate(chunks):
            if i > 0:
                chunk = chunks[i - 1][-overlap:] + chunk   # noqa
            result.append([chunk, metadata.copy()])
    return result


class RAGEngine:
    """RAG engine class"""

    def __init__(
        self, embed_model, docs_dir, db_file="vectors.json", server_host="localhost", server_port=11434, skip_files=[], list_files=[], skip_prefixes=[], skip_headers=[]):
        self.docs_dir = docs_dir
        self.db_file = db_file
        self.embed_model = embed_model
        self.server_host = server_host
        self.server_port = server_port
        self.skip_files = skip_files
        self.list_files = list_files
        self.skip_prefixes = skip_prefixes
        self.skip_headers = skip_headers
        self.database = []


    def get_embeddings(self, texts):
        """Get embeddings from ollama server"""
        payload = json.dumps({"model": self.embed_model, "input": texts})
        try:
            connection = http.client.HTTPConnection(self.server_host, self.server_port)
            connection.request("POST", "/api/embed", body=payload, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            data = json.loads(response.read().decode("utf-8"))
            connection.close()
            return data.get("embeddings", [])
        except Exception as e:
            logger.error(f"Failed to fetch embeddings: {e}")
            return []


    def load(self):
        """Load vectors from json, or index docs if missing"""
        if os.path.exists(self.db_file):
            with open(self.db_file, "r", encoding="utf-8") as f:
                self.database = json.load(f)
            return True

        logger.info(f"Building RAG vector database from: {self.docs_dir}")
        files = glob.glob(f"{self.docs_dir}/**/*.md", recursive=True)
        if not files:
            logger.warning(f"No markdown documentation found in {self.docs_dir}!")
            return False

        database = []
        for file in files:
            filename = os.path.basename(file)
            filename_lower = filename.lower()
            if any(target.lower() in filename_lower for target in self.skip_files):
                continue
            with open(file, "r", encoding="utf-8") as f:
                sections = split_markdown_headers(f.read(), self.skip_prefixes, self.skip_headers)

            chunks = []
            if any(target.lower() in filename_lower for target in self.list_files):   # special handling for long lists
                for section in sections:
                    list_entries = extract_list_entries(section[0])
                    if not list_entries:
                        chunks.append(section)
                        continue
                    for entry in list_entries:
                        chunks.append([entry, section[1]])
            else:
                chunks = split_chunks(sections, size=1200, overlap=150)

            texts = []
            for chunk in chunks:
                headers = [v for v in chunk[1].values() if v]
                breadcrumb = f"[File: {filename} > {" > ".join(headers)}]" if headers else f"[File: {filename}]"
                texts.append(f"{breadcrumb}\n\n{chunk[0]}")

            for i in range(0, len(texts), 10):
                text_batch = texts[i:i + 10]
                meta_batch = chunks[i:i + 10]
                embeddings = self.get_embeddings(text_batch)
                for text, meta_doc, vector in zip(text_batch, meta_batch, embeddings):
                    database.append({"text": text, "metadata": meta_doc[1], "embedding": vector})

        with open(self.db_file, "w", encoding="utf-8") as f:
            json.dump(database, f)
        self.database = database
        logger.info(f"Successfully indexed {len(self.database)} RAG entries")
        return True


    def retrieve(self, query, top=3):
        """Get top N embeddings for given query"""
        if not self.database:
            return []
        query_vectors = self.get_embeddings([query])
        if not query_vectors:
            return []
        query_vector = query_vectors[0]
        results = []
        for doc in self.database:
            score = sum(a * b for a, b in zip(query_vector, doc["embedding"]))
            results.append((score, doc["text"]))
        results.sort(key=lambda x: x[0], reverse=True)
        return [text for _, text in results[:top]]
