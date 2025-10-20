import argparse
import datetime
import json
import logging
import os
import random
import sys
import glob
import pprint
from tqdm import tqdm
import time

from spider_agent.envs.spider_agent import Spider_Agent_Env
from spider_agent.agent.agents import PromptAgent


#  Logger Configs {{{ #
logger = logging.getLogger("spider_agent")
logger.setLevel(logging.DEBUG)

datetime_str: str = datetime.datetime.now().strftime("%Y%m%d@%H%M%S")

file_handler = logging.FileHandler(os.path.join("logs", "normal-{:}.log".format(datetime_str)), encoding="utf-8")
debug_handler = logging.FileHandler(os.path.join("logs", "debug-{:}.log".format(datetime_str)), encoding="utf-8")
stdout_handler = logging.StreamHandler(sys.stdout)
sdebug_handler = logging.FileHandler(os.path.join("logs", "sdebug-{:}.log".format(datetime_str)), encoding="utf-8")

file_handler.setLevel(logging.INFO)
debug_handler.setLevel(logging.DEBUG)
stdout_handler.setLevel(logging.INFO)
sdebug_handler.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    fmt="\x1b[1;33m[%(asctime)s \x1b[31m%(levelname)s \x1b[32m%(module)s/%(lineno)d-%(processName)s\x1b[1;33m] \x1b[0m%(message)s")
file_handler.setFormatter(formatter)
debug_handler.setFormatter(formatter)
stdout_handler.setFormatter(formatter)
sdebug_handler.setFormatter(formatter)

stdout_handler.addFilter(logging.Filter("spider_agent"))
sdebug_handler.addFilter(logging.Filter("spider_agent"))

logger.addHandler(file_handler)
logger.addHandler(debug_handler)
logger.addHandler(stdout_handler)
logger.addHandler(sdebug_handler)
#  }}} Logger Configs # 



def config() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run end-to-end evaluation on the benchmark"
    )

    # Using Claude Agent SDK mode
    parser.add_argument("--claude_agent_sdk_mode", action="store_true")
    parser.add_argument("--keep_container_up", action="store_true")
    parser.add_argument("--just_prepare_container", action="store_true")

    parser.add_argument("--max_steps", type=int, default=30)
    
    parser.add_argument("--max_memory_length", type=int, default=25)
    parser.add_argument("--suffix", '-s', type=str, default="gpt-4-try1")
    
    parser.add_argument("--model", type=str, default="gpt-4o")
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--top_p", type=float, default=0.9)
    parser.add_argument("--max_tokens", type=int, default=2500)
    parser.add_argument("--stop_token", type=str, default=None)
    
    # example config
    parser.add_argument("--test_path","-t", type=str, default="../../spider2-dbt/examples/spider2-dbt.jsonl")
    parser.add_argument("--example_index", "-i", type=str, default="all", help="index range of the examples to run, e.g., '0-10', '2,3', 'all'")
    parser.add_argument("--example_name", "-n", type=str, default="", help="name of the example to run")
    parser.add_argument("--overwriting", action="store_true", default=False)
    parser.add_argument("--retry_failed", action="store_true", default=False)

    # output related
    parser.add_argument("--output_dir", type=str, default="output")
    parser.add_argument("--plan", action="store_true")

    parser.add_argument("--dbt_only", action="store_true",default=True)
    
    args = parser.parse_args()

    return args



def test(
    args: argparse.Namespace,
    test_all_meta: dict = None
) -> None:
    scores = []
    
    # log args
    logger.info("Args: %s", args)

    if args.suffix == "":
        logger.warning("No suffix is provided, the experiment id will be the model name.")
        experiment_id = args.model.split("/")[-1]
    else:
        experiment_id = args.model.split("/")[-1] + "-" + args.suffix
        
    if args.plan:
        experiment_id = f"{experiment_id}-plan"

    
    agent = PromptAgent(
        model=args.model,
        max_tokens=args.max_tokens,
        top_p=args.top_p if args.top_p > 0 else None,
        temperature=args.temperature if args.temperature > 0 else None,
        max_memory_length=args.max_memory_length,
        max_steps=args.max_steps,
        use_plan=args.plan
    )
    valid_ids = []
    ## load task configs
    assert os.path.exists(args.test_path) and args.test_path.endswith(".jsonl"), f"Invalid test_path, must be a valid jsonl file: {args.test_path}"
    with open(args.test_path, "r") as f:
        task_configs = [json.loads(line) for line in f]
    if args.example_name != "":
        task_configs = [task for task in task_configs if args.example_name in task["instance_id"]]
    else:
        if args.example_index != "all":
            if "-" in args.example_index:
                start, end = map(int, args.example_index.split("-"))
                task_configs = task_configs[start:end]
            else:
                indices = list(map(int, args.example_index.split(",")))
                task_configs = [task_configs[i] for i in indices]
    
    for task_config in task_configs:
        instance_id = experiment_id +"/"+ task_config["instance_id"]
        output_dir = os.path.join(args.output_dir, instance_id)
        result_json_path =os.path.join(output_dir, "spider/result.json")

        
      
        task_type = None
        if task_config["instance_id"].startswith("bq") or task_config["instance_id"].startswith("ga"):
            task_type = 'bq'
        elif task_config["instance_id"].startswith("local"):
            task_type = 'local'
        elif task_config["instance_id"].startswith("sf"):
            task_type = 'sf'
        elif task_config["instance_id"].startswith("ch0"):
            task_type = 'ch'
        elif task_config["instance_id"].startswith("postgres"):
            task_type = 'pg'
        else:
            task_type = 'dbt'


        valid_types = set()

        if args.dbt_only: valid_types.add('dbt')



        valid_ids.append(task_config["instance_id"])
        if not args.overwriting and os.path.exists(result_json_path):
            logger.info("Skipping %s", instance_id)
            continue
        elif os.path.exists(result_json_path):
            logger.info("Overwriting %s", instance_id)
        else:
            logger.info("Running %s", instance_id)
        if args.retry_failed and os.path.exists(result_json_path):
            with open(result_json_path, "r") as f:
                result = json.load(f)
                if result["finished"] and (not "FAIL" in result["result"]) and (not "error" in result["result"].lower()):
                    logger.info("Skipping %s", instance_id)
                    continue
            logger.info("Retrying %s", instance_id)
            
        if os.path.exists(output_dir):
            os.system(f"rm -rf {output_dir}")
            logger.info("Removed existing %s", output_dir)

        os.makedirs(output_dir, exist_ok=True)


        source_data_dir = os.path.dirname(args.test_path)

        env_config = \
        {
            "init_args": {
                "name": experiment_id,
                "work_dir": "/workspace",
                #"ports": {8088: 8080} # For dbt docs serve
            }
        }

        if args.just_prepare_container:
            env_config["init_args"]["ports"] = {8080: 8080} # For dbt docs serve


        env_config["image_name"] = "spider_agent-image"
        task_config['config'] = [{"type": "copy_all_subfiles", "parameters": {"dirs": [os.path.join(source_data_dir, task_config["instance_id"])]}}]


        env_config["init_args"]["name"] = experiment_id +"-"+ task_config["instance_id"]

        # In Claude Agent SDK mode, we run the agent inside the container, unlike the regular flow.
        # So the orchestration is around passing the info there, runnning the container with the agent script, and collecting the results.
        if args.claude_agent_sdk_mode:

            # Update env config for the agent running inside the container
            env_config["image_name"] = "spider_agent_with_claude_agent-image"
            env_config["init_args"]["environment"] = {
                "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"], # "******************"
            }

            # Agent / Test related files to add to container
            workspace_dir = env_config['init_args']['work_dir']
            agent_base_dir = "agent" # Relative to workspace_dir
            agent_exec_file = os.path.join(agent_base_dir, "run_test_in_container.py")
            agent_instruction_file = os.path.join(agent_base_dir, "task_instructions.txt")
            agent_results_file = os.path.join(agent_base_dir, "result.json")

            # Copy/Create the files
            task_config['config'].append({"type": "create_file",
                                          "parameters": {
                                            "src_data": task_config["instruction"],
                                            "dst_path": agent_instruction_file}})
            task_config['config'].append({"type": "copy_file",
                                            "parameters": {
                                            "src_file": "spider_agent/images/spider_agent_with_claude_agent-image/run_test_in_container.py",
                                            "dst_path": agent_exec_file}})

            #print(f"TEMP: TASK CONFIG: {pprint.pformat(task_config)}\n;;\nOUTPUT DIR: {output_dir}")

        env = Spider_Agent_Env(
            env_config=env_config,
            task_config=task_config,
            cache_dir="./cache",
            mnt_dir=output_dir
        )
    
        if args.just_prepare_container:
            logger.info(f'Container {env.container.name} ready and is under your responsibility. Exiting...')
            sys.exit(0)

        if not args.claude_agent_sdk_mode:

            # Regular script mode
            agent.set_env_and_task(env)
        
            logger.info('Task input:' + task_config['instruction'])
            done, result_output = agent.run()
            trajectory = agent.get_trajectory()
        
        else:
            # Claude Agent SDK mode

            # Run the agent in the container
            print(f"Run agent in the container...")
            cmd = ["python3", os.path.join(workspace_dir, agent_exec_file),
                   "--instruction_file", os.path.join(workspace_dir, agent_instruction_file),
                   "--model", args.model,
                   "--max_turns", str(args.max_steps)]
            _, stream = env.container.exec_run(cmd, workdir=os.path.join(workspace_dir, agent_base_dir), stream=True)
            for data in stream:
                try:
                    print(data.decode())
                except Exception as e:
                    print(f"Error decoding data: {e}")

            # Open the result.json file
            with open(os.path.join(output_dir, agent_results_file), "r") as f:
                results = json.load(f)
            
            # Update data for the rest of the code
            done = results.get("summary", {}).get("subtype", "failed") == "success"
            result_output = results.get("summary", {}).get("result", "")
            trajectory = results
            
            print(f"Test Done, saving results...")



        os.makedirs(os.path.join(output_dir, "spider"), exist_ok=True)
        result_files = env.post_process()
        spider_result = {"finished": done, "steps": len(trajectory["trajectory"]),
                           "result": result_output,"result_files": result_files, **trajectory}
        with open(os.path.join(output_dir, "spider/result.json"), "w") as f:
            json.dump(spider_result, f, indent=2)
        

        logger.info("Finished %s", instance_id)
        
        if args.keep_container_up:
            logger.info(f"Keeping container '{env.container.name}' up for debugging...")
        else:
            env.close()




if __name__ == '__main__':
    args = config()
    test(args)