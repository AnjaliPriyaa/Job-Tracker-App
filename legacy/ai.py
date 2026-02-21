from google import genai
import json
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

def match_job(title, company, keywords, target_companies, description, exclude_keywords, exclude_roles, exclude_levels, max_experience=5):
    try:
        exclude_roles_str = ', '.join([f'"{role}"' for role in exclude_roles])
        exclude_levels_str = ', '.join([f'"{level}"' for level in exclude_levels])
        
        prompt_text = f"""Job: {title} at {company}

Keywords to MATCH: {', '.join(keywords)}
Target Companies: {', '.join(target_companies)}
Keywords to REJECT: {', '.join(exclude_keywords)}

Description:
{description}

STRICT Rules - ANY violation means match=false:
1. Company "{company}" MUST be in this list: {', '.join(target_companies)}
2. Title/Description MUST contain at least one keyword from: {', '.join(keywords)}
3. Title/Description MUST NOT contain ANY of: {', '.join(exclude_keywords)}
4. IMMEDIATE REJECT if job title contains ANY of these words: {exclude_roles_str}
5. IMMEDIATE REJECT if description mentions any of: {exclude_levels_str}
6. IMMEDIATE REJECT if requires MORE than {max_experience} years experience (examples: "{max_experience+1}+ years", "{max_experience+3} years", "{max_experience+5}+ years" = REJECT)

CRITICAL: Check the job title "{title}" - if it contains any word from [{exclude_roles_str}], set match=false immediately.

Return ONLY valid JSON, no markdown:
{{"match": true/false, "confidence": 0.0-1.0, "reason": "State the actual company name '{company}', which keywords matched, excluded keywords found (if any), experience requirement, and why accepted/rejected"}}"""

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