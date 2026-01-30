from google import genai
import json
import os
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

PROFILE = {
    "role": "Senior DevOps Engineer",
    "experience": "5 years",
    "skills": "Python, Docker, Kubernetes, Jenkins, AWS, Azure, CI/CD, Terraform"
}

def match_job(title, company, keywords, target_companies):
    # use AI to check if job matches
    try:
        prompt = f"""Is this job a good match?

Job: {title} at {company}
Looking for: {PROFILE['role']} with {PROFILE['experience']} experience
Keywords: {', '.join(keywords)}
Skills: {PROFILE['skills']}

Return JSON: {{"match": true/false, "confidence": 0-1, "reason": "short reason"}}

Rules:
- Must match keywords (devops, sre, platform, cloud, infrastructure)
- Senior level only (no junior, no director/vp/manager)
- Company must be in target list"""
        
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        result = response.text.strip()
        
        if "```" in result:
            result = result.split("```")[1].replace("json", "").strip()
        
        data = json.loads(result)
        return data["match"], data["confidence"], data["reason"]
    except:
        # fallback
        has_keyword = any(k.lower() in title.lower() for k in keywords)
        return has_keyword, 0.5, "fallback"
