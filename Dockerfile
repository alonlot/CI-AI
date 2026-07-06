FROM node:20-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        python3 \
        python3-pip \
        python3-requests \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --break-system-packages --no-cache-dir anthropic

RUN npm install -g @anthropic-ai/claude-code

# claude refuses --dangerously-skip-permissions as root, so run as a normal user
RUN useradd -m -u 1001 reviewer

COPY ai_review /opt/ai-review/ai_review
COPY smart_lint /opt/ai-review/smart_lint
COPY skills /opt/ai-review/skills

ENV PYTHONUNBUFFERED=1 \
    AI_REVIEW_BUILTIN_SKILLS_DIR=/opt/ai-review/skills \
    PYTHONPATH=/opt/ai-review

USER reviewer

# default entrypoint is the review job; run the diff-only lint with:
#   python3 -m smart_lint
ENTRYPOINT ["python3", "-m", "ai_review"]
