from google import genai
import json
import os
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

PROFILE = {
    "role": "Senior DevOps Engineer",
    "experience_years": 5,
    "max_experience_required": 6,  # Skip jobs requiring more than this
    "skills": "Python, Docker, Kubernetes, Jenkins, AWS, Azure, CI/CD, Terraform"
}

def match_job(title, company, keywords, target_companies):
    # use AI to check if job matches
    try:
        prompt = f"""Is this job a good match?

Job: {title} at {company}
Looking for: {PROFILE['role']} with {PROFILE['experience_years']} years experience
Keywords: {', '.join(keywords)}
Skills: {PROFILE['skills']}

Return JSON: {{"match": true/false, "confidence": 0-1, "reason": "short reason"}}

Rules:
- Must match keywords (devops, sre, platform, cloud, infrastructure, software engineer with DevOps focus)
- Senior level ONLY (no junior/intern, no director/vp/manager/lead)
- REJECT if requires MORE than 6 years experience
- REJECT if says "6+ years", "7+ years", "8+ years", etc.
- For "Software Engineer" roles, MUST have DevOps/cloud/infrastructure keywords
- Company must be in target list
- Good for 3-6 years experience range"""
        
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
