#!/usr/bin/env python3
"""AI Agent Orchestrator - цикл Задача->Ollama->MCP->ответ, лимит 10 шагов"""
import json, subprocess, logging, re
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

LOG_FILE = Path(__file__).parent / "agent.log"
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()])
logger = logging.getLogger(__name__)


class AgentState(Enum):
    INITIALIZING = "initializing"
    THINKING = "thinking"
    PLANNING = "planning"
    TOOL_CALL = "tool_call"
    TOOLS_RESULT = "tools_result"
    REFINING = "refining"
    DONE = "done"
    FAILED = "failed"
    LIMIT_REACHED = "limit_reached"


class MCPServer(Enum):
    WINDOWS = "windows-mcp"
    PLAYWRIGHT = "playwright-mcp"


@dataclass
class StepResult:
    step_number: int
    state: AgentState
    message: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    observations: Optional[Dict[str, Any]] = None


@dataclass
class AgentConfig:
    model_name: str = "qwen2.5"
    max_steps: int = 10

    model_name: str = "qwen2.5"
    max_steps: int = 10


class AgentOrchestrator:
    def __init__(self, config=None):
        self.config = config or AgentConfig()
        self.current_step = 0
        self.history = []
        self.state = AgentState.INITIALIZING
        self.mcp_servers = {}
        logger.info(f"Orchestrator initialized (model={self.config.model_name}, max_steps={self.config.max_steps})")

    def load_mcp_config(self):
        cp = Path(__file__).parent / "mcp.json"
        if not cp.exists():
            return {"servers": [], "status": "no_config"}
        try:
            with open(cp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load MCP config: {e}")
            return {"servers": [], "status": "error"}

    def start_mcp_servers(self, config):
        if MCPServer.WINDOWS in config.get("servers", []):
            try:
                self.mcp_servers[MCPServer.WINDOWS] = subprocess.Popen(
                    ["uvx", "windows-mcp", "serve"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=Path(__file__).parent)
            except Exception as e:
                logger.error(f"Failed windows-mcp: {e}")
        if MCPServer.PLAYWRIGHT in config.get("servers", []):
            try:
                self.mcp_servers[MCPServer.PLAYWRIGHT] = subprocess.Popen(
                    ["npx", "@playwright/mcp@latest"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=Path(__file__).parent)
            except Exception as e:
                logger.error(f"Failed playwright-mcp: {e}")
        logger.info("MCP servers initialized")

    def stop_mcp_servers(self):
        for p in self.mcp_servers.values():
            if p.poll() is None:
                try:
                    p.terminate()
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
        logger.info("MCP servers stopped")

    def call_ollama(self, prompt, system_prompt=""):
        response = subprocess.run(["ollama", "run", self.config.model_name, prompt], capture_output=True, text=True, timeout=120, cwd=Path(__file__).parent)
        return response.stdout.strip() if response.returncode == 0 else None

    def parse_tool_calls(self, response):
        tool_calls = []
        for line in response.split('\n'):
            if "window_open" in line.lower():
                tool_calls.append({"name": "window_open", "args": self._extract_args(line)})
            elif "browser_navigate" in line.lower():
                tool_calls.append({"name": "browser_navigate", "args": self._extract_args(line)})
            elif "browser_click" in line.lower():
                tool_calls.append({"name": "browser_click", "args": self._extract_args(line)})
            elif "browser_type" in line.lower():
                tool_calls.append({"name": "browser_type", "args": self._extract_args(line)})
        return tool_calls

    def _extract_args(self, line):
        args = {}
        m = re.search(r'https?://[^\s"]+', line)
        if m:
            args["url"] = m.group(0)
        m = re.search(r'file:///([^\s"\']+)')
        if m:
            args["path"] = m.group(1).replace('file:///', '')
        m = re.search(r'"text":\s*"([^"]*)"', line)
        if m:
            args["text"] = m.group(1)
        return args

        return args
    
    def execute_tool_call(self, tool_call):
        tool_name = tool_call.get("name", "")
        args = tool_call.get("args", {})
        logger.info(f"Executing: {tool_name}, args={args}")

        if "window_open" in tool_name.lower():
            title = args.get("title", "")
            action = f"Открыть окно: {title}"
            return self._execute_windows(action)
        elif "browser_navigate" in tool_name.lower():
            url = args.get("url", "")
            if not url:
                return "Ошибка: URL не указан"
            return self._execute_playwright(f"Перейти по адресу: {url}")
        elif "browser_click" in tool_name.lower():
            selector = args.get("selector", "")
            text = args.get("text", "")
            if not selector and not text:
                return "Ошибка: Selector или text не указаны"
            action = f"Клик по: {selector or text}"
            return self._execute_playwright(action)
        elif "browser_type" in tool_name.lower():
            selector = args.get("selector", "")
            text = args.get("text", "")
            if not selector or not text:
                return "Ошибка: Selector или текст не указаны"
            action = f"Ввод текста '{text}' в: {selector}"
            return self._execute_playwright(action)
        else:
            return f"Инструмент [{tool_name}] требует подтверждения. Аргументы: {args}"

    def _execute_windows(self, action):
        try:
            if "Открыть окно" in action:
                window_title = action.replace("Открыть окно: ", "").strip()
                logger.info(f"Opening window: {window_title}")
                return f"\u2705 Окно '{window_title}' открыто (имитация)\n\nДоступные окна:\n- Notepad.txt\n- Calculator.exe"
            elif "Закрыть окно" in action:
                window_id = action.replace("Закрыть окно: ", "").strip()
                logger.info(f"Closing window: {window_id}")
                return f"\u2705 Окно '{window_id}' закрыто (имитация)"
            else:
                return f"\u26a0 Windows-действие не распознано"
        except Exception as e:
            logger.error(f"Windows action failed: {e}")
            return f"\u274C Ошибка: {str(e)}"

    def _execute_playwright(self, action):
        try:
            if "Перейти по адресу:" in action or "Navigate" in action:
                url_match = re.search(r'(\S+)', action)
                url = url_match.group(1) if url_match else ""
                return f"\u2705 Навигация по URL: {url} (имитация)\n\nСтраница загружена."
            elif "Клик по:" in action or "Click on:" in action:
                selector_text = re.search(r'(\S+)', action)
                selector = selector_text.group(1).replace('"', '') if selector_text else ""
                return f"\u2705 Клик выполнен (selector={selector}) (имитация)\n\nЭлемент найден и обработан."
            elif "Ввод текста" in action or "Type text:" in action:
                target_match = re.search(r'in: (\S+)', action)
                selector = target_match.group(1).replace('"', '') if target_match else "input"
                text_match = re.search(r'"text":\s*"([^"]*)"', action)
                text = text_match.group(1) if text_match else ""
                return f"\u2705 Текст '{text}' введен в {selector} (имитация)"
            elif "Нажмите Enter" in action or "press enter" in action:
                return f"\u2705 Нажат Enter на активном поле (имитация)"
            elif "Снять фокус" in action or "blur" in action.lower():
                return f"\u2705 Снят фокус с поля (имитация)"
            else:
                return f"\u26a0 Playwright-действие не распознано"
        except Exception as e:
            logger.error(f"Playwright action failed: {e}")
            return f"\u274C Ошибка выполнения действия: {str(e)}"

        except Exception as e:
            logger.error(f"Playwright action failed: {e}")
            return f"\u274C Ошибка выполнения действия: {str(e)}"
    
    def run_cycle(self, task):
        system_prompt = self._get_system_prompt()
        logger.info(f"\n{'='*60}\nTASK: {task}\n{'='*60}\n")
        
        while self.current_step < self.config.max_steps:
            self.current_step += 1
            logger.info(f"Step {self.current_step}/{self.config.max_steps}")
            
            response = self.call_ollama(prompt=self._build_user_prompt(task), system_prompt=system_prompt)
            
            if not response:
                state = AgentState.FAILED
                message = "Ошибка Ollama"
                break
            
            response = response.strip()
            logger.info(f"Model: {response[:300]}...")
            
            if self._check_termination(response, task):
                break
            
            tool_calls = self.parse_tool_calls(response)
            
            if tool_calls:
                logger.info(f"Tools found: {len(tool_calls)}")
                
                results = []
                for tc in tool_calls:
                    result = self.execute_tool_call(tc)
                    results.append(result)
                
                if results:
                    obs = "\n\n".join(results)
                    refine_prompt = f"Результат:\n{obs}\nЗадача: {task}\nЕсли готово - TERMINATE, иначе следующий шаг"
                    response = self.call_ollama(refine_prompt, system_prompt)
                    
                    if self._check_termination(response, task):
                        break
                
                else:
                    state = AgentState.FAILED
                    message = "Инструменты не выполнены"
                    break
            
            elif self._is_complete(response, task):
                state = AgentState.DONE
                message = f"Ответ:\n{response}"
                break
            
            else:
                state = AgentState.REFINING
                message = response[:300]
        
        return StepResult(self.current_step, self.state if state != AgentState.FAILED else state, message)

    def _get_system_prompt(self):
        return "Ты - AI-агент Windows/Chrome. Правило 1: Выполняй только задачи пользователя. Правило 2: Если готово - TERMINATE. Инструменты: windows-open_window(title), playwright-navigate(url), playwright-click(selector|text), playwright-type(selector,text)."

    def _build_user_prompt(self, task):
        return f"Задача:\n{task}\nКакие действия?"

    def _check_termination(self, response, task):
        if "TERMINATE" in response.upper():
            logger.info("Terminated by model")
        self.stop_mcp_servers()
        logger.info("Cleaned up")


def create_default_mcp_config():
    config = {
        "name": "alice-ai-agent",
        "servers": [
            {"name": "windows-mcp", "command": "uvx windows-mcp serve", "enabled": True, "priority": 1},
            {"name": "playwright-mcp", "command": "npx @playwright/mcp@latest", "enabled": True, "priority": 2}
        ],
        "settings": {"timeout": 30, "retry_attempts": 3, "log_level": "INFO"},
        "status": "ok"
    }
    (Path(__file__).parent / "mcp.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    print("Created mcp.json")
    return config


def main():
    print("="*60)
    print("AI AGENT ORCHESTRATOR")
    print("="*60)
    
    config_file = Path(__file__).parent / "mcp.json"
    if config_file.exists():
        try:
            mcp_config = json.loads(config_file.read_text(encoding="utf-8"))
            print(f"MCP loaded: {mcp_config.get('status')}")
        except Exception as e:
            print(f"Config error: {e}")
    else:
        create_default_mcp_config()
    
    orchestrator = AgentOrchestrator()
    mcp_config = orchestrator.load_mcp_config()
    
    if "error" not in mcp_config:
        orchestrator.start_mcp_servers(mcp_config)
    
    print("\nВведите задачу:")
    task = input("Задача: ").strip()
    
    if not task:
        print("Нет задачи!")
        return
    
    try:
        result = orchestrator.run_cycle(task)
        print(f"\n{'='*60}\nРЕЗУЛЬТАТ:\n{result.message}\n{'='*60}")
        print(f"Статус: {result.state}")
    except KeyboardInterrupt:
        print("\nПрервано пользователем")
    except Exception as e:
        print(f"\nОшибка: {e}")
    finally:
        orchestrator.cleanup()


if __name__ == "__main__":
    main()
            return True
        return False

    def _is_complete(self, response, task):
        phrases = ["задача выполнена", "готово", "completed", "done"]
        return any(p in response.lower() and len(response) > 100 for p in phrases)

    def print_history(self):
        logger.info("\n" + "="*60 + "\nAGENT HISTORY:\n" + "="*60)
        for step in self.history:
            logger.info(f"\nStep {step.step_number}: {step.state}")
            logger.info(f"Message: {step.message[:200]}...")

    def cleanup(self):
        self.stop_mcp_servers()
        logger.info("Cleaned up")
