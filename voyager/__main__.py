import json
import os

from voyager import Voyager
from voyager.env import VoyagerEnv
from voyager.llm import (
    DEFAULT_BASE_URL,
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_NUM_CTX,
)


def _flag(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _port(name, default):
    raw = os.environ.get(name, default).strip()
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(f"{name} must be a TCP port, got {raw}")
    if value < 1 or value > 65535:
        raise SystemExit(f"{name} must be a TCP port, got {raw}")
    return value


def _connection():
    return {
        "mc_port": _port("MC_PORT", "25565"),
        "mc_host": os.environ.get("MC_HOST", "minecraft"),
        "mc_username": os.environ.get("MC_USERNAME", "bot"),
        "mc_version": os.environ.get("MC_VERSION", "1.21.1"),
    }


def smoke():
    env = VoyagerEnv(**_connection(), log_path=os.environ.get("LOG_PATH", "./logs"))
    events = env.reset(
        options={
            "mode": "soft",
            "wait_ticks": int(os.environ.get("ENV_WAIT_TICKS", "20")),
        }
    )
    observation = events[-1][1]
    status = observation.get("status", {})
    print(
        json.dumps(
            {
                "position": status.get("position"),
                "inventory": observation.get("inventory"),
                "voxels": observation.get("voxels"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    env.close()


def learn():
    agent = Voyager(
        **_connection(),
        ollama_base_url=os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL),
        ollama_embedding_model_name=os.environ.get(
            "OLLAMA_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
        ),
        llm_num_ctx=int(os.environ.get("LLM_NUM_CTX", str(DEFAULT_NUM_CTX))),
        llm_request_timeout=int(os.environ.get("LLM_REQUEST_TIMEOUT", "240")),
        ckpt_dir=os.environ.get("CKPT_DIR", "ckpt"),
        resume=_flag("RESUME"),
        env_wait_ticks=int(os.environ.get("ENV_WAIT_TICKS", "20")),
        action_agent_model_name=os.environ.get(
            "ACTION_AGENT_MODEL", DEFAULT_CHAT_MODEL
        ),
        curriculum_agent_model_name=os.environ.get(
            "CURRICULUM_AGENT_MODEL", DEFAULT_CHAT_MODEL
        ),
        curriculum_agent_qa_model_name=os.environ.get(
            "CURRICULUM_QA_MODEL", DEFAULT_CHAT_MODEL
        ),
        critic_agent_model_name=os.environ.get(
            "CRITIC_AGENT_MODEL", DEFAULT_CHAT_MODEL
        ),
        skill_manager_model_name=os.environ.get(
            "SKILL_MANAGER_MODEL", DEFAULT_CHAT_MODEL
        ),
    )
    try:
        agent.learn()
    finally:
        agent.close()


def main():
    if _flag("SMOKE"):
        smoke()
        return
    learn()


if __name__ == "__main__":
    main()
