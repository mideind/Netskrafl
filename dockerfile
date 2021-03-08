FROM python:3.8

WORKDIR /code-server

COPY requirements.txt .

RUN pip3 install --upgrade pip

RUN pip3 install -r requirements.txt

COPY src/ .

COPY resources/ ./resources

RUN python3 ./dawgbuilder.py

RUN python3 ./generate-secret.py

EXPOSE 6000

ENTRYPOINT [ "python3" ]

CMD ["main.py"]
