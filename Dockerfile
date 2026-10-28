FROM python:3.11-slim

ARG INSTALL_SNOWFLAKE=false
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app

COPY pyproject.toml .
COPY src ./src
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir . \
    && if [ "$INSTALL_SNOWFLAKE" = "true" ]; then pip install --no-cache-dir ".[snowflake]"; fi

COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "streamlit_app/app.py", "--server.address=0.0.0.0"]
