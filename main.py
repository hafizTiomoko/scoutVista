import os
import json
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

client = OpenAI(api_key=OPENAI_API_KEY)

class CollectorAgent:
    def __init__(self, topic: str, interest_profile: str):
        self.topic = topic
        self.interest_profile = interest_profile

    def search_google(self, limit: int = 10):
        url = "https://google.serper.dev/search"
        payload = json.dumps({"q": self.topic, "num": limit, "tbs": "qdr:w"})
        headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}
        try:
            response = requests.post(url, headers=headers, data=payload)
            results = response.json().get("organic", [])
            # DEBUG: Print what Google actually found
            print(f"  🔎 Google Found {len(results)} raw links:")
            for r in results[:3]:
                print(f"     - {r.get('title')}")
            return results
        except Exception as e:
            print(f"Error searching: {e}")
            return []

    def filter_and_rank(self, articles):
        if not articles: return []
        
        # 1. THE LAX PROMPT: We lower the standard from 7/10 to 3/10
        articles_context = "\n".join([f"ID: {i} | Title: {a.get('title')} | Snippet: {a.get('snippet')}" for i, a in enumerate(articles)])
        
        prompt = f"""
        I have a list of articles. The user is interested in: "{self.interest_profile}".
        
        Return a JSON object with a list of "selected_ids" for articles that are remotely relevant (Score > 3/10).
        If you are unsure, INCLUDE IT. Do not be strict.
        
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
            print(f"  🤖 AI Thought Process: {content}") # DEBUG: See what AI said
            ids = json.loads(content).get("selected_ids", [])
            return [articles[i] for i in ids if i < len(articles)]
        except Exception as e:
            print(f"  ❌ AI Filtering Error: {e}")
            return []

    def write_email(self, articles, is_fallback=False):
        if not articles: return None
        
        content = "\n".join([f"- {a['title']}: {a['link']}" for a in articles])
        
        prefix = ""
        if is_fallback:
            prefix = "NOTE: The AI filter found no high-confidence matches, so here are the raw top results:\n\n"

        prompt = f"Write a short executive summary for: {self.interest_profile}.\n\nData:\n{content}"
        
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
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"✅ Email sent to {to_email}")
    except Exception as e:
        print(f"❌ Failed to email {to_email}: {e}")

if __name__ == "__main__":
    with open("customers.json", "r") as f:
        customers = json.load(f)

    for cust in customers:
        print(f"\n--- Processing {cust['name']} ---")
        agent = CollectorAgent(cust['topic_query'], cust['interests'])
        
        raw_news = agent.search_google()
        filtered_news = agent.filter_and_rank(raw_news)
        
        # THE FALLBACK LOGIC
        if filtered_news:
            print(f"  Found {len(filtered_news)} relevant articles.")
            email_body = agent.write_email(filtered_news, is_fallback=False)
            send_email(cust['email'], f"Weekly Intel: {cust['name']}", email_body)
        elif raw_news:
            print(f"  ⚠️ No matches found. Sending top 3 raw links as backup.")
            # If AI rejects everything, send top 3 raw links anyway
            email_body = agent.write_email(raw_news[:3], is_fallback=True)
            send_email(cust['email'], f"Weekly Intel (Raw): {cust['name']}", email_body)
        else:
            print(f"  No news found at all (Google returned 0).")