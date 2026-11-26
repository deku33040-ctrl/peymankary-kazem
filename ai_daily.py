"""Daily AI content generation entrypoint.
Configure OPENAI_API_KEY in server Secrets. Run from a daily scheduled job.
By default it saves drafts. Set AI_AUTO_PUBLISH=1 only if you explicitly want direct publishing.
"""
import os
import app as site

if __name__ == "__main__":
    amount = max(1, min(50, int(os.environ.get("AI_DAILY_COUNT", "50"))))
    topic = os.environ.get("AI_DAILY_TOPIC", "همه موضوعات")
    auto_publish = os.environ.get("AI_AUTO_PUBLISH", "0") == "1"
    results = site.generate_ai_posts(count=amount, topic=topic, publish=auto_publish)
    mode = "منتشر شد" if auto_publish else "به‌صورت پیش‌نویس ذخیره شد"
    print(f"{len(results)} محتوا {mode}.")
