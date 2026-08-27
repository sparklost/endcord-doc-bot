import http.client
import json
import logging
import os
import queue
import re
import shutil
import threading
import time

from endcord import git, peripherals

from rag import RAGEngine

EXT_NAME = "LLM Doc Bot"
EXT_VERSION = "0.1.2"
EXT_ENDCORD_VERSION = "1.5.0"
EXT_DESCRIPTION = "An extension that that implements LLM-powered documentation using ollama"
EXT_SOURCE = "https://github.com/sparklost/endcord-doc-bot"
EXT_COMMAND_ASSIST = (("docbot_update - Update docs to latest git commit for documentation bot", "docbot_update"),)
logger = logging.getLogger(__name__)

MAX_MSG_SIZE = 2000   # max by discord
SYSTEM_PROMPT = "You are a helpful documentation assistant.\n\nInstructions: Answer using ONLY the provided context."


def find_relative_path(search_dir, filename):
    """Find relative path for given file in a dir"""
    for root, dirs, files in os.walk(search_dir):
        if filename in files:
            full_path = os.path.join(root, filename)
            return os.path.relpath(full_path, start=search_dir)
    return None


def build_doc_embed(chunks, ai_time, model, repo, search_dir):
    """Build embed for pure document retrieval results"""
    if not chunks:
        return [{
            "type": "rich",
            "title": "Documentation Search",
            "description": "No relevant documentation found.",
            "color": 0xCC375F,  # red
        }]

    fields = []
    for i, chunk in enumerate(chunks):
        source = chunk.split("\n\n", 1)[0][6:].strip().rstrip("]")
        content_text = chunk.split("\n\n", 1)[1].strip()
        lines = content_text.split("\n", 1)
        breadcrumb = source.lstrip("/").replace("/", " > ").replace("\\", " > ")

        filename = source.split(" > ")[0].lstrip("/")
        rel_path = find_relative_path(search_dir, filename)
        file_url = f"{repo.rstrip("/")}/blob/main/{rel_path}"
        if lines and lines[0].startswith("#"):
            heading = re.sub(r"[^a-z0-9\s-]", "", lines[0].lstrip("#").strip().lower()).replace(" ", "-")
            file_url += f"#{heading}" if heading else ""
            content_text = lines[1].strip() if len(lines) > 1 else ""
        content_text = f"**Result #{i+1}: [{breadcrumb}]({file_url})**\n\n{content_text}"

        if len(content_text) > 1000:
            content_text = content_text[:997] + "..."
        fields.append({
            "name": " ",
            "value": content_text or "*No content*",
            "inline": False,
        })

    model = model.split("/")[-1].split(":")[0].replace("GGUF", "").strip("-")
    return [{
        "type": "rich",
        "title": "Documentation Search",
        "color": 0x854675,   # purple
        "fields": fields[:25],
        "footer": {
            "text": f"{model} • {round(ai_time, 3)}s",
        },
    }]


def build_ai_embed(reply, chunks, ai_time, model, repo, search_dir):
    """Constructs a structured embed for LLM generated responses."""
    sources = set()
    for chunk in chunks:
        source = chunk.split("\n\n", 1)[0][6:].strip().rstrip("]")
        lines = chunk.split("\n\n", 1)[1].strip().split("\n", 1)
        filename = source.split(" > ")[0].lstrip("/")
        rel_path = find_relative_path(search_dir, filename)
        file_url = f"{repo.rstrip("/")}/blob/main/{rel_path}"
        if lines and lines[0].startswith("#"):
            heading = re.sub(r"[^a-z0-9\s-]", "", lines[0].lstrip("#").strip().lower()).replace(" ", "-")
            file_url += f"#{heading}" if heading else ""
        sources.add(f"[{filename}]({file_url})")
    sources_str = ", ".join(sorted(sources))

    if len(reply) > 4000:
        reply = reply[:3997] + "..."
    model = model.split("/")[-1].split(":")[0].replace("GGUF", "").strip("-")
    return [{
        "type": "rich",
        "title": "AI Assistant Answer",
        "description": reply,
        "color": 0xFB86C0,  # pink
        "fields": [
            {
                "name": "Sources",
                "value": sources_str,
                "inline": True,
            },
        ],
        "footer": {
            "text": f"{model} • {round(ai_time, 3)}s",
        },
    }]


class Extension:
    """Main extension class"""

    def __init__(self, app):
        self.app = app

        self.trigger_doc = app.config.get("ext_doc_bot_trigger_doc", "!doc")
        self.trigger_ai = app.config.get("ext_doc_bot_trigger_ai", "!doc-ai")
        send_typing = bool(app.config.get("ext_doc_bot_send_typing", True))
        self.reply = bool(app.config.get("ext_doc_bot_reply", False))
        self.ping = bool(app.config.get("ext_doc_bot_reply_ping", True))
        self.max_typing = int(app.config.get("ext_doc_bot_max_typing", 120))
        self.limit_msg = int(app.config.get("ext_doc_bot_limit_msg_len", 1000))
        self.limit_msg = min(max(self.limit_msg, 10), MAX_MSG_SIZE)

        self.listen_channels = app.config.get("ext_doc_bot_listen_channels", [])
        self.listen_guilds = app.config.get("ext_doc_bot_listen_guilds", [])

        self.docs_dir = app.config.get("ext_doc_bot_source_docs_dir", f"{os.path.expanduser(peripherals.config_path)}/docbot")
        self.source_repo = app.config.get("ext_doc_bot_source_repo", None)
        self.database_path = f"{os.path.expanduser(peripherals.config_path)}/docbot/vectors.json"

        self.server_host = app.config.get("ext_doc_bot_server_host", "localhost")
        self.server_port = int(app.config.get("ext_doc_bot_server_port", 11434))
        self.embed_host = app.config.get("ext_doc_bot_embed_host", "localhost")
        self.embed_port = int(app.config.get("ext_doc_bot_embed_port", 11434))
        self.openrouter_token = app.config.get("ext_doc_bot_openrouter_token", None)

        self.embed_model = app.config.get("ext_doc_bot_embed_model", None)
        self.top_k = int(app.config.get("ext_doc_bot_rag_top_k", 3))
        self.skip_files = app.config.get("ext_doc_bot_skip_files", [])
        self.list_files = app.config.get("ext_doc_bot_list_files", [])
        self.skip_prefix = app.config.get("ext_doc_bot_skip_prefix", ["<"])
        self.skip_headers = app.config.get("ext_doc_bot_skip_headers", ["Features", "License"])

        self.model = app.config.get("ext_doc_bot_model", None)
        self.system_prompt = app.config.get("ext_doc_bot_system_prompt", SYSTEM_PROMPT)
        self.limit_prompt = app.config.get("ext_doc_bot_limit_prompt", 1500)
        self.temp = app.config.get("ext_doc_bot_llm_temp", 0.2)
        self.top_p = app.config.get("ext_doc_bot_llm_top_p", 0.9)
        self.repeat_penalty = app.config.get("ext_doc_bot_llm_repeat_penalty", 1.0)

        self.rag = None
        self.typing_channel_id = None
        self.typing_sent = int(time.time())
        self.history = {}
        self.message_send_queue = queue.Queue()
        self.run = True

        if not self.app.token.startswith("Bot"):
            logger.info("Not running on user accounts!")
            self.run = False
            del (type(self).on_message_event, type(self).on_message_event_is_irrelevant, type(self).on_main_start)
            return

        # this takes a long time so do it in a thread
        threading.Thread(target=self.reload, daemon=True, args=(True, )).start()

        if send_typing:
            threading.Thread(target=self.typing_sender, daemon=True).start()


    def reload(self, boot=False):
        """Redownload repo and recreate embeddigs"""
        ext_data_dir = f"{os.path.expanduser(peripherals.config_path)}/docbot/"
        if not os.path.exists(ext_data_dir):
            os.makedirs(ext_data_dir, exist_ok=True)
        if self.source_repo and "github.com" in self.source_repo:
            repo = self.source_repo.strip("/").split("/")[-1]
            owner = self.source_repo.strip("/").split("/")[-2]
            self.docs_dir = f"{os.path.expanduser(peripherals.config_path)}/docbot/{repo}"
            if not boot:   # then force redownload
                if os.path.exists(self.database_path):
                    os.remove(self.database_path)
                if os.path.exists(self.docs_dir):
                    shutil.rmtree(self.docs_dir)
            if not os.path.exists(self.docs_dir):
                git.download_gh_repo(owner, repo, self.docs_dir, proxy=self.app.config["proxy"])
        if boot:
            self.rag = RAGEngine(
                docs_dir=self.docs_dir,
                db_file=self.database_path,
                embed_model=self.embed_model,
                server_host=self.embed_host,
                server_port=self.embed_port,
                skip_files=self.skip_files,
                list_files=self.list_files,
                skip_prefixes=self.skip_prefix,
                skip_headers=self.skip_headers,
            )
            self.rag.load()
            logger.info(f"Connecting to ollama at {self.server_host}:{self.server_port}")
            threading.Thread(target=self.worker, daemon=True).start()
        else:
            self.rag.load()


    def on_main_start(self):
        """At this point there is app.my_id so update triggers"""
        if self.trigger_doc.startswith("@me"):
            self.trigger_doc = self.trigger_doc[3:] + f"<@{self.app.my_id}>"
        if self.trigger_ai.startswith("@me"):
            self.trigger_ai = self.trigger_ai[3:] + f"<@{self.app.my_id}>"
        if not self.trigger_doc.endswith(" "):
            self.trigger_doc += " "
        if not self.trigger_ai.endswith(" "):
            self.trigger_ai += " "


    def typing_sender(self):
        """Thread that sends typing status"""
        while self.run:
            if self.typing_channel_id and time.time() >= self.typing_sent + 7:
                if int(time.time()) > self.typing_started + self.max_typing:
                    self.typing_channel_id = None
                self.typing_sent = int(time.time())
                self.app.discord.send_typing(self.typing_channel_id)
            else:
                time.sleep(0.1)


    def query_llm(self, user_prompt):
        """OpenAI-compatible inference for Ollama, llama-server, and OpenRouter"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self.limit_msg,  # Replaces Ollama's 'num_predict'
            "temperature": self.temp,
            "top_p": self.top_p,
            "repetition_penalty": self.repeat_penalty,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if self.openrouter_token:
            host = "openrouter.ai"
            port = 443
            path = "/api/v1/chat/completions"
            headers["Authorization"] = f"Bearer {self.openrouter_token}"
            use_https = True
        else:
            host = self.server_host
            port = self.server_port
            path = "/v1/chat/completions"
            use_https = False

        try:
            if use_https:
                conn = http.client.HTTPSConnection(host, port)
            else:
                conn = http.client.HTTPConnection(host, port)
            conn.request("POST", path, body=json.dumps(payload), headers=headers)
            res = conn.getresponse()
            res_body = res.read().decode("utf-8")
            conn.close()
            data = json.loads(res_body)
            if "choices" in data and len(data["choices"]) > 0:
                reply = data["choices"][0].get("message", {}).get("content", "")
                return reply if reply else "Error: Received empty string."
            logger.error(f"Unexpected response structure: {data}")
            return "Error: Unexpected API response format."
        except Exception as e:
            logger.error(f"LLM query failed: {e}")
            return f"Internal server error! {e}"


    def worker(self):
        """Worker thread that processes queries, retrieves context, and formats output."""
        while self.run:
            try:
                guild_id, channel_id, message_id, message_content, use_ai = self.message_send_queue.get()
                use_ai = use_ai and self.model
                self.typing_channel_id = channel_id
                self.typing_started = int(time.time())
                start_time = time.monotonic()
                doc_chunks = self.rag.retrieve(message_content, top=self.top_k)

                # build embed
                if not use_ai:
                    ai_time = time.monotonic() - start_time
                    embeds = build_doc_embed(doc_chunks, ai_time, self.embed_model, self.source_repo, self.docs_dir)
                else:
                    prompt_len = 216 + len(self.system_prompt) + len(message_content)
                    context_str = ""
                    for chunk in doc_chunks:
                        if len(context_str) > self.limit_prompt - prompt_len:
                            break
                        if context_str:
                            context_str += "\n\n---\n\n"
                        context_str += chunk[:self.limit_prompt - prompt_len]
                    user_prompt = (
                        f"Documentation Context:\n{context_str}\n\n"
                        f"Question:\n{message_content}"
                    )
                    reply = self.query_llm(user_prompt)
                    ai_time = time.monotonic() - start_time
                    embeds = build_ai_embed(reply, doc_chunks, ai_time, self.model, self.source_repo, self.docs_dir)

                # send message to discord
                self.typing_channel_id = None
                self.typing_started = None
                if self.reply:
                    self.app.discord.send_message(
                        channel_id=channel_id,
                        message_content="",
                        reply_id=message_id,
                        reply_channel_id=channel_id,
                        reply_guild_id=guild_id,
                        reply_ping=self.ping,
                        embeds=embeds,
                    )
                else:
                    self.app.discord.send_message(
                        channel_id=channel_id,
                        message_content="",
                        embeds=embeds,
                    )

            except Exception:
                self.typing_channel_id = None
                self.typing_started = None


    def on_message_event_is_irrelevant(self, message, optext):
        """Check if message is relevant or not"""
        if optext != "MESSAGE_CREATE":
            return False
        content = message["content"]
        if content.startswith(self.trigger_ai) or content.startswith(self.trigger_doc):
            return True
        return False


    def on_message_event(self, new_message):
        """Ran when message event is received"""
        data = new_message["d"]
        if data["channel_id"] not in self.listen_channels and data["guild_id"] not in self.listen_guilds:
            return

        if new_message["op"] == "MESSAGE_CREATE" and data["user_id"] != self.app.my_id and data["user_id"] not in self.app.blocked:
            raw_content = data["content"] + " "
            if raw_content.startswith(self.trigger_ai):
                use_ai = True
                content = raw_content[len(self.trigger_ai):].strip()
            elif raw_content.startswith(self.trigger_doc):
                use_ai = False
                content = raw_content[len(self.trigger_doc):].strip()
            else:
                return
            if not content and data["referenced_message"]:
                content = data["referenced_message"]["content"]
            if not content:
                return

            guild_id = data["guild_id"]
            channel_id = data["channel_id"]

            if logger.getEffectiveLevel() == logging.DEBUG:
                body = ""
                if guild_id:
                    for guild in self.app.guilds:
                        if guild["guild_id"] == guild_id:
                            body += f"[{guild["name"]}] "
                            break
                    for channel in guild["channels"]:
                        if channel["id"] == channel_id and channel.get("permitted"):
                            body += f"#{channel["name"]} - "
                            break
                body += f" {data.get("username")} used {"AI" if use_ai else "DOCS"}: {raw_content.strip()}"
                logger.debug(body)

            self.message_send_queue.put((guild_id, channel_id, data["id"], content, use_ai))


    def on_execute_command(self, command_text, chat_sel, tree_sel):   # noqa
        """Handle commands"""
        if command_text.startswith("docbot_update_wait"):
            self.reload(boot=False)
            return True
        if command_text.startswith("docbot_update"):
            threading.Thread(target=self.reload, daemon=True, args=(False, )).start()
            return True
        return False
