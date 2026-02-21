"""Simplified Agentic Job Tracker - Uses LangChain chains with autonomous workflow"""
from langchain_ai import get_matcher
from dotenv import load_dotenv
import os
import utils

load_dotenv()


class AgenticJobTracker:
    """Autonomous job tracker using LangChain components"""
    
    def __init__(self, config_path: str = "config.json"):
        self.config = utils.load_config(config_path)
        self.matcher = get_matcher()
        
        # Statistics
        self.stats = {
            "total_jobs_found": 0,
            "new_jobs": 0,
            "matched_jobs": 0,
            "notifications_sent": 0
        }
    
    def ai_filter_job(self, title: str, company: str, description: str) -> dict:
        """Use AI to filter job based on criteria"""
        result = self.matcher.match_job(
            title=title,
            company=company,
            description=description,
            keywords=self.config["job_portals"][0]["keywords"],
            target_companies=self.config["target_companies"],
            exclude_keywords=self.config["exclude_keywords"],
            exclude_roles=self.config["exclude_roles"],
            exclude_levels=self.config["exclude_levels"],
            max_experience=self.config["experience_years"],
            target_roles=self.config.get("roles", [])
        )
        return result
    
    def process_job(self, job: dict, seen_jobs: set) -> bool:
        """
        Process a single job autonomously.
        Returns True if notification was sent.
        """
        print(f"\n  🔍 Analyzing: {job['title']} at {job['company']}")
        print(f"     URL: {job['url']}")
        
        # Check if seen before
        is_new = job["url"] not in seen_jobs
        if not is_new:
            print(f"     ⏭️  Already processed")
            return False
        
        # Get full description
        description = utils.get_job_description(job["url"])
        if not description:
            print(f"     ⚠️  Could not fetch description")
            return False
        
        print(f"     📄 Description: {len(description)} chars")
        
        # Pre-filter by excluded roles/levels
        title_lower = job["title"].lower()
        desc_lower = description.lower()
        
        # Check for excluded roles in title
        for role in self.config["exclude_roles"]:
            if role.lower() in title_lower:
                print(f"     ❌ Excluded role in title: {role}")
                seen_jobs.add(job["url"])
                return False
        
        # Check for excluded levels
        for level in self.config["exclude_levels"]:
            if level.lower() in title_lower or level.lower() in desc_lower:
                print(f"     ❌ Excluded level: {level}")
                seen_jobs.add(job["url"])
                return False
        
        # Check for excessive experience requirements (more strict)
        import re
        max_exp = self.config.get("experience_years", 5)
        
        # Look for experience patterns
        exp_patterns = [
            r'(\d+)\+\s*(?:years?|yrs?)(?:\s+(?:of\s+)?experience)?',
            r'minimum\s+(?:of\s+)?(\d+)\s*(?:years?|yrs?)',
            r'(\d+)\s*(?:to|-)\s*(\d+)\s*(?:years?|yrs?)',
            r'at\s+least\s+(\d+)\s*(?:years?|yrs?)'
        ]
        
        for pattern in exp_patterns:
            matches = re.findall(pattern, desc_lower, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    # Range pattern (e.g., 5-7 years)
                    exp_max = int(match[-1])  # Get the higher number
                else:
                    exp_max = int(match)
                
                if exp_max > max_exp:
                    print(f"     ❌ Requires {exp_max}+ years experience (max: {max_exp})")
                    seen_jobs.add(job["url"])
                    return False
        
        # Check for management/leadership keywords
        leadership_keywords = [
            "manage team", "lead team", "managing team", "team management",
            "direct reports", "people management", "line management",
            "reporting to you", "leadership role", "management position"
        ]
        
        for keyword in leadership_keywords:
            if keyword in desc_lower:
                print(f"     ❌ Contains leadership requirement: {keyword}")
                seen_jobs.add(job["url"])
                return False
        
        # AI matching
        ai_result = self.ai_filter_job(job["title"], job["company"], description)
        print(f"     🤖 AI Match: {ai_result['match']} (confidence: {ai_result['confidence']:.2f})")
        print(f"     💭 Reason: {ai_result['reason']}")
        
        self.stats["matched_jobs"] += 1 if ai_result["match"] else 0
        
        # Send notification if match and high confidence
        if ai_result["match"] and ai_result["confidence"] >= 0.6:
            message = f"""🎯 New Job Match!

Title: {job['title']}
Company: {job['company']}
Confidence: {ai_result['confidence']:.0%}

{ai_result['reason']}

{job['url']}"""
            
            if utils.send_telegram(message):
                print(f"     ✅ Notification sent!")
                self.stats["notifications_sent"] += 1
                seen_jobs.add(job["url"])
                return True
            else:
                print(f"     ⚠️  Notification failed")
        
        # Mark as seen regardless
        seen_jobs.add(job["url"])
        return False
    
    def run(self):
        """Main autonomous execution"""
        print("🤖 Agentic Job Tracker Started\n")
        print("="*70)
        
        # Step 1: Cleanup check
        print("\n📋 Step 1: Checking cleanup requirements...")
        utils.check_and_cleanup()
        
        # Step 2: Load seen jobs
        print("📋 Step 2: Loading seen jobs...")
        seen_jobs = utils.load_seen_jobs()
        print(f"   Tracking {len(seen_jobs)} previously seen jobs\n")
        
        # Step 3: Process each job portal
        print("📋 Step 3: Searching job portals...")
        for portal in self.config["job_portals"]:
            print(f"\n{'='*70}")
            print(f"🔎 Portal: {portal['name']}")
            print(f"{'='*70}")
            
            # Scrape jobs
            jobs = utils.scrape_jobs(
                portal["career_page"],
                self.config["target_companies"]
            )
            
            print(f"\n   Found {len(jobs)} jobs from target companies")
            self.stats["total_jobs_found"] += len(jobs)
            
            # Process each job autonomously
            for job in jobs:
                notified = self.process_job(job, seen_jobs)
                if notified:
                    self.stats["new_jobs"] += 1
        
        # Step 4: Save state
        print(f"\n{'='*70}")
        print("📋 Step 4: Saving state...")
        utils.save_seen_jobs(seen_jobs)
        print("   ✅ State saved")
        
        # Step 5: Report
        print(f"\n{'='*70}")
        print("📊 FINAL REPORT")
        print(f"{'='*70}")
        print(f"   Total jobs found: {self.stats['total_jobs_found']}")
        print(f"   New jobs discovered: {self.stats['new_jobs']}")
        print(f"   Jobs matched criteria: {self.stats['matched_jobs']}")
        print(f"   Notifications sent: {self.stats['notifications_sent']}")
        print(f"   Total tracked: {len(seen_jobs)}")
        print(f"{'='*70}\n")
        print("✅ Agentic Job Tracker Completed!\n")


def main():
    """Entry point"""
    try:
        tracker = AgenticJobTracker()
        tracker.run()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
