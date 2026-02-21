from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent
from tools import *
import os
from dotenv import load_dotenv
from langchain_core.callbacks import BaseCallbackHandler

# Load environment variables from .env file
load_dotenv()

# --- Callbacks for observing tool usage ---
class ToolCallback(BaseCallbackHandler):
    """Custom callback handler to print tool usage."""
    def on_tool_start(self, serialized, input_str, **kwargs):
        tool_name = serialized.get("name", "unknown")
        print(f"    🔧 Tool started → {tool_name}")
        print(f"       Input preview: {input_str[:100]}...")
    def on_tool_end(self, output, **kwargs):
        print(f"    ✅ Tool finished → Output length: {len(str(output))} chars")
        print(f"       Output preview: {str(output)[:100]}...")
    def on_tool_error(self, error, **kwargs):
        print(f"    ❌ Tool error → {error}")

# --- Agent Configuration ---

# Initialize the language model
llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.2,
        google_api_key=os.getenv("GEMINI_API_KEY"),
    )

# Define the list of tools available to the agent
tools = [
    load_config,
    scrape_jobs,
    get_job_description,
    manage_seen_jobs,
    send_telegram,
]

# Define the system prompt that instructs the agent
system_prompt = """
You are an autonomous job search agent.

Your goal:
Find HIGH QUALITY job matches and notify the user.

STRICT MATCHING RULES:
- Only target companies
- Must match keywords
- Reject senior roles (Lead, Staff, Manager, Architect)
- Reject >5 years experience
- Prefer individual contributor roles

WORKFLOW:
1. Load config
2. Scrape jobs
3. For each job:
- Check if seen
- Get description
- Evaluate relevance YOURSELF
- If strong match → notify
- Mark as seen

IMPORTANT:
- DO NOT call any matching tool
- YOU must decide match quality
- Be selective (quality > quantity)
"""

# --- Main Execution ---
if __name__ == "__main__":
    print("🤖 Starting Autonomous Job Agent...")

    # Create the agent
    agent_executor = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
    )

    # Instantiate the custom callback
    tool_callback = ToolCallback()

    # Invoke the agent to start the job search
    result = agent_executor.invoke(
        {"messages":[{"role": "user", "content": "Find jobs based on the user's configuration."}]},
        config={"callbacks": [tool_callback]}
    )

    # Print the final output from the agent
    print("\n✅ Agent finished. Final Output:")
    message = result["messages"][-1].content
    message = message[-1]['text'] if isinstance(message, list) else message
    print(message)