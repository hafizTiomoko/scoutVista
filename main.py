import os
import json
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict
from openai import OpenAI
from dotenv import load_dotenv

# Load env variables (You need to set these in your environment or .env file)
load_dotenv()
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")     # Your Gmail
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")   # Your Gmail App Password

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
            return response.json().get("organic", [])
        except Exception as e:
            print(f"Error searching: {e}")
            return []

    def filter_and_rank(self, articles):
        if not articles: return []
        print(f"🧠 Filtering {len(articles)} articles...")
        
        # We save tokens by only sending titles and snippets
        articles_context = "\n".join([f"ID: {i} | Title: {a.get('title')} | Snippet: {a.get('snippet')}" for i, a in enumerate(articles)])
        
        prompt = f"""
        Select articles relevant to: "{self.interest_profile}".
        Return JSON with "selected_ids" list of indices (0-10) that score > 7/10 in business value.
        Articles: {articles_context}
        """
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            ids = json.loads(response.choices[0].message.content).get("selected_ids", [])
            return [articles[i] for i in ids if i < len(articles)]
        except Exception:
            return []

    def write_email(self, articles):
        if not articles: return None
        content = "\n".join([f"- {a['title']}: {a['link']}" for a in articles])
        prompt = f"Write a short professional executive summary for: {self.interest_profile}.\n\nData:\n{content}"
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content

def send_email(to_email, subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        # Standard Gmail SMTP port
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"✅ Email sent to {to_email}")
    except Exception as e:
        print(f"❌ Failed to email {to_email}: {e}")

if __name__ == "__main__":
    # Load customers from JSON
    with open("customers.json", "r") as f:
        customers = json.load(f)

    for cust in customers:
        print(f"--- Processing {cust['name']} ---")
        agent = CollectorAgent(cust['topic_query'], cust['interests'])
        
        raw_news = agent.search_google()
        filtered_news = agent.filter_and_rank(raw_news)
        
        if filtered_news:
            email_body = agent.write_email(filtered_news)
            send_email(cust['email'], f"Weekly Intel: {cust['name']}", email_body)
        else:
            print(f"No relevant news for {cust['name']}")