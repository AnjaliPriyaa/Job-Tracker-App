"""Agentic Job Tracker using LangChain"""
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import AgentExecutor, create_react_agent
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.prompts import PromptTemplate
from langchain_core.tools import tool
from langchain_tools import ALL_TOOLS
from langchain_ai import get_matcher
from dotenv import load_dotenv
import os
import json

load_dotenv()


# Add AI matching tool to the agent
@tool("ai_match_job")
def ai_match_job(job_data: str) -> str:
    """
    Use AI to match a job against criteria with high accuracy.
    Input should be JSON string with: title, company, description, keywords, 
    target_companies, exclude_keywords, exclude_roles, exclude_levels, max_experience.
    Returns JSON with match status, confidence, and reasoning.
    """
    try:
        data = json.loads(job_data)
        matcher = get_matcher()
        
        result = matcher.match_job(
            title=data.get("title", ""),
            company=data.get("company", ""),
            description=data.get("description", ""),
            keywords=data.get("keywords", []),
            target_companies=data.get("target_companies", []),
            exclude_keywords=data.get("exclude_keywords", []),
            exclude_roles=data.get("exclude_roles", []),
            exclude_levels=data.get("exclude_levels", []),
            max_experience=data.get("max_experience", 5)
        )
        
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e), "match": False, "confidence": 0.0})


class JobTrackerAgent:
    """Agentic job tracker that autonomously searches and filters jobs"""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        
        # Initialize LLM
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash-exp",
            google_api_key=os.getenv("GEMINI_API_KEY"),
            temperature=0.2,
            convert_system_message_to_human=True
        )
        
        # Initialize tools (include AI matching tool)
        self.tools = ALL_TOOLS + [ai_match_job]
        
        # Create ReAct prompt
        self.prompt = PromptTemplate.from_template("""You are an autonomous job tracking agent. Your goal is to find relevant job opportunities and notify the user.

You have access to the following tools:
{tools}

Tool Names: {tool_names}

Use the following format:

Question: the input question or task you must complete
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

IMPORTANT WORKFLOW:
1. Always start by loading the config using 'load_config' tool
2. Check if cleanup is needed using 'check_cleanup_needed' tool
3. For each job portal in config, scrape jobs using 'scrape_linkedin_jobs'
4. For each job found, get full description using 'get_job_description'
5. Use 'ai_match_job' to intelligently filter jobs (requires JSON input)
6. Check if job was seen before using 'manage_seen_jobs' with action='check'
7. If new and matches criteria, send notification using 'send_telegram_notification'
8. Mark job as seen using 'manage_seen_jobs' with action='add'

Question: {input}
Thought: {agent_scratchpad}""")
        
        # Create agent
        self.agent = create_react_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=self.prompt
        )
        
        # Create agent executor
        self.agent_executor = AgentExecutor.from_agent_and_tools(
            agent=self.agent,
            tools=self.tools,
            verbose=self.verbose,
            handle_parsing_errors=True,
            max_iterations=50,
            max_execution_time=600,  # 10 minutes max
            return_intermediate_steps=True
        )
    
    def run(self, task: str = None) -> dict:
        """
        Run the agent with a specific task or default job tracking task.
        
        Args:
            task: Optional custom task description. If None, uses default job tracking.
        
        Returns:
            dict with output and intermediate steps
        """
        if task is None:
            task = """Search for new job opportunities based on the configuration.
            
Your workflow:
1. Load the configuration file to get search criteria
2. Check if cleanup is needed and perform if necessary
3. For each job portal in the config:
   a. Scrape jobs from the portal
   b. For each job found:
      - Get the full job description
      - Check if it was seen before
      - If not seen, use AI to match against criteria
      - If match confidence >= 0.6, send Telegram notification
      - Mark the job as seen
4. Provide a summary of total jobs found and new jobs discovered

Be autonomous and make decisions without asking for confirmation."""
        
        try:
            result = self.agent_executor.invoke({"input": task})
            return {
                "success": True,
                "output": result.get("output", ""),
                "steps": result.get("intermediate_steps", [])
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "output": ""
            }
    
    def run_custom_task(self, task: str) -> str:
        """
        Run a custom task with the agent.
        
        Args:
            task: Custom task description
        
        Returns:
            Agent's response
        """
        result = self.run(task)
        return result.get("output", result.get("error", "Unknown error"))


def main():
    """Main entry point for agentic job tracker"""
    print("🤖 Starting Agentic Job Tracker with LangChain...\n")
    
    # Create agent
    agent = JobTrackerAgent(verbose=True)
    
    # Run autonomous job tracking
    result = agent.run()
    
    print("\n" + "="*60)
    if result["success"]:
        print("✅ Agent completed successfully!")
        print(f"\nFinal Output:\n{result['output']}")
    else:
        print("❌ Agent encountered an error:")
        print(f"{result.get('error', 'Unknown error')}")
    print("="*60)


if __name__ == "__main__":
    main()
