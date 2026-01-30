from google import genai
import json
import os
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

PROFILE = {
    "role": "Senior DevOps Engineer",
    "experience_years": 5,
    "skills": "Python, Docker, Kubernetes, Jenkins, AWS, Azure, CI/CD, Terraform"
}

def match_job(title, company, keywords, target_companies):
    try:
        prompt = f"""Job: {title} at {company}
Looking for: {PROFILE['role']} ({PROFILE['experience_years']} years experience)

Rules:
- Match keywords: devops, sre, platform, cloud, infrastructure, software engineer (with DevOps focus)
- Senior level only (no junior/intern/director/vp/manager/lead)
- REJECT if requires 6+ years experience
- Target companies only

Return JSON: {{"match": true/false, "confidence": 0-1, "reason": "why"}}"""
        
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        result = response.text.strip()
        
        if "```" in result:
            result = result.split("```")[1].replace("json", "").strip()
        
        data = json.loads(result)
        return data["match"], data["confidence"], data["reason"]
    except:
        return any(k.lower() in title.lower() for k in keywords), 0.5, "fallback"
