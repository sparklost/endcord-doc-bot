# endcord-doc-bot
An extension for [endcord](https://github.com/sparklost/endcord) discord TUI client, that implements LLM-powered documentation using llama-server or ollama.  
This extension is intended **for bots only**.  

## Installing
See [official extensions documentation](https://github.com/sparklost/endcord/blob/main/docs/extensions.md#installing-extensions) for installing instructions.
Available options:
- Git clone into `Extensions` directory located in endcord config directory.
- Run `endcord -i https://github.com/sparklost/endcord-doc-bot`
- Or use endcord client-side command `install_extension sparklost/endcord-doc-bot`

## Usage
- Send `!doc my query message` (or whatever you set for triggers) in configured channels, Bot will respond with top_k number of top matching documentation entries.
- Use `!doc-4` (or any other single-digit number) to tell bot to respond with that number of matching entries.
- Use `!doc-ai some question message` to get LLM rephrased answer with source link.

## Configuration
All extension options are under `[main]` section in endcord config. This extension options are always prefixed with `ext_doc_bot_`.  
Either ollama or llama-server is required to be running at configured address.  
After updating the source repository run `docbot-update` client command to update local repository and regenerate RAG database.

### Settings options
- `ext_doc_bot_trigger_doc = "!doc"`  
    Trigger string for pure documentation search without any LLM processing.  
    Messages starting with this string will be searched in the RAG database.  
    `@me` is special token meaning this bot mention at the start of the message.
- `ext_doc_bot_trigger_ai = "!doc-ai"`  
    Same as above trigger, but here, retrieved entries from RAG will be put through LLM with system prompt and user query.
- `ext_doc_bot_send_typing = True`  
    Whether to send "typing..." status to current chat.
- `ext_doc_bot_reply = False`  
    Whether to send response as a reply.
- `ext_doc_bot_reply_ping = True`  
    Whether to send reply with a ping.
- `ext_doc_bot_max_typing = 120`  
    Longest period of time the bot can be sending "typing..." status. Value is in seconds.
- `ext_doc_bot_limit_msg_len = 1000`  
    Limit to the message size in characters. Hard limit is 2000 as that's how much discord allows. Will affect response generation speed.
- `ext_doc_bot_listen_channels = []`  
    List of channel IDs where to monitor messages. IDs must be strings (`"12345"`).
- `ext_doc_bot_listen_guilds = []`  
    List of server IDs where to monitor messages. IDs must be strings (`"12345"`).
    Overrides `ext_notify_mention_listen_channel` if channels are from same server.
- `ext_doc_bot_source_docs_dir = [endcord_config]/docbot`  
    Directory containing source documentation, or this is where repo from `ext_doc_bot_source_repo` will be saved.
- `ext_doc_bot_source_repo = None`  
    Github repository containing source documentation that will be downloaded and saved to `ext_doc_bot_source_docs_dir`.
    If None then `ext_doc_bot_source_docs_dir` is expected to contain source documentation.
- `ext_doc_bot_server_host = "localhost"`  
    Address at which OpenAI-compatible llm server is running.
- `ext_doc_bot_server_port = 11434`  
    Port at which OpenAI-compatible llm server is running.
- `ext_doc_bot_embed_host = "localhost"`  
    Address at which OpenAI-compatible embedding server is running.  
    This is intended for llama-server, since it cant handle multiple simultaneous models.  
    If this is ollama, then same server can be used for bot embedding and main llm.
- `ext_doc_bot_embed_port = 11434`  
    Port at which OpenAI-compatible embedding server is running.
- `ext_doc_bot_openrouter_token = None`  
    OpenRouter bearer token string. This only overrides model for LLM inference, **NOT for embedding**.  
    Embedding still has to be configured through ollama.
- `ext_doc_bot_embed_model = None`  
    Model used for embedding, also from ollama.
- `ext_doc_bot_rag_top_k = 3`  
    How many entries to retrieve from RAG. Used both in AI and non-AI modes.
- `ext_doc_bot_skip_files = []`  
    What files to skip. Use only file names.  
- `ext_doc_bot_list_files = []`  
    What files to treat as long lists. Lists are considered to have many lines starting with `- `.  
    These lists will be added to rag as all items individually.
- `ext_doc_bot_skip_prefix = ["<"]`  
    Skip lines starting with this strings.
- `ext_doc_bot_skip_headers" = ["Features", "License"]`  
    Skip these entire headers.
- `ext_doc_bot_model = None`  
    What LLM model to use, it mus be installed in the backend.
    Must be exact model name from `ollama list`.
- `ext_doc_bot_system_prompt = SYSTEM_PROMPT`  
    System prompt for LLM. Default is:
    "You are a helpful documentation assistant.\n\nInstructions: Answer using ONLY the provided context."
- `ext_doc_bot_limit_prompt = 1500`  
    Limit to the prompt passed to LLM.
- `ext_doc_bot_llm_temp = 0.2`  
    Temperature of LLM response.
- `ext_doc_bot_llm_top_p = 0.9`
    Top_p of LLM response.
- `ext_doc_bot_llm_repeat_penalty = 1.0`  
    Repeat penalty of LLM response.


## Disclaimer
> [!WARNING]
> Using third-party client is against Discord's Terms of Service and may cause your account to be banned!  
> **Use endcord and/or this extension at your own risk!**  
> If this extension is modified, it may be used for harmful or unintended purposes.  
> **The developer is not responsible for any misuse or for actions taken by users.**  
