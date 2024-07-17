from flask import Flask, request, jsonify
import threading
import os
import requests
import re
import json
from datetime import datetime
import html
import base64

app = Flask(__name__)

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_USER = os.environ["GITHUB_USER"]
GITHUB_REPO = os.environ["GITHUB_REPO"]
WORKFLOW_ID = os.environ["WORKFLOW_ID"]
REF = os.environ["BRANCH"]
ISSUE_LABELS = os.environ["GITHUB_ISSUE_LABELS"]
ISSUE_TEMPLATE = os.environ["GITHUB_ISSUE_TEMPLATE"]

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
SLACK_URL_VERFICATION_KEY = "url_verification"
SLACK_RETRY_KEY = "x-slack-retry-num"

FORMATTER = [
  {
    "slack": "\\*(.*?)\\*",
    "markdown": "**\\1**"
  },
  {
    "slack": "•",
    "markdown": "-"
  },
  {
    "slack": "<(http[s]?://[^\\|]+)\\|([^>]+)>",
    "markdown": "[\\2](\\1)"
  },
  {
    "slack": "\\n",
    "markdown": "\\n\\n"
  }
]

def slack_to_markdown(slack_message):
    markdown_message = slack_message
    for item in FORMATTER:
        markdown_message = re.sub(item["slack"], item["markdown"], markdown_message)
    return markdown_message

def parse_message(message):
    DATETIME_INPUT_FORMAT = "%a, %d %b %Y %H:%M:%S %Z"

    PATTERNS = {
        "url": [r"<(https?://\S+?)\|", lambda x: html.unescape(x)],
        "type": [r"\*Event type code\*\n(.+)\n", lambda x: x.replace("_", " ")],
        "datetime": r"\*Start time\*\n(.+)\n"
    }
    data = {}
    for key, desc in PATTERNS.items():
        if isinstance(desc, (list, tuple)) and len(desc) == 2:
            pattern, format = desc
        elif isinstance(desc, str):
            pattern, format = desc, lambda x: x
        match = re.search(pattern, message)
        if match:
            data[key] = format(match.group(1))

    return  f"[{datetime.strftime(datetime.strptime(data['datetime'], DATETIME_INPUT_FORMAT), '%Y%m%d')}] Health Event: {data['type']}", \
                base64.b64encode(json.dumps({
                    "SCREENSHOT" : slack_to_markdown(message),
                    "DATETIME" : data["datetime"],
                    "URL" : data["url"],
                }).encode()).decode()


def create_github_issue(message_timestamp, message_text):
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/actions/workflows/{WORKFLOW_ID}/dispatches"

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    title, description = parse_message(message_text)

    data = {
        "ref": REF,
        "inputs": {
            "title": title,
            "description": description,
            "labels": ISSUE_LABELS,
            "template": ISSUE_TEMPLATE,
            "slack-thread-timestamp": message_timestamp,
            "slack-webhook-url": SLACK_WEBHOOK_URL
        }
    }

    print("[ISSUE Data]", data)
    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 204:
        print("[SUCCESS] Trigger GitHub Action workflow")
    else:
        print("[        FAIL] Trigger GitHub Action workflow: ", response.text)

def handle_slack_event(event):
    print("[EVENT]: ", event)
    if event.get("type", "") == "message":
        message_timestamp = event.get("ts", "")
        message_text = event.get("text", "")

        create_github_issue(message_timestamp, message_text)

@app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.get_json(silent=True)
    headers = request.headers

    if data is None or headers.get(SLACK_RETRY_KEY, 0, type=int) > 1:
        return jsonify()

    # Check for the challenge code
    if data.get("type", "") == SLACK_URL_VERFICATION_KEY:
        return jsonify({"challenge": data.get("challenge", "")})
    
    # Not handle reply message
    event = data.get("event", {})
    if event.get("thread_ts", "") != "":
        return jsonify()

    # Create a new thread to handle the event
    event_thread = threading.Thread(target=handle_slack_event, args=(event,))
    event_thread.start()

    # Respond to Slack immediately
    return jsonify()