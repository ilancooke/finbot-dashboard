FROM python:3.11-slim

WORKDIR /app

ENV FINBOT_DATA_ROOT=/data
ENV PYTHONUNBUFFERED=1
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_PORT=8501

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY .streamlit ./.streamlit
COPY finbot_dashboard ./finbot_dashboard

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
