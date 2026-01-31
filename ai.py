from google import genai
import json
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

def match_job(title, company, keywords, target_companies, description, exclude_keywords):
    try:
        prompt_text = f"""Job: {title} at {company}

Keywords to MATCH: {', '.join(keywords)}
Target Companies: {', '.join(target_companies)}
Keywords to REJECT: {', '.join(exclude_keywords)}

Description:
{description}

STRICT Rules:
1. Company "{company}" MUST be in this list: {', '.join(target_companies)}
2. Title/Description MUST contain at least one keyword from: {', '.join(keywords)}
3. Title/Description MUST NOT contain ANY of: {', '.join(exclude_keywords)}
4. Senior level only - REJECT if contains: junior, intern, director, vp, manager
5. REJECT if requires MORE than 5 years experience (6+ years = REJECT)

Return ONLY valid JSON, no markdown:
{{"match": true/false, "confidence": 0.0-1.0, "reason": "State the actual company name '{company}', which keywords matched, excluded keywords found (if any), and experience requirement"}}"""

        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt_text)
        text = response.text.strip()
        
        if not text:
            print("  AI Error: Empty response")
            return any(k.lower() in title.lower() for k in keywords), 0.5, "AI fallback - empty response"
        
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        
        data = json.loads(text)
        return data["match"], data["confidence"], data["reason"]
    except json.JSONDecodeError as e:
        print(f"  AI Error: Invalid JSON - {str(e)[:100]}")
        print(f"  AI Response: {text[:200] if 'text' in locals() else 'No response'}")
        return any(k.lower() in title.lower() for k in keywords), 0.5, "AI fallback - invalid JSON"
    except Exception as e:
        print(f"  AI Error: {str(e)[:200]}")
        return any(k.lower() in title.lower() for k in keywords), 0.5, "AI fallback - error"
