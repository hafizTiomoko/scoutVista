import os
import json
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict
from openai import OpenAI
from dotenv import load_dotenv

# --- VERSION CHECK ---
print("\n🚀 STARTING COLLECTOR AGENT V4.0 (CRM CONNECTED)\n")

load_dotenv()
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

client = OpenAI(api_key=OPENAI_API_KEY)

class CollectorAgent:
    def __init__(self, topic: str, interest_profile: str, crm_data: dict = None):
        self.topic = topic
        self.interest_profile = interest_profile
        self.crm = crm_data if crm_data else {}

    def search_google(self, limit: int = 10):
        url = "https://google.serper.dev/search"
        payload = json.dumps({"q": self.topic, "num": limit, "tbs": "qdr:w"})
        headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}
        try:
            response = requests.post(url, headers=headers, data=payload)
            results = response.json().get("organic", [])
            print(f"  🔎 Google returned {len(results)} links.")
            if results:
                print(f"     Example: {results[0].get('title')}")
            return results
        except Exception as e:
            print(f"Error searching: {e}")
            return []

    def filter_and_rank(self, articles):
        if not articles: return []
        
        articles_context = "\n".join([f"ID: {i} | Title: {a.get('title')} | Snippet: {a.get('snippet')}" for i, a in enumerate(articles)])
        
        prompt = f"""
        I have a list of articles. The user is interested in: "{self.interest_profile}".
        Return a JSON object with a list of "selected_ids" for ANY article that is even slightly relevant.
        If unsure, INCLUDE IT.
        Articles:
        {articles_context}
        """
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "You are a helpful curator. Output valid JSON."},
                          {"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            ids = json.loads(content).get("selected_ids", [])
            return [articles[i] for i in ids if i < len(articles)]
        except Exception as e:
            print(f"  ❌ AI Filtering Error: {e}")
            return []

    def _check_crm_match(self, article):
        """
        Scans the article text to see if it mentions a company in our CRM.
        Returns a formatted Action string if found.
        """
        text_to_scan = (article.get('title', '') + " " + article.get('snippet', '')).lower()
        
        for company, data in self.crm.items():
            # Check if company name is in the text
            if company.lower() in text_to_scan:
                strength = data.get('relationship_strength', 0)
                contacts = data.get('key_contacts', [])
                
                if contacts:
                    # Pick the highest priority contact
                    top_person = contacts[0]
                    return f" [🚀 ACTION: You have {strength} contacts at {company}. Reach out to {top_person['name']} ({top_person['role']})]"
        
        return ""

    def write_email(self, articles, is_fallback=False):
        if not articles: return None
        
        # Build the content list with CRM Actions appended
        content_lines = []
        for a in articles:
            crm_note = self._check_crm_match(a)
            line = f"- {a['title']}: {a['link']}{crm_note}"
            content_lines.append(line)
            
        content_block = "\n".join(content_lines)
        
        prefix = ""
        if is_fallback:
            prefix = "NOTE: AI found no high-confidence matches. Showing raw results:\n\n"
        
        prompt = f"""
        Write an executive summary for: {self.interest_profile}.
        
        IMPORTANT: The data below contains '🚀 ACTION' notes where the news matches the user's personal CRM network. 
        You MUST highlight these opportunities prominently in the summary.
        
        Data:
        {content_block}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return prefix + response.choices[0].message.content

def send_email(to_email, subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        # BCC Yourself (Optional - good for monitoring)
        # recipients = [to_email, EMAIL_ADDRESS] 
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"✅ Email sent to {to_email}")
    except Exception as e:
        print(f"❌ Failed to email {to_email}: {e}")

if __name__ == "__main__":
    # 1. LOAD CRM DATABASE
    crm_data = {}
    try:
        with open("user_crm.json", "r") as f:
            crm_data = json.load(f)
        print(f"📂 Loaded CRM data for {len(crm_data)} companies.")
    except FileNotFoundError:
        print("⚠️ user_crm.json not found. Running without CRM insights.")

    # 2. LOAD CUSTOMERS
    with open("customers.json", "r") as f:
        customers = json.load(f)

    # 3. RUN AGENT
    for cust in customers:
        print(f"\n--- Processing {cust['name']} ---")
        
        # Pass CRM data into the agent
        agent = CollectorAgent(cust['topic_query'], cust['interests'], crm_data)
        
        raw_news = agent.search_google()
        filtered_news = agent.filter_and_rank(raw_news)
        
        if filtered_news:
            print(f"  Found {len(filtered_news)} curated articles.")
            email_body = agent.write_email(filtered_news)
            send_email(cust['email'], f"Weekly Intel: {cust['name']}", email_body)
        elif raw_news:
            print(f"  ⚠️ Falling back to raw links.")
            email_body = agent.write_email(raw_news[:3], is_fallback=True)
            send_email(cust['email'], f"Weekly Intel (Raw): {cust['name']}", email_body)
        else:
            print(f"  No news found.")
