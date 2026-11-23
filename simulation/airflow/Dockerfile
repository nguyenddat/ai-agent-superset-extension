FROM apache/airflow:2.10.5-python3.12

COPY requirements.txt /requirements.txt
COPY entrypoint.sh /opt/airflow-bootstrap.sh

USER root
RUN sed -i 's/\r$//' /opt/airflow-bootstrap.sh
USER airflow
RUN pip install --no-cache-dir -r /requirements.txt
