"""Run with python -m BRH_Test.ai_doctor; checks Gemini without fallback masking failure."""
import json
from pathlib import Path
from dotenv import dotenv_values
from .ai_client import AdviceClient


def main():
    config = dict(dotenv_values(Path(__file__).parent / ".env"))
    config["XAI_API_KEY"] = ""
    client = AdviceClient(config)
    answer = client.generate("You are Rover, a recycling adviser. Reply in one sentence.",
                             [], "Where should used batteries go?")
    print(json.dumps({"gemini": client.status()["gemini"], "reply": answer}, indent=2))
    return 0 if answer else 1


if __name__ == "__main__":
    raise SystemExit(main())
