import re
import os
import sys
import json
import time
from typing import Any
import asyncio
import pprint
import argparse
from dataclasses import asdict
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, SystemMessage, AssistantMessage, TextBlock, ResultMessage, HookMatcher, ToolResultBlock, tool, create_sdk_mcp_server

# TODO:
# 6. Add to the agent the ability to run sql queries on the DB (python code with duckdb driver)
# 7. Make the main runner (run.py) with a new flag mode run this new method and orcestrate the results (define and implement a way to detect when agent finishes or unexpectedly exist).
# 8. Align output schema to the expectation of the evaluation suite / whatever comes next.


SYSTEM_PROMPT = """
You are a data scientist proficient in database, SQL and DBT Project.
You are starting in the /workspace directory, which contains all the codebase needed for your tasks (excluding /workspace/agent directory which is unrelated to the task).
You will be given a task to solve. Solving the task requires you to add the needed DBT model SQLs that answers the task, then run `dbt run` to update the database.
Think of the steps you need to take to solve the task, and create a TODO list to keep track of your planned work.
You're advised to first run 'dbt run' to ensure the project is in a good state, and if not fix it before you start writing SQL.
You are **NOT** allowed to update the DuckDB file directly, only via "dbt run" command. Treat the DuckDB file as readonly.
If the task is asking for explenation, you should still answer in the form of generating a DBT model SQL that answers the task.

When you are done, you must use the format described in the "Terminate Action" to finish the task.

# Terminate Action
* Signature: TerminateAction(output=\"DB_file_name_or_error_reason\")
* Description: This action denotes the completion of the entire task and returns the final answer or the output file path. The answer should always be the name of the DuckDB file in the workspace directory. In case of error preventing completing the task, you must terminate the task with the error message prefixed with "Error: ".
* Examples:
  - Example1: TerminateAction(output="database_file.duckdb")
  - Example2: TerminateAction(output="Error: Failed to complete the task, couldn't get 'dbt run' to work properly.")

# DBT Project Hint#
1. **For dbt projects**, first read the dbt project files. Your task is to write SQL queries to handle the data transformation and solve the task.
2. All necessary data is stored in the **DuckDB**. Use `execute_sql` tool to query the database, do not use the DuckDB CLI. Do NOT update the DuckDB file directly, only via "dbt run" command. Treat the DuckDB file as readonly.
3. **Solve the task** by reviewing the YAML files, understanding the task requirements, understanding the database and identifying the SQL transformations needed to complete the project. 
4. The project is an unfinished project. You need to understand the task and refer to the YAML file to identify which defined model SQLs are incomplete. You must complete these SQLs in order to finish the project.
5. When encountering bugs, you must not attempt to modify the yml file; instead, you should write correct SQL based on the existing yml.
6. After writing all required SQL, run `dbt run` to update the database.
7. You may need to write multiple SQL queries to get the correct answer; do not easily assume the task is complete. You must complete all SQL queries according to the YAML files.
8. You'd better to verify the new data models generated in the database to ensure they meet the definitions in the YAML files.
9. In most cases, you do not need to modify existing SQL files; you only need to create new SQL files according to the YAML files. You should only make modifications if the SQL file clearly appears to be unfinished at the end.
10. Once the data transformation is complete and the task is solved, TerminateAction with the DuckDB file name.

"""

  
# =================================================================================================================== #
# Collector for the results
# =================================================================================================================== #
class AgentResults:

    # --------------------------------------------------------------------------------------------------------------- #
    def __init__(self):
        self.result = ""
        self.trajectory = []
        self.task = []
        self.system_message = ""
        self.summary = {}

    # --------------------------------------------------------------------------------------------------------------- #

    def add_generic_trajectory(self, **kwargs):
        self.trajectory.append(kwargs)

    # --------------------------------------------------------------------------------------------------------------- #
    def add_text_trajectory(self, message):
        self.trajectory.append({
            'text': message,
            'type': message.__class__.__name__,
        })
    
    # --------------------------------------------------------------------------------------------------------------- #
    def add_agent_trajectory(self, messageObj):


        # msg_type = message.__class__.__name__
        # if hasattr(message, "content"):
        #     for block in message.content:
        #         if isinstance(block, TextBlock):
        #             self._log(f"MSG {msg_type} (TextBlock): {block.text}")
        #         elif isinstance(block, ToolResultBlock):
        #             self._log(f"MSG {msg_type} (ToolResultBlock): is_error: {block.is_error}, content: {block.content}")


        if hasattr(messageObj, "content"):
            for block in messageObj.content:
                if isinstance(block, TextBlock):
                    self.trajectory.append({
                        'text': block.text,
                        'type':f"{messageObj.__class__.__name__} (TextBlock)",
                    })
                elif isinstance(block, ToolResultBlock):
                    self.trajectory.append({
                        'is_error': block.is_error,
                        'content': block.content,
                        'type':f"{messageObj.__class__.__name__} (ToolResultBlock)",
                    })
        else:
            self.trajectory.append({
                'type': messageObj.__class__.__name__,
            })

    # --------------------------------------------------------------------------------------------------------------- #
    def to_json(self):
        out = {}
        for k, v in self.__dict__.items():
            if k.startswith("_"):
                continue
            out[k] = v
        return out
        


# Tools that the agent can use
# =================================================================================================================== #

@tool("execute_sql",
      "Execute an SQL command on the specified readonly database file (SQLITE or Duckdb). This command can only be used to query the database, not to update it. If 'output' is set to a file path, the results are saved to this CSV file; if 'output' is empty or not provided, results are returned as str from the function. Example: execute_sql(file_path='data.duckdb', command='SELECT * FROM users', output='users_output.csv')",
      {
        "db_file_path": {
            "type": "string",
            "description": "The path to the existing database file.",
        },
        "code": {
            "type": "string",
            "description": "The SQL command to execute on the database.",
        },
        "output": {
            "type": "string",
            "description": "The path to the output file, only CSV is supposed. An empty string means to return the output directly from the function.",
        },
    })
async def execute_sql(args: dict[str, Any]) -> dict[str, Any]:

    db_file_path : str = args["db_file_path"]
    code : str = args["code"]
    output : str = args["output"]

    if not os.path.exists(db_file_path):
        return {
            "content": [{
                "type": "text",
                "text": f"Error: Database file not found: {db_file_path}"
            }]
        }
        
    if output and not output.endswith(".csv"):
        return {
            "content": [{
                "type": "text",
                "text": f"Error: Output file must be a CSV file: {output}"
            }]
        }

    # Implementation
    import pandas as pd
    import sqlite3
    import duckdb

    def detect_db_type(file_path):
        if file_path.endswith('.db') or file_path.endswith('.sqlite') :
            return 'sqlite'
        elif file_path.endswith('.duckdb'):
            return 'duckdb'
        else:
            try:
                conn = duckdb.connect(database=file_path, read_only=True)
                conn.execute('SELECT 1')
                conn.close()
                return 'duckdb'
            except:
                return 'sqlite'

    def execute_sql(file_path : str, command : str, output_path : str = None):
        db_type = detect_db_type(file_path)
        
        # Connect to the database
        if db_type == 'sqlite':
            conn = sqlite3.connect(file_path)
        elif db_type == 'duckdb':
            conn = duckdb.connect(database=file_path, read_only=True)
        else:
            return False, f"Unsupported database type: {db_type}"
        
        try:
            # Execute the SQL command and fetch the results
            df = pd.read_sql_query(command, conn)
            
            # Check if the output should be saved to a CSV file or printed directly
            if output_path and output_path.lower().endswith(".csv"):
                df.to_csv(output_path, index=False)
                return True, f"Output saved to: {output_path}"
            else:
                return True, df.to_string()
        except Exception as e:
            return False, f"Exsception: {e}"
        finally:
            # Close the connection to the database
            conn.close()

        return False, "Should not reach this code"

    is_ok, result = execute_sql(db_file_path, code, output)
    if not is_ok:
        return {
            "content": [{
                "type": "text",
                "text": f"Error: {result}"
            }]
        }
    
    return {
        "content": [{
            "type": "text",
            "text": result
        }]
    }


# =================================================================================================================== #
# cluade agent SDK based agent for data engineering tasks (using one-offs for our usage)
# =================================================================================================================== #
class DataEngAIAgent:

    # --------------------------------------------------------------------------------------------------------------- #
    def __init__(self, model=None, max_turns=None, system_prompt_append="", log_file="./debug_log.txt", result_file="./result.json"):
        # configurations
        self.model = model
        self.max_turns = max_turns
        self.system_prompt_append = system_prompt_append
        self.log_file = log_file
        self.result_file = result_file

        # Agent stuff
        self.system_prompt = None
        self.options = None
        self.client = None

        # Results
        self.results = AgentResults()

    # --------------------------------------------------------------------------------------------------------------- #
    async def setup(self):

        self.system_prompt = {
            "type": "preset",
            "preset": "claude_code",
            "append": SYSTEM_PROMPT + self.system_prompt_append,
        }

        # Create SDK MCP server with custom tools
        mcp_server = create_sdk_mcp_server(
            name="utilities",
            version="1.0.0",
            tools=[execute_sql]
        )

        self.options = ClaudeAgentOptions(
            model=self.model if self.model else None,
            max_turns=self.max_turns if self.max_turns else None,
            permission_mode="default",
            cwd="/workspace",
            system_prompt=self.system_prompt,
            mcp_servers={"utils": mcp_server},
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher="", hooks=[self._check_permissions]),
                ],
            },
        )

        self._log(f"Starting agent with model: {self.model}")

        self.client = ClaudeSDKClient(options=self.options)
        await self.client.connect()

    # --------------------------------------------------------------------------------------------------------------- #
    async def end(self):
        if self.client:
            await self.client.disconnect()
            self.client = None
        
        self._log(f"Agent End")

    # --------------------------------------------------------------------------------------------------------------- #
    async def query(self, message):

        # Results tracking
        self.results = AgentResults()
        self.results.task = message
        self.results.system_message = self.system_prompt['append']

        # Conversation history
        self._log(f"Task: {message}")
        await self.client.query(message)

        result = None
        async for message in self.client.receive_response():
            self._log_response(message)
            if isinstance(message, ResultMessage):
                result = message
            
        if result is not None:
            # self._log(f"Task Done: Statistics: duration_ms: {result.duration_ms}, duration_api_ms: {result.duration_api_ms}, is_error: {result.is_error}, num_turns: {result.num_turns}, total_cost_usd: {result.total_cost_usd}\n")
            self.results.result = self._extract_terminate_action(result.result or "") or ""
            self.results.summary = asdict(result)
            self._log(f"Task Done: Result: {pprint.pformat(self.results.summary)}")


        # Save results to file
        if self.result_file:
            with open(self.result_file, "w") as f:
                json.dump(self.results.to_json(), f, indent=2)

        return self.results

    # --------------------------------------------------------------------------------------------------------------- #
    def get_json_output(self):
        return self.results.to_json()

    # --------------------------------------------------------------------------------------------------------------- #
    def _extract_terminate_action(self, data : str):
        # EXample:
        #TerminateAction(output="playbook.duckdb")
        matches = re.findall(r'TerminateAction\(output="?(.*?)"?\)', data, flags=re.DOTALL)
        if matches:
            output = matches[-1]
            return output

        return None

    # --------------------------------------------------------------------------------------------------------------- #
    async def _check_permissions(self, input_data, tool_use_id, context):
        tool_name = input_data["tool_name"]
        tool_input = input_data["tool_input"]

        self.results.add_generic_trajectory(
            type="tool_use",
            tool_name=tool_name,
            tool_input=tool_input,
        )
        self._log(f"TOOL-USE: name:'{tool_name}', tool_input:'{tool_input}'")

        # Allow any tool for now
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": f"Tool '{tool_name}' allowed, yey",
            }
        }            

    # --------------------------------------------------------------------------------------------------------------- #
    def _log_response(self, message):
        self.results.add_agent_trajectory(message)

        msg_type = message.__class__.__name__
        if hasattr(message, "content"):
            for block in message.content:
                if isinstance(block, TextBlock):
                    self._log(f"MSG {msg_type} (TextBlock): {block.text}")
                #elif isinstance(block, ToolResultBlock):
                #    self._log(f"MSG {msg_type} (ToolResultBlock): is_error: {block.is_error}, content: {block.content}")
        else:
            self._log(f"MSG {msg_type}: ---")

    # --------------------------------------------------------------------------------------------------------------- #
    def _log(self, message):
        print(message, flush=True)
        if self.log_file:
            with open(self.log_file, "a") as f:
                f.write(message + "\n")

    # --------------------------------------------------------------------------------------------------------------- #
    async def __aenter__(self) -> "DataEngAIAgent":
        """Enter async context - automatically connects with empty stream for interactive use."""
        await self.setup()
        return self

    # --------------------------------------------------------------------------------------------------------------- #
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        """Exit async context - always disconnects."""
        await self.end()
        return False

# =================================================================================================================== #
# Main
# =================================================================================================================== #
async def main():

    # CLI arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--instruction_file", type=str, required=True)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--max_turns", type=int, default=None)
    parser.add_argument("--result_file", type=str, default="./result.json")
    args = parser.parse_args()

    print("Starting test...")

    # Read the instructions from file
    instruction_file = args.instruction_file
    if not instruction_file:
        print("No instruction file provided, exiting")
        sys.exit(1)

    try:
        with open(instruction_file, "r") as f:
            instruction = f.read()
    except Exception as e:
        print(f"Error reading instruction file, exiting: {e}")
        sys.exit(1)

    print(f"DEBUG: Instruction: {instruction}")

    # print(f"DEBUG: TEMP - STOP")
    # sys.exit(1)

    # Run the agent
    agent_kwargs = {
        "log_file": "./debug_log.txt",
        "result_file": args.result_file,
        "model": args.model,
        "max_turns": args.max_turns,
        "system_prompt_append": f"Complete the task by up to {args.max_turns} turns." if args.max_turns else "",
    }

    async with DataEngAIAgent(**agent_kwargs) as agent:
        await agent.query(instruction)

    print("\n\nDone.\n\n")
    #print(f"Result: {pprint.pformat(agent.get_json_output())}")

if __name__ == "__main__":
    asyncio.run(main())
