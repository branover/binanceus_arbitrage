FROM python:3
WORKDIR /usr/src/app
COPY . .
CMD ["binanceus-arbitrage.py"]
RUN pip install requests
ENTRYPOINT ["python3"]
