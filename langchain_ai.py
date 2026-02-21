"""LangChain-based AI matching using Gemini"""
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field, field_validator
from typing import List
import os
from dotenv import load_dotenv
import json

load_dotenv()


class JobMatchResult(BaseModel):
    """Job matching result schema"""
    match: bool = Field(description="Whether the job matches the criteria")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")
    reason: str = Field(description="Detailed explanation of the match decision")
    
    @field_validator('confidence')
    @classmethod
    def confidence_must_be_valid(cls, v):
        if not 0.0 <= v <= 1.0:
            raise ValueError('Confidence must be between 0.0 and 1.0')
        return v


class LangChainJobMatcher:
    """AI-powered job matcher using LangChain and Gemini"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        
        # Initialize Gemini model via LangChain
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash-exp",
            google_api_key=self.api_key,
            temperature=0.1,  # Low temperature for consistent matching
            convert_system_message_to_human=True
        )
        
        # Initialize output parser
        self.parser = PydanticOutputParser(pydantic_object=JobMatchResult)
        
        # Create prompt template
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert job matching AI. Analyze job postings and determine if they match the candidate's criteria.
Be strict with filtering to avoid false positives. Follow ALL rules precisely."""),
            ("human", """{input_text}

{format_instructions}

IMPORTANT: Return ONLY valid JSON, no markdown or explanations.""")
        ])
    
    def match_job(
        self,
        title: str,
        company: str,
        description: str,
        keywords: List[str],
        target_companies: List[str],
        exclude_keywords: List[str],
        exclude_roles: List[str],
        exclude_levels: List[str],
        max_experience: int = 5,
        target_roles: List[str] = None
    ) -> dict:
        """
        Match a job against criteria using AI.
        
        Returns:
            dict with keys: match (bool), confidence (float), reason (str)
        """
        try:
            # Build the matching criteria text
            exclude_roles_str = ', '.join([f'"{role}"' for role in exclude_roles])
            exclude_levels_str = ', '.join([f'"{level}"' for level in exclude_levels])
            target_roles_str = ', '.join([f'"{role}"' for role in (target_roles or [])])
            
            input_text = f"""Job Title: {title}
Company: {company}

Target Roles (what candidate is looking for): {target_roles_str}
Keywords to MATCH: {', '.join(keywords)}
Target Companies: {', '.join(target_companies)}
Keywords to REJECT: {', '.join(exclude_keywords)}

Job Description:
{description[:2000]}  

STRICT Matching Rules - ANY violation means match=false:
1. Company "{company}" MUST be in target list: {', '.join(target_companies)}
2. Title/Description MUST contain at least one keyword from: {', '.join(keywords)}
3. Title/Description MUST NOT contain ANY of: {', '.join(exclude_keywords)}
4. IMMEDIATE REJECT if job title contains ANY: {exclude_roles_str}
5. IMMEDIATE REJECT if description mentions: {exclude_levels_str}
6. IMMEDIATE REJECT if requires MORE than {max_experience} years experience
   - Examples of REJECT: "{max_experience+1}+ years", "{max_experience+2}+ years", "minimum {max_experience+1} years", "{max_experience+2}-{max_experience+4} years"
7. REJECT if title contains words indicating higher seniority: "Principal", "Staff", "Architect", "Lead", "Manager", "Director", "Head of", "Chief"
8. REJECT if description asks for responsibilities beyond individual contributor: "managing team", "lead a team", "reporting to", "direct reports"

CRITICAL CHECKS:
- Check the job title "{title}" - if it contains ANY word from [{exclude_roles_str}], set match=false immediately
- Check for experience requirements: if it says "{max_experience+1}+ years" or "minimum {max_experience+1}", REJECT
- Check for leadership/management keywords in description: "manage", "lead team", "reporting" = REJECT
- Job title should align with target roles: {target_roles_str}
- Focus on individual contributor roles unless explicitly stated otherwise

Analyze carefully and provide:
- match: true/false based on ALL rules above
- confidence: 0.0 to 1.0 (how confident you are in the decision)
- reason: State the company name, whether role matches target roles ({target_roles_str}), which keywords matched/excluded, experience requirement, and why accepted/rejected"""
            
            # Create chain
            chain = self.prompt | self.llm
            
            # Get format instructions
            format_instructions = self.parser.get_format_instructions()
            
            # Invoke chain
            response = chain.invoke({
                "input_text": input_text,
                "format_instructions": format_instructions
            })
            
            # Parse response
            text = response.content.strip()
            
            # Remove markdown if present
            if "```" in text:
                text = text.split("```")[1].replace("json", "").strip()
            
            # Try to parse as JSON directly
            try:
                result = json.loads(text)
                return {
                    "match": result.get("match", False),
                    "confidence": result.get("confidence", 0.5),
                    "reason": result.get("reason", "Unknown")
                }
            except json.JSONDecodeError:
                # Fallback to Pydantic parser
                parsed = self.parser.parse(text)
                return {
                    "match": parsed.match,
                    "confidence": parsed.confidence,
                    "reason": parsed.reason
                }
        
        except Exception as e:
            print(f"  AI Error: {str(e)[:200]}")
            # Fallback to keyword matching
            has_keyword = any(k.lower() in title.lower() for k in keywords)
            return {
                "match": has_keyword,
                "confidence": 0.5,
                "reason": f"AI fallback - error: {str(e)[:100]}"
            }


# Create a singleton instance
_matcher_instance = None

def get_matcher() -> LangChainJobMatcher:
    """Get or create the job matcher instance"""
    global _matcher_instance
    if _matcher_instance is None:
        _matcher_instance = LangChainJobMatcher()
    return _matcher_instance
