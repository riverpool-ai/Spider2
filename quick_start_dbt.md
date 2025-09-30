## Quick Start

### Prerequisite

* Install `uv`

### Run the setup file
```bash
bash ./setup.sh 
```

### Run spider agent with claude

#### Setup Anthropic API key

```bash
export ANTHROPIC_API_KEY=<your API key>
```

#### Run spider agent

```bash
cd methods/spider-agent-dbt
source .venv/bin/activate
python run.py --model <the model to use, example: claude-3-7-sonnet-latest> -s <name of the run, example: test1>
```

### Run evaluation

#### Prepare the `results_metadata.jsonl` file

Under `methods/spider-agent-dbt/` there is a file called `results_metadata.jsonl`. Copy this file to your output directory. For example, if you run with `claude-3-7-sonnet-latest` model and your run called `test1`. You will need to copy this file to `methods/spider-agent-dbt/output/claude-3-7-sonnet-latest-test1`
```bash
cp methods/spider-agent-dbt/results_metadata.jsonl methods/spider-agent-dbt/output/claude-3-7-sonnet-latest-test1/
```

#### Run the evaluation:

Assuming you run with `claude-3-7-sonnet-latest` model and your run called `test1`, run the following to evaluate the results:

```bash
cd spider2-dbt/evaluation_suite/
source ../../methods/spider-agent-dbt/.venv/bin/activate
python evaluate.py --result_dir ../../methods/spider-agent-dbt/output/claude-3-7-sonnet-latest-test1/ --gold_dir ./gold/
```

The output will give you the final score and a list of failed and pass cases, example:

```
failed: twilio001
failed: app_reporting002
failed: greenhouse001
failed: provider001
pass: quickbooks002
failed: google_ads001
failed: tpch001
failed: social_media001
failed: apple_store001
failed: superstore001
failed: inzight001
pass: lever001
failed: recharge002
pass: hive001
pass: mrr002
failed: nba001
failed: hubspot001
failed: jira001
failed: google_play002
failed: shopify002
pass: f1003
pass: workday002
failed: recharge001
failed: airbnb001
pass: asana001
failed: tickit002
failed: scd001
pass: playbook001
failed: google_play001
failed: app_reporting001
failed: gitcoin001
failed: shopify_holistic_reporting001
failed: salesforce001
pass: divvy001
failed: xero001
failed: airport001
pass: tickit001
failed: synthea001
failed: quickbooks001
failed: analytics_engineering001
pass: workday001
failed: movie_recomm001
failed: marketo001
failed: playbook002
failed: activity001
failed: zuora001
failed: netflix001
failed: flicks001
pass: retail001
failed: tpch002
failed: airbnb002
failed: reddit001
failed: atp_tour001
failed: xero_new001
failed: xero_new002
failed: shopify001
failed: biketheft001
failed: f1002
failed: maturity001
pass: mrr001
failed: chinook001
failed: qualtrics001
failed: sap001
failed: asset001
failed: pendo001
failed: f1001
failed: intercom001
failed: quickbooks003
0.19117647058823528 13 68
```
